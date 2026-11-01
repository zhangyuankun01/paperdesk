# SPDX-License-Identifier: GPL-3.0-or-later
import faulthandler
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    smoke = "--self-test" in sys.argv
    if smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon, QFont, QFontDatabase
    from PySide6.QtCore import QTimer
    from paperdesk.window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("纸间 PDF")
    from paperdesk import __version__
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    # Register Windows fonts explicitly so CJK also renders in Qt's offscreen
    # verification mode, which does not enumerate the system font database.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for font_file in ("msyh.ttc", "msyhbd.ttc", "arial.ttf"):
        if (fonts / font_file).exists():
            QFontDatabase.addApplicationFont(str(fonts / font_file))
    app.setFont(QFont("Microsoft YaHei", 10))
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon = base / "assets" / "app.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    screen = app.primaryScreen().availableGeometry()
    window.resize(min(1160, screen.width()-50), min(780, screen.height()-60))
    window.show()
    if smoke:
        from paperdesk.selftest import run
        output = Path(sys.argv[sys.argv.index("--self-test")+1])
        QTimer.singleShot(150, lambda: run(app, window, output))
    else:
        paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
        if paths:
            QTimer.singleShot(100, lambda: window.add_paths(paths))
    return app.exec()


if __name__ == "__main__":
    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PaperDesk"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "crash.log").open("a", encoding="utf-8") as crash_log:
        faulthandler.enable(crash_log)
        try:
            sys.exit(main())
        except Exception:
            traceback.print_exc(file=crash_log)
            from ctypes import windll
            windll.user32.MessageBoxW(None, "启动失败。请查看用户目录 AppData\\Local\\PaperDesk\\crash.log。", "纸间 PDF", 16)
            raise
