"""TST-037: decoding still images into the canonical RGB form (API and Contracts.md section 38)."""

import io
import struct
import zlib
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from PIL import Image

from backend.infrastructure.media.image import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedImageError,
    decode_image,
    read_header,
)

LIMIT = 10**6
WIDTH, HEIGHT = 60, 40
ENCODE_OPTIONS: dict[str, dict[str, Any]] = {"WEBP": {"lossless": True}, "JPEG": {"quality": 95}}


def picture(width: int = WIDTH, height: int = HEIGHT) -> np.ndarray[Any, Any]:
    """An image with no symmetry at all, so a wrong flip or turn cannot go unnoticed."""
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, (height, width, 3), dtype=np.uint8)


def encode(image: Image.Image, fmt: str, **options: Any) -> bytes:
    out = io.BytesIO()
    image.save(out, fmt, **options)
    return out.getvalue()


def encoded(fmt: str, array: np.ndarray[Any, Any] | None = None) -> bytes:
    image = Image.fromarray(picture() if array is None else array)
    options = ENCODE_OPTIONS.get(fmt, {})
    return encode(image, fmt, **options)


# --- every supported format --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "mime"),
    [("PNG", "image/png"), ("BMP", "image/bmp"), ("WEBP", "image/webp")],
)
def test_each_lossless_format_is_read_and_decoded_to_rgb(fmt: str, mime: str) -> None:
    data = encoded(fmt)

    header = read_header(data)
    decoded = decode_image(data, max_pixels=LIMIT)

    assert (header.format, header.mime_type) == (fmt, mime)
    assert (header.width, header.height) == (WIDTH, HEIGHT)
    assert decoded.header == header
    assert (decoded.width, decoded.height) == (WIDTH, HEIGHT)
    pixels = decoded.pixels
    assert pixels.shape == (HEIGHT, WIDTH, 3)
    assert pixels.dtype == np.uint8
    assert pixels.flags["C_CONTIGUOUS"]
    assert np.array_equal(pixels, picture())


def test_a_jpeg_is_identified_as_one() -> None:
    header = read_header(encoded("JPEG"))

    assert (header.format, header.mime_type) == ("JPEG", "image/jpeg")
    assert (header.width, header.height) == (WIDTH, HEIGHT)


def test_a_jpeg_is_close_to_the_picture_it_was_made_from() -> None:
    smooth = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    smooth[..., 0] = np.linspace(0, 255, WIDTH, dtype=np.uint8)
    smooth[..., 1] = np.linspace(0, 255, HEIGHT, dtype=np.uint8)[:, None]

    decoded = decode_image(encoded("JPEG", smooth), max_pixels=LIMIT)

    assert np.abs(decoded.pixels.astype(int) - smooth.astype(int)).mean() < 6  # (lossy)


def test_channels_are_in_rgb_order() -> None:
    red = np.zeros((4, 4, 3), np.uint8)
    red[..., 0] = 255

    decoded = decode_image(encoded("PNG", red), max_pixels=LIMIT)

    assert decoded.pixels[0, 0].tolist() == [255, 0, 0]


def test_the_result_can_be_written_to() -> None:
    decoded = decode_image(encoded("PNG"), max_pixels=LIMIT)

    decoded.pixels[0, 0, 0] = 1  # (a read-only result would raise)

    assert decoded.pixels[0, 0, 0] == 1


# --- anything that is not plain 8-bit colour ---------------------------------------------------


def test_alpha_is_dropped_and_the_colour_kept() -> None:
    rgba = np.dstack([picture(), np.full((HEIGHT, WIDTH), 255, np.uint8)])

    decoded = decode_image(encode(Image.fromarray(rgba, "RGBA"), "PNG"), max_pixels=LIMIT)

    assert decoded.pixels.shape == (HEIGHT, WIDTH, 3)
    assert np.array_equal(decoded.pixels, picture())


@pytest.mark.parametrize("mode", ["L", "LA", "1", "P"])
def test_grey_bilevel_and_palette_images_become_three_channels(mode: str) -> None:
    source = Image.fromarray(picture()).convert(mode)
    expected = np.asarray(source.convert("RGB"))

    decoded = decode_image(encode(source, "PNG"), max_pixels=LIMIT)

    assert np.array_equal(decoded.pixels, expected)


def test_sixteen_bit_grey_is_scaled_not_clipped() -> None:
    grey = np.array([[0, 32768, 65535, 257]], dtype=np.uint16)

    decoded = decode_image(encode(Image.fromarray(grey), "PNG"), max_pixels=LIMIT)

    assert decoded.pixels[0, :, 0].tolist() == [0, 128, 255, 1]
    assert np.array_equal(decoded.pixels[..., 0], decoded.pixels[..., 1])
    assert np.array_equal(decoded.pixels[..., 0], decoded.pixels[..., 2])


def test_a_cmyk_jpeg_becomes_rgb() -> None:
    cmyk = Image.fromarray(picture()).convert("CMYK")

    decoded = decode_image(encode(cmyk, "JPEG"), max_pixels=LIMIT)

    assert decoded.pixels.shape == (HEIGHT, WIDTH, 3)
    assert decoded.pixels.dtype == np.uint8


# --- the camera's orientation ------------------------------------------------------------------

