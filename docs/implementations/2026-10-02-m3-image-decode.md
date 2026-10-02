# M3: decoding still images (step 6, first half; TST-037)

Date: 2026-10-02. Spec: API and Contracts section 38; owner decision on Pillow and NumPy (tech-stack, same date).

## What was built (`backend/infrastructure/media/image.py`)
- `read_header(data)`: the format (JPEG, PNG, BMP or WebP), its MIME type and its stored size, read lazily without decoding any pixel.
- `decode_image(data, max_pixels)`: the canonical form the ML worker takes: RGB, `uint8`, height by width by 3, contiguous, writable, with the EXIF orientation applied. `max_pixels` has no default; the size is checked from the header before anything is decoded.
- Errors of their own kinds: `UnsupportedImageError` (not one of the four, even if Pillow could read it, such as a GIF), `CorruptImageError` (one of the four but damaged or cut short), `ImageTooLargeError`.
- Dependency added: `pillow` (the owner's decision; an `opencv-python-headless` that I had added first was removed before anything was built on it).

## Behaviour pinned by the tests
Lossless round trips are exact; a JPEG is close; channel order is RGB; alpha is dropped, grey, bilevel and palette images become three channels, a CMYK JPEG becomes RGB, and a 16-bit grey PNG is **scaled** (Pillow's own conversion clips it to 255, seen in a probe: a maximum of 16793 became 255); all eight EXIF orientations are applied (JPEG), and 3, 6 and 8 also in PNG and WebP; the header keeps the stored size while the pixels are upright; an enormous image (a header-only PNG naming 60000 by 60000) is refused without decoding and without a decompression-bomb warning; truncated files, a valid header over garbage pixels and a zero size are corrupt; an unknown format is unsupported, and a damaged file of a known format is corrupt, not unsupported (Pillow reports both as "cannot identify", so the signature decides).

## Verification
50 tests, backend coverage 100%, 20 mutations caught. Redundant code deleted on the way: an explicit `load()` (the next call loads and raises in the same handler) and the unreachable 16-bit modes other than `I;16`.
