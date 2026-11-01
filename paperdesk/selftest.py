# SPDX-License-Identifier: GPL-3.0-or-later
"""A packaged-app integration check; writes its evidence to the requested folder."""
from pathlib import Path
from io import BytesIO
from contextlib import closing
import json
import shutil
import sys
import time
import traceback

from PIL import Image, ImageDraw, ImageOps
import pikepdf
from PySide6.QtCore import QMimeData, Qt, QPointF
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from .engine import import_photo, export_pdf, ExportOptions, normalized_filename


def run(app, window, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "checks": []}
    def check(condition, text):
        if not condition:
            raise AssertionError(text)
        report["checks"].append(text)
    try:
        app.processEvents()
        window.grab().save(str(output / "01_空白界面.png"))
        paths = []
        for n, size, color in [(1, (480, 640), "#f5bfac"), (2, (640, 480), "#b5d4fa")]:
            image = Image.new("RGB", size, color)
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 120, 100), fill="#263b68")
            draw.text((40, 160), f"IMAGE {n}", fill="black", font_size=38)
            path = output / f"测试图片_{n:02}.png"
            image.save(path)
            paths.append(str(path))
        # Import through the same asynchronous path used by native file drops.
        window.add_paths(paths)
        deadline = time.monotonic() + 30
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        check(not window.busy and window.photos.count() == 2, "异步导入两张中文路径图片")
        window.add_paths(paths)
        check(window.photos.count() == 2 and not window.busy, "重复添加不产生重复页面")
        window.photos.setCurrentRow(0)
        app.processEvents()
        # Exercise the drop handler with real Qt MIME and drop-event objects.
        first_uid = window.ordered()[0].uid
        mime = QMimeData()
        mime.setData("application/x-paperdesk-page", first_uid.encode())
        position = window.photos.visualItemRect(window.photos.item(1)).center()
        event = QDropEvent(QPointF(position), Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        window.photos.dropEvent(event)
        check(window.ordered()[1].uid == first_uid and window.photos.count() == 2, "Qt 拖放事件调整页序且不丢失页面")
        QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
        check(window.ordered()[0].uid == first_uid, "撤销恢复拖动前的页序")
        window.photos.setCurrentRow(0)
        QTest.mouseClick(window.next_button, Qt.MouseButton.LeftButton)
        check(window.ordered()[1].uid == first_uid, "按钮调整页序")
        QTest.mouseClick(window.rotate_button, Qt.MouseButton.LeftButton)
        check(window.ordered()[1].angle == 90, "选中图片顺时针旋转 90 度")
        window.filename.setText("中文合并结果.pdf")
        result = output / "中文合并结果.pdf"
        original_dialog = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(result), "PDF 文件 (*.pdf)")
        try:
            QTest.mouseClick(window.export_button, Qt.MouseButton.LeftButton)
        finally:
            QFileDialog.getSaveFileName = original_dialog
        deadline = time.monotonic() + 30
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        check(result.is_file() and not window.busy, "生成按钮经后台任务完成中文文件名保存")
        check(window.open_pdf.isVisible(), "生成成功后显示打开文件入口")
        with pikepdf.Pdf.open(result) as doc:
            check(len(doc.pages) == 2, "生成结果为两页 PDF")
            check(int(doc.pages[1].get('/Rotate', 0)) % 360 == 90, "导出的第二页保留旋转")
            colors = []
            for page in doc.pages:
                image = pikepdf.PdfImage(next(iter(page.Resources.XObject.values()))).as_pil_image().convert('RGB')
                colors.append(image.getpixel((200, 200)))
            check(colors == [(181, 212, 250), (245, 191, 172)], "导出图片顺序为 02、01 且色彩像素一致")
        app.processEvents()
        window.grab().save(str(output / "02_整理与导出界面.png"))
        a4 = output / "A4打印版.pdf"
        export_pdf(window.ordered(), str(a4), ExportOptions("a4", "auto", 10))
        with pikepdf.Pdf.open(a4) as doc:
            check(len(doc.pages) == 2 and float(doc.pages[0].MediaBox[2]) > float(doc.pages[0].MediaBox[3]), "A4 自动方向与页数正确")
        QTest.mouseClick(window.remove_button, Qt.MouseButton.LeftButton)
        check(window.photos.count() == 1 and all(Path(p).exists() for p in paths), "移除页面保留原始图片")
        QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
        check(window.photos.count() == 2, "撤销恢复已移除页面")
        QTest.mouseClick(window.clear_button, Qt.MouseButton.LeftButton)
        check(window.photos.count() == 0 and not window.export_button.isEnabled(), "空列表禁用导出，避免误操作")
        QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
        check(window.photos.count() == 2, "清空后可撤销恢复")
        window.filename.setText("无效/名称")
        window.choose_export()
        check("文件名不能" in window.notice.text(), "非法文件名提供中文提示")
        window.filename.setText("图片合并.pdf")
        # Exercise the actual bundled decoders, not just file extensions.
        fixtures = (Path(sys._MEIPASS) / "test-fixtures" if getattr(sys, "frozen", False)
                    else Path(__file__).resolve().parent.parent / "tests" / "fixtures")
        format_paths, expected_images = [], []
        for name in ("phone.heic", "rotated.heic", "primary.heic", "ten-bit.heif"):
            path = output / name
            shutil.copyfile(fixtures / name, path)
            format_paths.append(str(path))
        for extension, format, mode in [
            ("jfif", "JPEG", "RGB"), ("avif", "AVIF", "RGB"),
            ("jp2", "JPEG2000", "RGB"), ("ico", "ICO", "RGB"),
            ("pcx", "PCX", "RGB"), ("tga", "TGA", "RGB"),
            ("pgm", "PPM", "L"), ("dds", "DDS", "RGB"),
            ("qoi", "QOI", "RGB"), ("img", "PNG", "RGB"),
        ]:
            path = output / ("格式测试." + extension)
            Image.new("RGB", (96, 96), (180, 90, 40)).convert(mode).save(path, format=format)
            format_paths.append(str(path))
        window.clear_images()
        imported = {}
        original_finished = window.import_finished
        def capture_import(result):
            imported["errors"] = result[1]
            if not result[1]:
                original_finished(result)
        window.import_finished = capture_import
        try:
            window.add_paths(format_paths)
            deadline = time.monotonic() + 30
            while window.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
        finally:
            window.import_finished = original_finished
        check(not window.busy and window.photos.count() == len(format_paths),
              "打包版异步导入 HEIC/HEIF、AVIF、JFIF 等 14 张图片：" + str(imported.get("errors", [])))
        merged = output / "多格式合并.pdf"
        export_pdf(window.ordered(), str(merged), ExportOptions())
        with pikepdf.Pdf.open(merged) as pdf:
            check(len(pdf.pages) == len(format_paths), "混合格式导出 PDF 页数正确")
            for photo, page in zip(window.ordered(), pdf.pages):
                with closing(Image.open(photo.source)) as opened:
                    expected = ImageOps.exif_transpose(opened)
                    expected.load()
                embedded = pikepdf.PdfImage(next(iter(page.Resources.XObject.values()))).as_pil_image().convert("RGB")
                check(embedded.size == expected.size and
                      embedded.getpixel((40, 40)) == expected.convert("RGB").getpixel((40, 40)),
                      photo.name + " 转换后尺寸、像素和顺序正确")
        rotated = next(p for p in window.ordered() if p.name == "rotated.heic")
        check((rotated.width, rotated.height) == (64, 96), "HEIC 方向信息正确应用")
        primary = next(p for p in window.ordered() if p.name == "primary.heic")
        with Image.open(BytesIO(primary.thumb)) as preview:
            r, g, b, _ = preview.getpixel((40, 40))
            check(b > 240 and r < 10 and g < 10, "多图 HEIC 使用指定主图而非第零帧")
        window.notice.setText("HEIC/HEIF、AVIF 等格式导入与 PDF 导出验证完成。")
        app.processEvents()
        window.grab().save(str(output / "03_多格式导入.png"))
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        (output / "验收记录.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not report["passed"] and sys_stdout_available():
            print(report.get("error"))
        window.staging.cleanup()
        app.exit(0 if report["passed"] else 1)


def sys_stdout_available():
    import sys
    return sys.stdout is not None
