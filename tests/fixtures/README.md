# HEIF regression fixtures

These synthetic images were generated for PaperDesk using Pillow 13.0.0 and
pillow-heif 1.8.1, with no photographs or personal metadata.

- `phone.heic`: 96 x 64 RGB, brown background and blue top-left square.
- `rotated.heic`: the same pattern with EXIF orientation 6; decodes to 64 x 96.
- `primary.heic`: two images, red then blue; the blue second image is primary.
- `ten-bit.heif`: 96 x 64, 10-bit HEVC image, generated from RGB;16 pixels.

These fixtures are part of this project under GPL-3.0-or-later. The test runner
only needs the decoder `pi-heif`; the encoder is not a runtime dependency.
