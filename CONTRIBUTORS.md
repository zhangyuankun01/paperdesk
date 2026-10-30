# 贡献说明

## 项目发起与维护

[@zhangyuankun01](https://github.com/zhangyuankun01) 发起并维护纸间 PDF，提出中文化、现代简洁界面和面向普通用户的图片整理需求，并确定了轻量、本地运行的实现范围。

本项目新增与整合的工作包括：

- 中文界面、图片卡片、最终页码预览，以及三步操作流程。
- 拖放与按钮排序、自然排序、倒序、旋转、移除、清空与撤销。
- PDF 命名、A4 / Letter 自动方向与边距设置。
- 图片暂存、重复检测、失败时保留目标文件的保存方式。
- Windows 便携版、源码测试、打包程序检查及使用教程。
- 开源归属说明、许可证整理和 GitHub 发布。

这些实现、调试、测试与文档工作由维护者使用 **OpenAI Codex 辅助完成**，以 AI 辅助开发方式记录贡献。

## 上游贡献

纸间 PDF 的一部分处理逻辑来自 [PDF Arranger](https://github.com/pdfarranger/pdfarranger) 1.14.0，固定提交为 `29f306bb6932e28d3001b098f6dad9824ab74100`。

保留和适配的内容位于 `paperdesk/pdfarranger_port.py`：

- `Sides` 的边界字段定义。
- `_img_to_pdf`：图片转 PDF 与相关兼容处理。
- `_normalize_rectangle`、`_intersect_rectangle`、`_mediabox`：页面边界处理。
- `_scale`、`_update_angle`、`_apply_geom_transform`：页面缩放、旋转与几何变换。

上述复用内容的原始贡献归 PDF Arranger 作者及贡献者所有。原文件中的版权声明与 GPL-3.0-or-later 许可继续保留；完整上游贡献记录以原仓库为准。

## 其他组件

Qt / PySide6、img2pdf、pikepdf / QPDF、Pillow、lxml 等组件提供各自的界面或文档处理能力，其作者与许可归属见 `THIRD_PARTY_NOTICES.md`。
