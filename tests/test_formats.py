"""Decode real image bytes and verify the resulting PDF, including HEIF."""
from io import BytesIO
from pathlib import Path
import shutil
import struct

import pikepdf
import pytest
from PIL import Image, ImageOps

from paperdesk.engine import IMAGE_FILE_FILTER, ExportOptions, import_photo, export_pdf, friendly_error

FIXTURES = Path(__file__).parent / "fixtures"


def assert_pdf_matches(photo, target, expected):
    export_pdf([photo], str(target), ExportOptions())
    with pikepdf.Pdf.open(target) as pdf:
        assert len(pdf.pages) == 1
        embedded = pikepdf.PdfImage(next(iter(pdf.pages[0].Resources.XObject.values()))).as_pil_image().convert("RGB")
        assert embedded.size == expected.size
        assert embedded.getpixel((40, 40)) == expected.convert("RGB").getpixel((40, 40))
    with Image.open(BytesIO(photo.thumb)) as preview:
        assert preview.size == expected.size
        assert preview.convert("RGB").getpixel((40, 40)) == expected.convert("RGB").getpixel((40, 40))


@pytest.mark.parametrize("fixture,extension,size,multi", [
    ("phone.heic", ".HEIC", (96, 64), False),
    ("phone.heic", ".heif", (96, 64), False),
    ("phone.heic", ".hif", (96, 64), False),
    ("rotated.heic", ".heic", (64, 96), False),
    ("ten-bit.heif", ".HEIF", (96, 64), False),
    ("primary.heic", ".heic", (96, 64), True),
])
def test_heif_phone_images(tmp_path, fixture, extension, size, multi):
    source = tmp_path / ("IMG_3500" + extension)
    shutil.copyfile(FIXTURES / fixture, source)
    original = source.read_bytes()
    with Image.open(source) as opened:
        # Do not seek(0): the HEIF primary image can be the second frame.
        expected = ImageOps.exif_transpose(opened)
        expected.load()
    photo, animated = import_photo(str(source), str(tmp_path))
    assert (photo.width, photo.height) == size
    assert animated == multi
    assert source.read_bytes() == original
    assert_pdf_matches(photo, tmp_path / "手机照片.pdf", expected)
    if fixture == "primary.heic":
        r, g, b = expected.getpixel((40, 40))
        assert b > 240 and r < 10 and g < 10


@pytest.mark.parametrize("extension,format,mode", [
    ("jpg", "JPEG", "RGB"), ("jfif", "JPEG", "RGB"),
    ("png", "PNG", "RGB"), ("apng", "PNG", "RGB"),
    ("webp", "WEBP", "RGB"), ("bmp", "BMP", "RGB"),
    ("dib", "DIB", "RGB"), ("gif", "GIF", "RGB"),
    ("tif", "TIFF", "RGB"), ("avif", "AVIF", "RGB"),
    ("jp2", "JPEG2000", "RGB"), ("j2k", "JPEG2000", "RGB"),
    ("ico", "ICO", "RGB"), ("pcx", "PCX", "RGB"),
    ("tga", "TGA", "RGB"), ("ppm", "PPM", "RGB"),
    ("pgm", "PPM", "L"), ("pbm", "PPM", "1"),
    ("pnm", "PPM", "RGB"), ("dds", "DDS", "RGB"),
    ("qoi", "QOI", "RGB"),
])
def test_raster_formats_to_pdf(tmp_path, extension, format, mode):
    source = tmp_path / ("其他图片." + extension)
    Image.new("RGB", (96, 96), (180, 90, 40)).convert(mode).save(source, format=format)
    with Image.open(source) as opened:
        expected = opened.copy()
    photo, _ = import_photo(str(source), str(tmp_path))
    assert_pdf_matches(photo, tmp_path / "结果.pdf", expected)


@pytest.mark.parametrize("extension", ["img", "", "heic", "jpg"])
def test_content_detection_with_incorrect_or_missing_extension(tmp_path, extension):
    source = tmp_path / ("下载图片" + ("." + extension if extension else ""))
    expected = Image.new("RGB", (96, 64), (20, 40, 60))
    expected.save(source, format="PNG")
    photo, _ = import_photo(str(source), str(tmp_path))
    assert_pdf_matches(photo, tmp_path / "内容识别.pdf", expected)


def test_flattened_psd(tmp_path):
    source = tmp_path / "设计图.psd"
    # Minimal PSD: RGB, no resource/layer blocks, uncompressed planar pixels.
    source.write_bytes(struct.pack(">4sH6sHIIHH", b"8BPS", 1, bytes(6), 3, 64, 96, 8, 3)
                       + bytes(12) + bytes(2)
                       + bytes([180]) * (96 * 64) + bytes([90]) * (96 * 64) + bytes([40]) * (96 * 64))
    photo, _ = import_photo(str(source), str(tmp_path))
    assert_pdf_matches(photo, tmp_path / "合成图.pdf", Image.new("RGB", (96, 64), (180, 90, 40)))


def test_bad_heic_has_chinese_error_and_leaves_no_cache(tmp_path):
    source = tmp_path / "损坏.heic"
    source.write_bytes(b"not an image")
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(Exception) as error:
        import_photo(str(source), str(staging))
    assert "无法识别图片内容" in friendly_error(error.value)
    assert list(staging.iterdir()) == []
    assert source.read_bytes() == b"not an image"


def test_dialog_exposes_phone_formats_and_all_files():
    assert "*.heic" in IMAGE_FILE_FILTER
    assert "*.heif" in IMAGE_FILE_FILTER
    assert "*.avif" in IMAGE_FILE_FILTER
    assert "*.jfif" in IMAGE_FILE_FILTER
    assert "所有文件 (*)" in IMAGE_FILE_FILTER
