# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2008-2017 Konstantinos Poulios, 2018-2019 Jerome Robert
# Adapted for PaperDesk (2026). Original PDF Arranger 1.14.0 sources:
# pdfarranger/core.py and pdfarranger/exporter.py, commit 29f306bb6932e28d3001b098f6dad9824ab74100.
# These processing functions are retained; GTK/Poppler UI imports are removed.
import os
import tempfile
from typing import NamedTuple
import img2pdf
import pikepdf
from packaging import version

IMG2PDF_VERSION = img2pdf.__version__

class PDFDocError(ValueError):
    pass

class Sides(NamedTuple):
    left: float = 0
    right: float = 0
    top: float = 0
    bottom: float = 0

def _normalize_rectangle(rect):
    """
    PDF Specification 1.7, 7.9.5, although rectangles are conventionally
    specified by their lower-left and upper-right corners, it is acceptable to
    specify any two diagonally opposite corners. Applications that process PDF
    should be prepared to normalize such rectangles in situations where
    specific corners are required.
    """
    rect = [float(x) for x in rect]
    if rect[0] > rect[2]:
        rect[0], rect[2] = rect[2], rect[0]
    if rect[1] > rect[3]:
        rect[1], rect[3] = rect[3], rect[1]
    return rect

def _intersect_rectangle(rect1, rect2):
    return [
        max(rect1[0], rect2[0]),
        max(rect1[1], rect2[1]),
        min(rect1[2], rect2[2]),
        min(rect1[3], rect2[3]),
    ]

def _mediabox(page, crop=Sides()):
    """ Return the media box for a given page. """
    # PDF files which do not have mediabox default to Portrait Letter / ANSI A
    cmb = page.MediaBox if "/MediaBox" in page else [0, 0, 612, 792]
    cmb = _normalize_rectangle(cmb)
    if "/CropBox" in page:
        # PDF specification §14.11.2.1, "If they do, they are effectively
        # reduced to their intersection with the media box"
        cmb = _intersect_rectangle(cmb, _normalize_rectangle(page.CropBox))

    if crop == Sides():
        return cmb
    angle = page.Rotate if '/Rotate' in page else 0
    rotate_times = int(round(((angle) % 360) / 90) % 4)
    crop_init = crop
    if rotate_times != 0:
        perm = [0, 2, 1, 3]
        for _ in range(rotate_times):
            perm.append(perm.pop(0))
        perm.insert(1, perm.pop(2))
        crop = Sides(*(crop_init[perm[side]] for side in range(4)))
    x1, y1, x2, y2 = [float(x) for x in cmb]
    x1_new = x1 + (x2 - x1) * crop.left
    x2_new = x2 - (x2 - x1) * crop.right
    y1_new = y1 + (y2 - y1) * crop.bottom
    y2_new = y2 - (y2 - y1) * crop.top
    return [x1_new, y1_new, x2_new, y2_new]

def _scale(doc, page, factor):
    """ Scale a page """
    if factor == 1:
        return page
    rotate = 0
    if "/Rotate" in page:
        # We'll set the rotate attribute on the resulting page so we must
        # unset it on the input page before
        rotate = page.Rotate
        page.Rotate = 0
    page_id = len(doc.pages)
    newmediabox = [factor * float(x) for x in page.MediaBox]
    content = "q {} 0 0 {} 0 0 cm /p{} Do Q".format(factor, factor, page_id)
    xobject = pikepdf.Page(page).as_form_xobject()
    new_page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=newmediabox,
        Contents=doc.make_stream(content.encode()),
        Resources={'/XObject': {'/p{}'.format(page_id): xobject}},
        Rotate=rotate,
    )
    # This was needed for pikepdf <= 2.6.0. See https://github.com/pikepdf/pikepdf/issues/174
    # It's also needed for pikepdf 8.8 but not for pikepdf 6.0.1
    new_page = doc.make_indirect(new_page)
    return new_page

def _update_angle(model_page, source_page, output_page):
    angle = model_page.angle
    angle0 = source_page.Rotate if '/Rotate' in source_page else 0
    if angle != 0:
        new_angle = angle + angle0
        if new_angle >= 360:
            new_angle -= 360
        output_page.Rotate = new_angle

def _apply_geom_transform(pdf_output, new_page, row):
    _update_angle(row, new_page, new_page)
    new_page.MediaBox = _mediabox(new_page, row.crop)
    # add_overlay() & add_underlay() will use TrimBox or CropBox if they exist
    if '/TrimBox' in new_page:
        del new_page.TrimBox
    if '/CropBox' in new_page:
        del new_page.CropBox
    return pikepdf.Page(_scale(pdf_output, new_page, row.scale))

def _img_to_pdf(images, tmp_dir, page_size=None):
    """Wrap img2pdf.convert to handle some corner cases"""
    if version.parse(IMG2PDF_VERSION) < version.Version('0.4.2'):
        for num, image in enumerate(images):
            if isinstance(image, img2pdf.BytesIO):
                # Images from ImageExporter does not have transparency
                continue
            if isinstance(image, str):
                img = img2pdf.Image.open(image)
            else:
                img = img2pdf.Image.open(img2pdf.BytesIO(image))
            if (img.mode == "LA") or (img.mode != "RGBA" and "transparency" in img.info):
                # TODO: Find a way to keep image in P or L format and remove transparency.
                # This will work but converting from 1, L, P to RGB is not optimal.
                img = img.convert("RGBA")
            if img.mode == "RGBA":
                # Remove transparency as old img2pdf doesn't support it
                bg = img2pdf.Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                imgio = img2pdf.BytesIO()
                bg.save(imgio, "PNG")
                imgio.seek(0)
                images[num] = imgio
    try:
        # Try to handle invalid EXIF rotation
        rot = img2pdf.Rotation.ifvalid
    except AttributeError:
        # img2pdf is too old so we can't support invalid EXIF rotation
        rot = None
    kwargs = dict(rotation=rot)
    if page_size is not None:
        kwargs['layout_fun'] = img2pdf.get_layout_fun(page_size)
    try:
        pdf = img2pdf.convert(images, **kwargs)
    except ValueError as e:
        # Too small or large image
        raise PDFDocError(e)
    if tmp_dir is None:
        pdf_file = img2pdf.BytesIO()
        pdf_file.write(pdf)
    else:
        fd, pdf_file = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
        os.close(fd)
        with open(pdf_file, "wb") as f:
            f.write(pdf)
    return pdf_file
