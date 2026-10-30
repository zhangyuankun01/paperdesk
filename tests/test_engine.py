from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

from paperdesk.engine import import_photo, export_pdf, ExportOptions, normalized_filename, natural_key


def make_photo(tmp_path, name="中文图片.png", mode="RGB"):
    path = tmp_path / name
    Image.new(mode, (120, 80), (180, 90, 40, 120) if mode == "RGBA" else (180, 90, 40)).save(path)
    staging = tmp_path / "暂存"
    staging.mkdir(exist_ok=True)
    return path, import_photo(str(path), str(staging))[0]


def test_lossless_snapshot_and_unicode_output(tmp_path):
    source, photo = make_photo(tmp_path)
    source.unlink()
    result = tmp_path / "合并输出.pdf"
    export_pdf([photo, replace(photo, uid="duplicate", angle=90)], str(result), ExportOptions())
    with pikepdf.Pdf.open(result) as doc:
        assert len(doc.pages) == 2
        assert int(doc.pages[1].Rotate) == 90
        image = pikepdf.PdfImage(next(iter(doc.pages[0].Resources.XObject.values()))).as_pil_image().convert("RGB")
        assert image.size == (120, 80)
        assert image.getpixel((50, 50)) == (180, 90, 40)


def test_exif_thumbnail_and_pdf_agree(tmp_path):
    path = tmp_path / "手机照片.jpg"
    image = Image.new("RGB", (120, 80), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    photo, _ = import_photo(str(path), str(tmp_path))
    assert (photo.width, photo.height) == (80, 120)
    output = tmp_path / "方向.pdf"
    export_pdf([photo], str(output), ExportOptions())
    with pikepdf.Pdf.open(output) as doc:
        assert int(doc.pages[0].Rotate) % 360 == 90


def test_alpha_preserved_and_gif_first_frame(tmp_path):
    _, photo = make_photo(tmp_path, mode="RGBA")
    output = tmp_path / "透明.pdf"
    export_pdf([photo], str(output), ExportOptions())
    with pikepdf.Pdf.open(output) as doc:
        xobject = next(iter(doc.pages[0].Resources.XObject.values()))
        assert "/SMask" in xobject
    path = tmp_path / "动画.gif"
    first, second = Image.new("RGB", (20, 20), "red"), Image.new("RGB", (20, 20), "blue")
    first.save(path, save_all=True, append_images=[second], duration=100, loop=0)
    gif, animated = import_photo(str(path), str(tmp_path))
    assert animated
    export_pdf([gif], str(tmp_path / "第一帧.pdf"), ExportOptions())
    with pikepdf.Pdf.open(tmp_path / "第一帧.pdf") as doc:
        assert len(doc.pages) == 1
        image = pikepdf.PdfImage(next(iter(doc.pages[0].Resources.XObject.values()))).as_pil_image().convert("RGB")
        assert image.getpixel((10, 10)) == (255, 0, 0)


def test_a4_and_rotation_fit(tmp_path):
    _, photo = make_photo(tmp_path)
    output = tmp_path / "打印.pdf"
    export_pdf([photo, replace(photo, angle=90)], str(output), ExportOptions("a4", "auto", 10))
    with pikepdf.Pdf.open(output) as doc:
        first, second = doc.pages[0].MediaBox, doc.pages[1].MediaBox
        assert float(first[2]) > float(first[3])
        assert float(second[2]) < float(second[3])


def test_failed_export_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    from paperdesk import engine
    _, photo = make_photo(tmp_path)
    target = tmp_path / "已有文件.pdf"
    target.write_bytes(b"existing-content")
    def fail(*args):
        raise ValueError("simulated conversion failure")
    monkeypatch.setattr(engine, "_img_to_pdf", fail)
    with pytest.raises(ValueError):
        export_pdf([photo], str(target), ExportOptions())
    assert target.read_bytes() == b"existing-content"
    assert not list(tmp_path.glob(".paperdesk-*.pdf"))


@pytest.mark.parametrize("name", ["", "a/b.pdf", "NUL", "CON.pdf", ".pdf", "file."])
def test_bad_names(name):
    with pytest.raises(ValueError):
        normalized_filename(name)


def test_filename_and_natural_sort():
    assert normalized_filename("我的材料") == "我的材料.pdf"
    assert normalized_filename("已有.PDF") == "已有.PDF"
    assert sorted(["10.png", "2.png", "1.png"], key=natural_key) == ["1.png", "2.png", "10.png"]
