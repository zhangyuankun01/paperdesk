# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import sys

from PySide6.QtCore import Qt, QSize, Signal, QObject, QRunnable, QThreadPool, QSettings, QUrl, QRectF, QMimeData
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QFont, QShortcut, QKeySequence, QTransform, QDesktopServices, QDrag
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QListWidget, QListWidgetItem, QAbstractItemView, QLineEdit,
    QComboBox, QFileDialog, QMessageBox, QProgressBar, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem,
)

from .engine import Photo, ExportOptions, import_photo, export_pdf, natural_key, normalized_filename, friendly_error, IMAGE_FILE_FILTER
from . import __version__


STYLE = """
QMainWindow, QWidget#root { background: #f4f6fb; color: #1d293d; }
QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: 13px; color: #24334b; }
QFrame#header, QFrame#settings { background: white; border: 1px solid #e3e8f1; border-radius: 16px; }
QLabel#brand { color: #2563eb; font-size: 20px; font-weight: 700; }
QLabel#title { font-size: 27px; font-weight: 700; color: #17253c; }
QLabel#muted { color: #718096; }
QLabel#section { font-size: 16px; font-weight: 700; }
QLabel#field { color: #526079; font-size: 12px; font-weight: 600; }
QLabel#notice { padding: 11px 14px; border-radius: 8px; background: #eaf1ff; color: #2855a2; }
QPushButton { background: white; border: 1px solid #dce3ef; border-radius: 8px; padding: 9px 12px; }
QPushButton:hover { background: #eff5ff; border-color: #9bbbf7; }
QPushButton:pressed { background: #dfeaff; }
QPushButton:disabled { color: #a3acba; background: #f2f4f8; border-color: #e6e9ee; }
QPushButton#primary { background: #2563eb; border-color: #2563eb; color: white; font-weight: 700; padding: 12px 18px; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #c6d5f5; border-color: #c6d5f5; color: #f6f8ff; }
QPushButton#link { border: 0; background: transparent; color: #5376b6; padding: 4px; }
QLineEdit, QComboBox { background: #f9fbff; border: 1px solid #dce3ef; border-radius: 8px; padding: 10px; min-height: 22px; }
QLineEdit:focus, QComboBox:focus { border-color: #2563eb; }
QComboBox::drop-down { border: 0; width: 25px; }
QComboBox::down-arrow { image: url("__ARROW__"); width: 10px; height: 7px; }
QListWidget { background: transparent; border: 0; outline: 0; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #ccd5e5; border-radius: 4px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar { border: 0; border-radius: 3px; background: #e7edf8; height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #2563eb; border-radius: 3px; }
"""


class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int)


class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, TaskSignals()

    def run(self):
        try:
            self.signals.result.emit(self.fn(self.signals.progress))
        except Exception as exc:
            self.signals.error.emit(friendly_error(exc))


class PhotoList(QListWidget):
    files_dropped = Signal(list)
    reordered = Signal()

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setGridSize(QSize(202, 241))
        self.setSpacing(5)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setItemDelegate(PhotoDelegate(self))
        self.setAccessibleName("图片列表，可拖动调整页序")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-paperdesk-page"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-paperdesk-page"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        elif event.mimeData().hasFormat("application/x-paperdesk-page"):
            uid = bytes(event.mimeData().data("application/x-paperdesk-page")).decode()
            source = next((i for i in range(self.count()) if self.item(i).data(Qt.ItemDataRole.UserRole).uid == uid), -1)
            target = self.indexAt(event.position().toPoint()).row()
            if target < 0:
                target = self.count()-1
            if source >= 0 and target != source:
                item = self.takeItem(source)
                self.insertItem(target, item)
                self.setCurrentItem(item)
            self.reordered.emit()
            event.acceptProposedAction()

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None:
            return
        mime = QMimeData()
        mime.setData("application/x-paperdesk-page", item.data(Qt.ItemDataRole.UserRole).uid.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.viewport().rect()).adjusted(15, 20, -15, -20)
            painter.setPen(QColor("#b9c9e6"))
            painter.setBrush(QColor("#f9fbff"))
            painter.drawRoundedRect(rect, 16, 16)
            painter.setPen(QColor("#2563eb"))
            painter.setFont(QFont("Microsoft YaHei UI", 40))
            painter.drawText(rect.adjusted(0, -65, 0, 0), Qt.AlignmentFlag.AlignCenter, "＋")
            painter.setPen(QColor("#263955"))
            painter.setFont(QFont("Microsoft YaHei UI", 17, QFont.Weight.DemiBold))
            painter.drawText(rect.adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignCenter, "把图片拖到这里")
            painter.setPen(QColor("#78869a"))
            painter.setFont(QFont("Microsoft YaHei UI", 10))
            painter.drawText(rect.adjusted(0, 110, 0, 0), Qt.AlignmentFlag.AlignCenter, "或点击上方「添加图片」 · 支持一次添加多张")


class PhotoDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(192, 231)

    def paint(self, painter, option, index):
        photo: Photo = index.data(Qt.ItemDataRole.UserRole)
        if photo is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor("#eef4ff" if selected else "#ffffff"))
        painter.setPen(QColor("#6c99f0" if selected else "#e0e6ef"))
        painter.drawRoundedRect(rect, 12, 12)
        preview = rect.adjusted(12, 14, -12, -63)
        painter.fillRect(preview, QColor("#f3f5f9"))
        pix = QPixmap()
        pix.loadFromData(photo.thumb)
        if photo.angle:
            pix = pix.transformed(QTransform().rotate(photo.angle), Qt.TransformationMode.SmoothTransformation)
        pix = pix.scaled(preview.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(int(preview.center().x() - pix.width()/2), int(preview.center().y() - pix.height()/2), pix)
        badge = QRectF(rect.x() + 8, rect.y() + 8, 28, 24)
        painter.setBrush(QColor("#2563eb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge, 7, 7)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index.row()+1))
        painter.setPen(QColor("#25344c"))
        painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        name = painter.fontMetrics().elidedText(photo.name, Qt.TextElideMode.ElideMiddle, int(rect.width()-24))
        painter.drawText(rect.adjusted(12, rect.height()-52, -12, -27), Qt.AlignmentFlag.AlignVCenter, name)
        painter.setPen(QColor("#8390a4"))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        w, h = photo.display_size
        painter.drawText(rect.adjusted(12, rect.height()-27, -12, -7), Qt.AlignmentFlag.AlignVCenter, f"{w} × {h}  ·  第 {index.row()+1} 页")
        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("纸间 PDF · 图片转 PDF")
        self.resize(1160, 780)
        self.setMinimumSize(980, 680)
        self.setAcceptDrops(True)
        self.staging = tempfile.TemporaryDirectory(prefix="paperdesk-")
        self.history: list[list[Photo]] = []
        self.busy = False
        self.last_output = ""
        self.settings = QSettings("PaperDesk", "ImageToPDF")
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.task = None
        self._build()
        asset_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets"
        self.setStyleSheet(STYLE.replace("__ARROW__", (asset_root / "down.png").as_posix()))
        for sequence, fn in [("Ctrl+O", self.choose_images), ("Ctrl+S", self.choose_export), ("Ctrl+Z", self.undo), ("Delete", self.remove_selected), ("Alt+Left", lambda: self.move_selected(-1)), ("Alt+Right", lambda: self.move_selected(1))]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(fn)
        self.update_controls()

    def _build(self):
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 22, 26, 15)
        outer.setSpacing(18)
        header = QFrame(objectName="header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 15, 22, 15)
        header_layout.addWidget(QLabel("纸间 PDF", objectName="brand"))
        header_layout.addStretch()
        header_layout.addWidget(QLabel("本地处理  ·  离线可用", objectName="muted"))
        about = QPushButton("关于", objectName="link")
        about.clicked.connect(self.about)
        header_layout.addWidget(about)
        outer.addWidget(header)
        outer.addWidget(QLabel("把图片，整理成一份 PDF", objectName="title"))
        outer.addWidget(QLabel("① 添加图片     →     ② 调整顺序     →     ③ 命名并生成 PDF", objectName="muted"))
        body = QHBoxLayout()
        body.setSpacing(22)
        outer.addLayout(body, 1)
        left = QVBoxLayout()
        left.setSpacing(10)
        body.addLayout(left, 1)
        toolbar = QHBoxLayout()
        self.add_button = self.button("＋ 添加图片", self.choose_images, "primary")
        toolbar.addWidget(self.add_button)
        self.sort_button = self.button("按名称排序", self.sort_images)
        toolbar.addWidget(self.sort_button)
        self.reverse_button = self.button("倒序", self.reverse_images)
        toolbar.addWidget(self.reverse_button)
        toolbar.addStretch()
        self.count_label = QLabel("0 张图片", objectName="muted")
        toolbar.addWidget(self.count_label)
        left.addLayout(toolbar)
        self.photos = PhotoList()
        self.photos.files_dropped.connect(self.add_paths)
        self.photos.reordered.connect(self.after_drag)
        self.photos.currentRowChanged.connect(self.update_controls)
        self.photos.itemDoubleClicked.connect(self.preview)
        left.addWidget(self.photos, 1)
        actions = QHBoxLayout()
        self.previous_button = self.button("← 前移", lambda: self.move_selected(-1))
        self.next_button = self.button("后移 →", lambda: self.move_selected(1))
        self.rotate_button = self.button("旋转 90°", self.rotate_selected)
        self.remove_button = self.button("移除", self.remove_selected)
        self.undo_button = self.button("撤销", self.undo)
        for b in (self.previous_button, self.next_button, self.rotate_button, self.remove_button, self.undo_button):
            actions.addWidget(b)
        actions.addStretch()
        self.clear_button = self.button("清空", self.clear_images)
        actions.addWidget(self.clear_button)
        left.addLayout(actions)
        left.addWidget(QLabel("拖动图片即可换序；也可以选中后点击前移、后移。双击可放大查看。", objectName="muted"))
        settings = QFrame(objectName="settings")
        settings.setFixedWidth(292)
        panel = QVBoxLayout(settings)
        panel.setContentsMargins(22, 20, 22, 20)
        panel.setSpacing(9)
        panel.addWidget(QLabel("生成你的 PDF", objectName="section"))
        panel.addWidget(QLabel("一张图片一页，按左侧顺序合并。", objectName="muted"))
        panel.addSpacing(6)
        panel.addWidget(QLabel("PDF 文件名", objectName="field"))
        self.filename = QLineEdit("图片合并.pdf")
        self.filename.setAccessibleName("PDF 文件名")
        self.filename.setClearButtonEnabled(True)
        self.filename.textEdited.connect(self.invalidate_result)
        panel.addWidget(self.filename)
        panel.addWidget(QLabel("页面大小", objectName="field"))
        self.paper = QComboBox()
        self.paper.addItem("跟随图片尺寸 · 推荐", "original")
        self.paper.addItem("A4 · 适合打印", "a4")
        self.paper.addItem("Letter · 美式信纸", "letter")
        self.paper.currentIndexChanged.connect(self.update_controls)
        self.paper.currentIndexChanged.connect(self.invalidate_result)
        panel.addWidget(self.paper)
        self.orientation = QComboBox(settings)
        for text, value in [("自动判断 · 推荐", "auto"), ("统一竖向", "portrait"), ("统一横向", "landscape")]:
            self.orientation.addItem(text, value)
        self.orientation.currentIndexChanged.connect(self.invalidate_result)
        self.orientation.hide()
        self.margin = QComboBox(settings)
        self.margin.addItem("留白 10 毫米 · 推荐", 10)
        self.margin.addItem("无边距", 0)
        self.margin.addItem("留白 20 毫米", 20)
        self.margin.currentIndexChanged.connect(self.invalidate_result)
        self.margin.hide()
        note = QLabel("保持图片比例，完整放入页面。\nA4 和 Letter 自动选方向，留白 10 毫米。", objectName="muted")
        note.setWordWrap(True)
        panel.addWidget(note)
        panel.addStretch()
        self.summary = QLabel("添加图片后，即可生成 PDF。", objectName="muted")
        self.summary.setWordWrap(True)
        self.summary.hide()
        self.export_button = self.button("生成 PDF", self.choose_export, "primary")
        self.export_button.setMinimumHeight(49)
        self.export_button.setToolTip("点击后选择 PDF 的保存位置")
        panel.addWidget(self.export_button)
        body.addWidget(settings)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.notice = QLabel("准备好了：添加图片，开始整理。", objectName="notice")
        self.notice.setWordWrap(True)
        outer.addWidget(self.notice)
        self.open_row = QHBoxLayout()
        self.open_pdf = self.button("打开 PDF", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output)))
        self.open_folder = self.button("打开所在文件夹", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.last_output).parent))))
        self.open_pdf.hide()
        self.open_folder.hide()
        self.open_row.addWidget(self.open_pdf)
        self.open_row.addWidget(self.open_folder)
        self.open_row.addStretch()
        outer.addLayout(self.open_row)

    @staticmethod
    def button(text, fn, name=""):
        button = QPushButton(text)
        if name:
            button.setObjectName(name)
        button.clicked.connect(fn)
        return button

    def ordered(self):
        return [self.photos.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.photos.count())]

    def snapshot(self):
        self.history.append(self.ordered())
        self.history = self.history[-30:]

    def invalidate_result(self, *_):
        self.open_pdf.hide()
        self.open_folder.hide()
        self.last_output = ""
        self.notice.setText("设置或图片已更新，点击「生成 PDF」保存当前版本。")

    def display(self, photos: list[Photo], selected: str = ""):
        self.invalidate_result()
        self.photos.clear()
        for photo in photos:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, photo)
            item.setData(Qt.ItemDataRole.DisplayRole, photo.name)
            item.setToolTip(photo.source)
            item.setSizeHint(QSize(192, 231))
            self.photos.addItem(item)
            if photo.uid == selected:
                self.photos.setCurrentItem(item)
        self.last_order = self.ordered()
        self.update_controls()

    def update_controls(self, *_):
        n, row = self.photos.count(), self.photos.currentRow()
        ready = not self.busy
        for b in (self.sort_button, self.reverse_button, self.clear_button, self.export_button):
            b.setEnabled(ready and n > 0)
        self.add_button.setEnabled(ready)
        self.photos.setEnabled(ready)
        self.previous_button.setEnabled(ready and row > 0)
        self.next_button.setEnabled(ready and 0 <= row < n-1)
        for b in (self.rotate_button, self.remove_button):
            b.setEnabled(ready and row >= 0)
        self.undo_button.setEnabled(ready and bool(self.history))
        original = self.paper.currentData() == "original"
        self.orientation.setEnabled(ready and not original)
        self.margin.setEnabled(ready and not original)
        self.filename.setEnabled(ready)
        self.paper.setEnabled(ready)
        self.count_label.setText(f"{n} 张图片")
        self.summary.setText(f"将生成 {n} 页 PDF，保存时可选择位置。" if n else "添加图片后，即可生成 PDF。")
        self.export_button.setText("正在处理…" if self.busy else "生成 PDF")

    def choose_images(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "添加图片", self.settings.value("input_dir", ""), IMAGE_FILE_FILTER)
        if paths:
            self.settings.setValue("input_dir", str(Path(paths[0]).parent))
            self.add_paths(paths)

    def add_paths(self, paths):
        if self.busy or not paths:
            return
        known = {p.source.casefold() for p in self.ordered()}
        unique = []
        for path in paths:
            resolved = str(Path(path).resolve())
            if resolved.casefold() not in known:
                unique.append(resolved)
                known.add(resolved.casefold())
        if not unique:
            self.notice.setText("这些图片已经添加过了，无需重复添加。")
            return
        unique.sort(key=lambda p: natural_key(Path(p).name))
        def load(progress):
            added, errors, animated = [], [], 0
            for i, path in enumerate(unique):
                try:
                    photo, multi = import_photo(path, self.staging.name)
                    added.append(photo)
                    animated += int(multi)
                except Exception as exc:
                    errors.append(f"{Path(path).name}：{friendly_error(exc)}")
                progress.emit(int((i+1)*100/len(unique)))
            return added, errors, animated
        self.run_task(load, self.import_finished, "正在读取图片…")

    def run_task(self, fn, done, text):
        self.busy = True
        self.open_pdf.hide()
        self.open_folder.hide()
        self.progress.setValue(0)
        self.progress.show()
        self.notice.setText(text)
        self.update_controls()
        self.task = Task(fn)
        self.task.signals.progress.connect(self.progress.setValue)
        self.task.signals.result.connect(lambda result: self.finish_task(done, result))
        self.task.signals.error.connect(self.task_failed)
        self.pool.start(self.task)

    def finish_task(self, fn, result):
        self.busy = False
        self.progress.hide()
        fn(result)
        self.update_controls()

    def task_failed(self, message):
        self.busy = False
        self.progress.hide()
        self.notice.setText("处理失败：" + message)
        self.update_controls()

    def import_finished(self, result):
        added, errors, animated = result
        if added:
            self.snapshot()
            self.display(self.ordered() + added, added[0].uid)
        self.notice.setText(f"已添加 {len(added)} 张图片。拖动缩略图可以调整顺序。" + (f"其中 {animated} 张多帧图片使用首帧（HEIC/HEIF 使用主图）。" if animated else ""))
        if errors:
            box = QMessageBox(self)
            box.setWindowTitle("部分图片没有添加")
            box.setText(f"已添加 {len(added)} 张，另有 {len(errors)} 个文件无法添加。")
            box.setDetailedText("\n".join(errors))
            box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
            box.exec()

    def after_drag(self):
        previous = getattr(self, "last_order", [])
        current = self.ordered()
        if [p.uid for p in current] != [p.uid for p in previous]:
            self.invalidate_result()
            self.history.append(previous)
            self.last_order = current
            self.notice.setText("页序已调整，按左侧编号生成 PDF。")
        self.photos.viewport().update()
        self.update_controls()

    def move_selected(self, delta):
        if self.busy:
            return
        row, ordered = self.photos.currentRow(), self.ordered()
        target = row + delta
        if row < 0 or not 0 <= target < len(ordered):
            return
        self.snapshot()
        ordered[row], ordered[target] = ordered[target], ordered[row]
        self.display(ordered, ordered[target].uid)

    def rotate_selected(self):
        if self.busy or self.photos.currentRow() < 0:
            return
        self.snapshot()
        row, ordered = self.photos.currentRow(), self.ordered()
        ordered[row] = replace(ordered[row], angle=(ordered[row].angle + 90) % 360)
        self.display(ordered, ordered[row].uid)

    def remove_selected(self):
        if self.busy or self.photos.currentRow() < 0:
            return
        self.snapshot()
        row, ordered = self.photos.currentRow(), self.ordered()
        ordered.pop(row)
        self.display(ordered, ordered[min(row, len(ordered)-1)].uid if ordered else "")
        self.notice.setText("已从列表移除，原始图片保留。点击「撤销」可以恢复。")

    def undo(self):
        if not self.busy and self.history:
            self.display(self.history.pop())
            self.notice.setText("已撤销上一步操作。")

    def sort_images(self):
        if self.busy:
            return
        self.snapshot()
        self.display(sorted(self.ordered(), key=lambda p: natural_key(p.name)))

    def reverse_images(self):
        if self.busy:
            return
        self.snapshot()
        self.display(list(reversed(self.ordered())))

    def clear_images(self):
        if not self.busy and self.photos.count():
            self.snapshot()
            self.display([])
            self.notice.setText("列表已清空，可以添加新图片。点击「撤销」可以恢复。")

    def preview(self, item):
        from PySide6.QtWidgets import QDialog
        photo: Photo = item.data(Qt.ItemDataRole.UserRole)
        dialog = QDialog(self)
        dialog.setWindowTitle(photo.name + " · 图片预览")
        dialog.resize(800, 650)
        layout = QVBoxLayout(dialog)
        # Preview thumbnails already account for camera EXIF orientation.
        pix = QPixmap()
        pix.loadFromData(photo.thumb)
        pix = pix.transformed(QTransform().rotate(photo.angle), Qt.TransformationMode.SmoothTransformation)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(pix.scaled(760, 560, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(label, 1)
        layout.addWidget(self.button("关闭预览", dialog.accept))
        dialog.exec()

    def choose_export(self):
        if self.busy or not self.photos.count():
            return
        try:
            filename = normalized_filename(self.filename.text())
        except ValueError as exc:
            self.notice.setText(str(exc))
            self.filename.setFocus()
            return
        initial = str(Path(self.settings.value("output_dir", str(Path.home() / "Documents"))) / filename)
        target, _ = QFileDialog.getSaveFileName(self, "保存 PDF", initial, "PDF 文件 (*.pdf)")
        if not target:
            return
        if not target.lower().endswith(".pdf"):
            target += ".pdf"
        self.filename.setText(Path(target).name)
        self.settings.setValue("output_dir", str(Path(target).parent))
        photos, options = self.ordered(), self.export_options()
        def save(progress):
            export_pdf(photos, target, options, lambda done, total: progress.emit(int(done*100/total)))
            return target
        self.run_task(save, self.export_finished, f"正在生成 {len(photos)} 页 PDF…")

    def export_options(self):
        return ExportOptions(self.paper.currentData(), self.orientation.currentData(), self.margin.currentData())

    def export_finished(self, target):
        self.last_output = target
        self.notice.setText(f"PDF 已生成 · 共 {self.photos.count()} 页 · {Path(target).name}")
        self.open_pdf.show()
        self.open_folder.show()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.add_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle("关于纸间 PDF")
        box.setText(f"纸间 PDF {__version__}\n\n中文图片转 PDF 工具。图片在本机处理。\n支持 HEIC/HEIF、AVIF、JPG、PNG 等图片。\n\n基于 PDF Arranger 1.14.0 的图片转换与页面变换源码改造，使用 GPL-3.0-or-later 许可证。\n完整源码在软件文件夹内的 modern-pdf 与 upstream-pdfarranger。")
        box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def closeEvent(self, event):
        if self.busy:
            self.notice.setText("正在处理文件，请完成后再关闭。")
            event.ignore()
        else:
            self.staging.cleanup()
            event.accept()