# EXIF orientation -> how the stored picture must be turned to be upright.
UPRIGHT: dict[int, Callable[[np.ndarray[Any, Any]], np.ndarray[Any, Any]]] = {
    1: lambda a: a,
    2: lambda a: a[:, ::-1],
    3: lambda a: a[::-1, ::-1],
    4: lambda a: a[::-1, :],
    5: lambda a: a.transpose(1, 0, 2),
    6: lambda a: np.rot90(a, -1),
    7: lambda a: np.rot90(a, 1)[:, ::-1],
    8: lambda a: np.rot90(a, 1),
}


def with_orientation(fmt: str, orientation: int) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = orientation
    options = ENCODE_OPTIONS.get(fmt, {})
    return encode(Image.fromarray(picture()), fmt, exif=exif, **options)


@pytest.mark.parametrize("orientation", range(1, 9))
def test_every_exif_orientation_is_applied(orientation: int) -> None:
    upright = decode_image(with_orientation("JPEG", orientation), max_pixels=LIMIT)
    stored = decode_image(with_orientation("JPEG", 1), max_pixels=LIMIT)

    assert np.array_equal(upright.pixels, UPRIGHT[orientation](stored.pixels))


@pytest.mark.parametrize("orientation", [3, 6, 8])
@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_orientation_is_applied_in_the_other_formats_too(fmt: str, orientation: int) -> None:
    decoded = decode_image(with_orientation(fmt, orientation), max_pixels=LIMIT)

    assert np.array_equal(decoded.pixels, UPRIGHT[orientation](picture()))


def test_the_header_is_the_stored_size_and_the_pixels_are_the_upright_one() -> None:
    decoded = decode_image(with_orientation("JPEG", 6), max_pixels=LIMIT)

    assert (decoded.header.width, decoded.header.height) == (WIDTH, HEIGHT)
    assert (decoded.width, decoded.height) == (HEIGHT, WIDTH)


# --- the size limit ----------------------------------------------------------------------------


def test_exactly_the_limit_is_allowed_and_one_pixel_more_is_not() -> None:
    data = encoded("PNG")

    assert decode_image(data, max_pixels=WIDTH * HEIGHT).width == WIDTH
    with pytest.raises(ImageTooLargeError, match="more than the 2399 allowed"):
        decode_image(data, max_pixels=WIDTH * HEIGHT - 1)


def png_header_claiming(width: int, height: int) -> bytes:
    """A PNG that is only a header, with a valid checksum, naming an enormous picture."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", b"") + chunk(b"IEND", b"")


def test_an_enormous_image_is_refused_from_its_header_without_decoding_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(self: Image.Image) -> None:
        raise AssertionError("a pixel was decoded")

    monkeypatch.setattr(Image.Image, "load", never)
    data = png_header_claiming(60_000, 60_000)

    assert read_header(data).width == 60_000  # (no decompression-bomb warning either)
    with pytest.raises(ImageTooLargeError):
        decode_image(data, max_pixels=LIMIT)


def test_reading_a_header_decodes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    data = encoded("JPEG")  # (made before the patch: encoding loads pixels too)

    def never(self: Image.Image) -> None:
        raise AssertionError("a pixel was decoded")

    monkeypatch.setattr(Image.Image, "load", never)

    assert read_header(data).format == "JPEG"


# --- what is not an image we take ----------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"hello",
        b"GIF89a" + bytes(40),
        b"II*\x00" + bytes(40),  # TIFF
        b"%PDF-1.7\n" + bytes(40),
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"\x00\x00\x00\x18ftypheic" + bytes(40),  # HEIC
    ],
    ids=["empty", "text", "gif", "tiff", "pdf", "svg", "heic"],
)
def test_anything_that_is_not_one_of_the_four_formats_is_unsupported(data: bytes) -> None:
    with pytest.raises(UnsupportedImageError):
        read_header(data)
    with pytest.raises(UnsupportedImageError):
        decode_image(data, max_pixels=LIMIT)


def test_a_gif_is_refused_even_though_pillow_can_read_gifs() -> None:
    gif = encode(Image.fromarray(picture()).convert("P"), "GIF")

    with pytest.raises(UnsupportedImageError):
        decode_image(gif, max_pixels=LIMIT)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "BMP", "WEBP"])
def test_a_file_cut_short_is_corrupt(fmt: str) -> None:
    data = encoded(fmt)

    with pytest.raises(CorruptImageError):
        decode_image(data[: len(data) // 2], max_pixels=LIMIT)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "BMP", "WEBP"])
def test_a_file_with_only_its_signature_is_corrupt(fmt: str) -> None:
    signature = {"PNG": 8, "JPEG": 2, "BMP": 2, "WEBP": 12}[fmt]

    with pytest.raises(CorruptImageError):
        read_header(encoded(fmt)[:signature])


def test_a_valid_header_over_garbage_pixels_is_corrupt() -> None:
    data = bytearray(encoded("PNG"))
    start = data.index(b"IDAT") + 4
    data[start : start + 40] = bytes(40)

    assert read_header(bytes(data)).format == "PNG"  # the header is fine...
    with pytest.raises(CorruptImageError):
        decode_image(bytes(data), max_pixels=LIMIT)  # ...the pixels are not


def test_a_png_naming_a_zero_size_is_corrupt() -> None:
    with pytest.raises(CorruptImageError):
        read_header(png_header_claiming(0, 10))
