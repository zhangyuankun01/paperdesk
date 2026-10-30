# 第三方组件与来源

本项目改造源码使用 GPL-3.0-or-later。第三方组件按各自许可证分发，原版权声明与许可正文随便携包保留。

| 组件 | 版本 / 基准 | 用途 | 许可与源码来源 |
| --- | --- | --- | --- |
| PDF Arranger | 1.14.0，提交 29f306bb6932e28d3001b098f6dad9824ab74100 | 复用图片转 PDF、页面边界与几何变换函数 | GPL-3.0-or-later；https://github.com/pdfarranger/pdfarranger |
| PySide6 Essentials / shiboken6 | 6.12.0 | Qt 桌面界面、拖放、文件对话框 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Qt | 6.12.0 | PySide6 所用动态链接桌面库 | 组件各自的 Qt 开源许可；https://code.qt.io/cgit/qt/ |
| img2pdf | 0.6.3 | 图片嵌入 PDF | LGPL-3.0；https://gitlab.mister-muffin.de/josch/img2pdf |
| pikepdf | 10.17.0 | PDF 页面组织与保存 | MPL-2.0；https://github.com/pikepdf/pikepdf |
| QPDF | 由 pikepdf wheel 附带 | 底层 PDF 处理 | Apache-2.0；https://github.com/qpdf/qpdf |
| Pillow | 13.0.0 | 图片识别、缩略图与格式转换 | MIT-CMU；https://github.com/python-pillow/Pillow |
| lxml | 6.1.3 | 元数据 XML 处理 | BSD-3-Clause 及其依赖许可；https://github.com/lxml/lxml |
| CPython | 3.11.15，Windows 包内运行时 | Python 运行环境 | PSF 许可及附带第三方许可；https://github.com/python/cpython |

依赖版本以 `requirements.txt` 与发布包内的组件信息为准。便携包 `licenses/` 目录保留所用 wheel 附带的许可文本，`_internal` 中的 Qt 等库采用动态链接形式。

## PDF Arranger 的衍生关系

上游 `pdfarranger/core.py` 和 `pdfarranger/exporter.py` 中的部分处理函数被保留和适配到 `paperdesk/pdfarranger_port.py`，其版权不归本项目维护者独占。具体函数与固定提交见 `third_party/PDF_ARRANGER_SOURCE.txt`。

本仓库提供本项目的完整源码；发布的 Windows ZIP 另附 `modern-pdf/` 本项目源码与 `upstream-pdfarranger/` 上游基准源码。
