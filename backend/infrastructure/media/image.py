"""Decoding still images (API and Contracts.md section 38; Architecture section 19).

An image is accepted only if it is a JPEG, a PNG, a BMP or a WebP, and only after its header has
been read and its size checked against a limit the caller chooses, so an image that would be huge
once decoded is refused before any pixel is allocated. What comes out is the canonical form the ML
worker takes as input: RGB, `uint8`, height by width by channel, contiguous, with the camera's
orientation (EXIF) already applied. Pillow decodes; NumPy holds the result. Model-specific
preprocessing (size, ordering, normalisation) is not here: it belongs to a versioned contract of
the model that needs it.

Everything that is not plain 8-bit colour is converted to three 8-bit channels: alpha is dropped,
palettes and greys are expanded, and 16-bit grey is scaled (Pillow's own conversion would clip it).
"""

import io
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

# The size check below happens before any pixel is decoded and uses the caller's limit, so
# Pillow's own decompression-bomb guard (a fixed global limit that warns) is not wanted.
Image.MAX_IMAGE_PIXELS = None

FORMATS = ("JPEG", "PNG", "BMP", "WEBP")
MIME_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "WEBP": "image/webp"}
_SIXTEEN_BIT_GREY = "I;16"  # (what Pillow calls a 16-bit grey PNG, the only such input)
# How each of the four formats begins (a WebP is a RIFF container naming WEBP at byte 8).
_SIGNATURES = re.compile(rb"\x89PNG\r\n\x1a\n|\xff\xd8|BM|RIFF....WEBP", re.DOTALL)


class ImageError(ValueError):
    """An image that cannot be used."""


class UnsupportedImageError(ImageError):
    """Not a JPEG, PNG, BMP or WebP."""


class CorruptImageError(ImageError):
    """It says it is one of the four, but it cannot be read as one."""


class ImageTooLargeError(ImageError):
    """More pixels than the caller allows."""


@dataclass(frozen=True, slots=True)
class ImageHeader:
    format: str  # JPEG, PNG, BMP or WEBP
    mime_type: str
    width: int  # as stored: the camera's orientation is not applied to these
    height: int


@dataclass(frozen=True, slots=True)
class DecodedImage:
    pixels: np.ndarray[Any, Any]  # RGB, uint8, height x width x 3, contiguous
    header: ImageHeader

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])


def _open(data: bytes) -> Image.Image:
    """Open lazily: this reads the header and nothing else."""
    try:
        return Image.open(io.BytesIO(data), formats=list(FORMATS))
    except UnidentifiedImageError:
        # Pillow says this both for a format it does not know and for one of the four whose header
        # is cut short or damaged, so the signature decides which it was.
        if _SIGNATURES.match(data):
            raise CorruptImageError("the image header is cut short or damaged") from None
        raise UnsupportedImageError("not a JPEG, PNG, BMP or WebP image") from None
    except (OSError, ValueError, SyntaxError) as error:
        raise CorruptImageError(f"the image header cannot be read ({error})") from error


def _header_of(image: Image.Image) -> ImageHeader:
    assert image.format is not None  # (opened from bytes, so Pillow identified a format)
    width, height = image.size
    return ImageHeader(image.format, MIME_TYPES[image.format], width, height)


def read_header(data: bytes) -> ImageHeader:
    """The format and stored size of an image, without decoding it."""
    return _header_of(_open(data))


def _to_rgb(image: Image.Image) -> np.ndarray[Any, Any]:
    if image.mode == _SIXTEEN_BIT_GREY:
        grey = np.asarray(image, dtype=np.uint32)
        scaled = ((grey * 255 + 32767) // 65535).astype(np.uint8)  # (rounded, not clipped)
        return np.stack([scaled] * 3, axis=-1)
    # A copy, so the array owns its memory, is writable and does not depend on Pillow's buffer.
    return np.array(image.convert("RGB"), dtype=np.uint8, order="C")


def decode_image(data: bytes, *, max_pixels: int) -> DecodedImage:
    """Decode an image to RGB. `max_pixels` has no default: it bounds the memory one image may
    take, which is the caller's measured choice. The size is checked from the header, before any
    pixel exists."""
    image = _open(data)
    header = _header_of(image)
    if header.width * header.height > max_pixels:
        raise ImageTooLargeError(
            f"{header.width} by {header.height} pixels is more than the {max_pixels} allowed"
        )
    try:
        upright = ImageOps.exif_transpose(image)
        return DecodedImage(_to_rgb(upright), header)
    except (OSError, ValueError, SyntaxError) as error:
        raise CorruptImageError(f"the {header.format} cannot be decoded ({error})") from error
