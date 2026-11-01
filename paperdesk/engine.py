# SPDX-License-Identifier: GPL-3.0-or-later
"""Image ingestion and atomic PDF export, independent of the GUI."""
from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import dataclass, replace
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
from typing import Callable

from PIL import Image, ImageOps, UnidentifiedImageError
from pi_heif import register_heif_opener
import pikepdf

from .pdfarranger_port import Sides, _img_to_pdf, _apply_geom_transform

# Register once, before background import jobs. The bundled decoder works
# without the Windows Store HEIF/HEVC extensions or an internet connection.
register_heif_opener(thumbnails=False)
IMAGE_FORMATS = (
    "JPEG", "PNG", "WEBP", "BMP", "DIB", "GIF", "TIFF", "HEIF", "AVIF",
    "JPEG2000", "ICO", "PCX", "TGA", "PPM", "DDS", "QOI", "PSD",
)
SUPPORTED = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".webp", ".bmp",
    ".dib", ".gif", ".tif", ".tiff", ".heic", ".heif", ".heics", ".heifs",
    ".hif", ".avif", ".avifs", ".jp2", ".j2k", ".j2c", ".jpc", ".jpf",
    ".jpx", ".ico", ".pcx", ".tga", ".icb", ".vda", ".vst", ".ppm",
    ".pgm", ".pbm", ".pnm", ".pfm", ".dds", ".qoi", ".psd",
}
IMAGE_FILE_FILTER = (
    "所有支持的图片 (" + " ".join("*" + ext for ext in sorted(SUPPORTED)) + ");;"
    "手机照片 (*.heic *.heif *.heics *.heifs *.hif *.jpg *.jpeg *.jfif);;"
    "所有文件 (*)"
)


@dataclass(frozen=True)
class Photo:
    uid: str
    source: str
    cached: str
    name: str
    width: int
    height: int
    size: int
    thumb: bytes
    angle: int = 0

    @property
    def display_size(self):
        return (self.height, self.width) if self.angle % 180 else (self.width, self.height)


@dataclass(frozen=True)
class ExportOptions:
    paper: str = "original"
    orientation: str = "auto"
    margin_mm: int = 10


@dataclass
class Geometry:
    angle: int = 0
    crop: Sides = Sides()
    scale: float = 1


def natural_key(value: str):
    return [int(s) if s.isdigit() else s.casefold() for s in re.split(r"(\d+)", value)]


def normalized_filename(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("请先填写 PDF 文件名。")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError('文件名不能包含这些字符：\\ / : * ? " < > |')
    if value.endswith((".", " ")):
        raise ValueError("文件名不能以句点或空格结尾。")
    stem = value[:-4] if value.lower().endswith(".pdf") else value
    if not stem or stem.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("这个文件名是 Windows 的保留名称，请换一个。")
    if len(value) > 180:
        raise ValueError("文件名太长，请缩短到 180 个字符以内。")
    return value if value.lower().endswith(".pdf") else value + ".pdf"


def import_photo(path: str, staging: str) -> tuple[Photo, bool]:
    source = Path(path)
    if not source.is_file():
        raise ValueError("找不到这张图片，它可能已被移动。")
    uid = uuid.uuid4().hex
    cached = Path(staging) / (uid + source.suffix.lower())
    shutil.copyfile(source, cached)
    original_cached = cached
    try:
        # Inspect the actual bytes: downloaded images can have a misleading
        # extension or no extension at all. Avoid plugins requiring external
        # programs (e.g. EPS/Ghostscript).
        # close() also releases Pillow's memory maps on Windows; __exit__ alone
        # only closes file pointers and can leave PGM/BMP caches locked.
        with closing(Image.open(cached, formats=IMAGE_FORMATS)) as opened:
            animated = opened.format != "PSD" and getattr(opened, "n_frames", 1) > 1
            # HEIF opens on its declared primary image, which need not be 0.
            # Preserve it rather than selecting an auxiliary/alternate photo.
            if opened.format not in {"HEIF", "PSD"}:
                opened.seek(0)
            image = ImageOps.exif_transpose(opened)
            image.load()
            width, height = image.size
            if min(width, height) < 1:
                raise ValueError("图片尺寸无效。")
            # img2pdf embeds JPEG/PNG without recompression. Other formats are
            # normalized to a lossless first-frame PNG, matching the preview.
            if opened.format not in {"JPEG", "PNG"} or animated:
                normalized = cached.with_name(uid + "-normalized.png")
                image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB").save(normalized, "PNG")
                cached = normalized
            thumb = image.convert("RGBA")
            thumb.thumbnail((700, 700), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            thumb.save(buffer, "PNG")
        if original_cached != cached:
            original_cached.unlink()
        return Photo(uid, str(source.resolve()), str(cached), source.name, width, height,
                     source.stat().st_size, buffer.getvalue()), animated
    except Exception:
        cached.unlink(missing_ok=True)
        original_cached.unlink(missing_ok=True)
        raise


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return "没有读写权限，或文件正被其他程序占用。请关闭已打开的 PDF，或换一个保存位置。"
    if isinstance(exc, Image.DecompressionBombError):
        return "图片尺寸过大，请缩小图片后重试。"
    if isinstance(exc, UnidentifiedImageError):
        return "无法识别图片内容，文件可能损坏或格式暂不支持。支持 HEIC/HEIF、AVIF、JPG、PNG 等图片。"
    if isinstance(exc, FileNotFoundError):
        return "找不到文件或保存位置，请重新选择。"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "磁盘空间不足，请清理空间或换一个磁盘。"
    return str(exc) or "处理失败，请检查图片后重试。"


def export_pdf(photos: list[Photo], target: str, options: ExportOptions,
               progress: Callable[[int, int], None] | None = None):
    if not photos:
        raise ValueError("请先添加至少一张图片。")
    if options.paper not in {"original", "a4", "letter"}:
        raise ValueError("未知的纸张尺寸。")
    if options.orientation not in {"auto", "portrait", "landscape"}:
        raise ValueError("未知的页面方向。")
    if not 0 <= options.margin_mm <= 40:
        raise ValueError("页边距应在 0 到 40 毫米之间。")
    destination = Path(target)
    if any(destination.resolve() == Path(p.source).resolve() for p in photos):
        raise ValueError("不能覆盖原始图片，请使用 .pdf 文件名。")
    if not destination.parent.is_dir():
        raise FileNotFoundError("保存文件夹不存在，请重新选择。")
    fd, temporary = tempfile.mkstemp(prefix=".paperdesk-", suffix=".pdf", dir=destination.parent)
    os.close(fd)
    try:
        with ExitStack() as stack:
            output = stack.enter_context(pikepdf.Pdf.new())
            originals = stack.enter_context(pikepdf.Pdf.new())
            # PDF Arranger's two-pass copy-then-transform rule avoids cross-
            # document resource errors (upstream pikepdf issue #271).
            for i, photo in enumerate(photos):
                wrapped = _img_to_pdf([photo.cached], None)
                wrapped.seek(0)
                source = stack.enter_context(pikepdf.Pdf.open(wrapped))
                if len(source.pages) != 1:
                    raise ValueError("图片包含多个画面，请重新添加以使用第一帧。")
                originals.pages.append(source.pages[0])
                if progress:
                    progress(i + 1, len(photos))
            for i, photo in enumerate(photos):
                originals.pages[i] = _apply_geom_transform(originals, originals.pages[i], Geometry(photo.angle))
                source_page = originals.pages[i]
                if options.paper == "original":
                    output.pages.append(source_page)
                else:
                    w, h = (595.2756, 841.8898) if options.paper == "a4" else (612, 792)
                    iw, ih = photo.display_size
                    landscape = options.orientation == "landscape" or (options.orientation == "auto" and iw > ih)
                    if landscape:
                        w, h = h, w
                    margin = options.margin_mm * 72 / 25.4
                    blank = output.add_blank_page(page_size=(w, h))
                    blank.add_overlay(source_page, pikepdf.Rectangle(margin, margin, w - margin, h - margin), shrink=True, expand=True)
            with output.open_metadata(set_pikepdf_as_editor=False) as meta:
                meta["dc:title"] = destination.stem
                from . import __version__
                meta["pdf:Producer"] = f"PaperDesk {__version__} / PDF Arranger derived processing"
            output.save(temporary, compress_streams=True)
        # Never leave a partially generated file at the chosen destination.
        with pikepdf.Pdf.open(temporary) as verified:
            if len(verified.pages) != len(photos):
                raise ValueError("导出页数校验失败，请重试。")
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
