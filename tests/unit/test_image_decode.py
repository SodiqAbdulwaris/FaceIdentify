"""TST-037: decoding still images into the canonical RGB form (API and Contracts.md section 38)."""

import io
import struct
import zlib
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageFile

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


def smooth_picture() -> np.ndarray[Any, Any]:
    picture_ = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    picture_[..., 0] = np.linspace(0, 255, WIDTH, dtype=np.uint8)
    picture_[..., 1] = np.linspace(0, 255, HEIGHT, dtype=np.uint8)[:, None]
    picture_[..., 2] = 90
    return picture_


def test_a_cmyk_jpeg_becomes_the_same_colours_in_rgb() -> None:
    cmyk = Image.fromarray(smooth_picture()).convert("CMYK")
    expected = np.asarray(cmyk.convert("RGB"), dtype=int)

    decoded = decode_image(encode(cmyk, "JPEG", quality=95), max_pixels=LIMIT)

    assert decoded.pixels.shape == (HEIGHT, WIDTH, 3)
    assert decoded.pixels.dtype == np.uint8
    assert np.abs(decoded.pixels.astype(int) - expected).mean() < 6  # (right colours, lossy)


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


@pytest.mark.parametrize("orientation", range(1, 9))
@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_orientation_is_applied_in_the_other_formats_too(fmt: str, orientation: int) -> None:
    decoded = decode_image(with_orientation(fmt, orientation), max_pixels=LIMIT)

    assert np.array_equal(decoded.pixels, UPRIGHT[orientation](picture()))


@pytest.mark.parametrize("value", [0, 9, 65535])
def test_an_orientation_that_means_nothing_leaves_the_picture_as_stored(value: int) -> None:
    decoded = decode_image(with_orientation("JPEG", value), max_pixels=LIMIT)
    stored = decode_image(with_orientation("JPEG", 1), max_pixels=LIMIT)

    assert np.array_equal(decoded.pixels, stored.pixels)


def test_damaged_exif_does_not_make_a_picture_unusable() -> None:
    jpeg = encoded("JPEG")
    payload = b"Exif" + bytes(2) + b"II*" + bytes(1) + bytes([8, 0, 0, 0, 5, 0])  # cut short
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    damaged = jpeg[:2] + app1 + jpeg[2:]

    decoded = decode_image(damaged, max_pixels=LIMIT)  # (no warning escapes either)

    assert (decoded.width, decoded.height) == (WIDTH, HEIGHT)


def test_the_header_is_the_stored_size_and_the_pixels_are_the_upright_one() -> None:
    decoded = decode_image(with_orientation("JPEG", 6), max_pixels=LIMIT)

    assert (decoded.header.width, decoded.header.height) == (WIDTH, HEIGHT)
    assert (decoded.width, decoded.height) == (HEIGHT, WIDTH)


# --- animation -----------------------------------------------------------------------------------


def test_an_animated_webp_yields_its_first_frame() -> None:
    first, second = picture(), picture()[::-1]
    out = io.BytesIO()
    Image.fromarray(first).save(
        out, "WEBP", save_all=True, append_images=[Image.fromarray(second)], lossless=True
    )

    decoded = decode_image(out.getvalue(), max_pixels=LIMIT)

    assert np.array_equal(decoded.pixels, first)


def test_an_animated_png_yields_its_first_frame() -> None:
    first, second = picture(), picture()[::-1]
    out = io.BytesIO()
    Image.fromarray(first).save(out, "PNG", save_all=True, append_images=[Image.fromarray(second)])

    decoded = decode_image(out.getvalue(), max_pixels=LIMIT)

    assert np.array_equal(decoded.pixels, first)


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


@pytest.fixture
def arm_tripwire(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Call it to make any decoding of pixels fail the test. (Armed on demand, because making the
    images to test with decodes pixels too.) It sits on Pillow's real decode entry."""

    def arm() -> None:
        def never(self: Image.Image) -> None:
            raise AssertionError("a pixel was decoded")

        monkeypatch.setattr(ImageFile.ImageFile, "load", never)
        monkeypatch.setattr(Image.Image, "load", never)

    return arm


def test_the_tripwire_does_fire_when_a_real_decode_happens(
    arm_tripwire: Callable[[], None],
) -> None:
    data = encoded("PNG")
    arm_tripwire()

    with pytest.raises(AssertionError, match="a pixel was decoded"):
        decode_image(data, max_pixels=LIMIT)


def test_reading_a_header_decodes_nothing(arm_tripwire: Callable[[], None]) -> None:
    data = [encoded(fmt) for fmt in ("PNG", "JPEG", "BMP", "WEBP")]
    arm_tripwire()

    assert [read_header(d).format for d in data] == ["PNG", "JPEG", "BMP", "WEBP"]


def test_an_image_over_the_limit_is_refused_before_anything_is_decoded(
    arm_tripwire: Callable[[], None],
) -> None:
    data = encoded("PNG")
    arm_tripwire()

    with pytest.raises(ImageTooLargeError, match="more than the 2399 allowed"):
        decode_image(data, max_pixels=WIDTH * HEIGHT - 1)


def test_an_enormous_image_is_refused_by_pillows_ceiling_without_decoding(
    arm_tripwire: Callable[[], None],
) -> None:
    arm_tripwire()
    data = png_header_claiming(60_000, 60_000)  # 3.6 billion pixels

    with pytest.raises(ImageTooLargeError, match="ever open"):
        read_header(data)
    with pytest.raises(ImageTooLargeError, match="ever open"):
        decode_image(data, max_pixels=10**12)  # (even a caller that allows everything)


def test_an_image_between_pillows_limit_and_twice_it_is_left_to_the_callers_limit(
    arm_tripwire: Callable[[], None],
) -> None:
    arm_tripwire()
    data = png_header_claiming(12_000, 9_000)  # 108 million pixels: Pillow only warns here

    assert read_header(data).width == 12_000  # (and no warning escapes: warnings are errors here)
    with pytest.raises(ImageTooLargeError, match="more than the 1000000 allowed"):
        decode_image(data, max_pixels=LIMIT)


def test_pillows_global_decompression_guard_is_left_as_it_was() -> None:
    assert Image.MAX_IMAGE_PIXELS is not None
    assert Image.MAX_IMAGE_PIXELS < 10**9


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


def test_something_that_only_begins_like_a_bmp_is_corrupt_not_unsupported() -> None:
    with pytest.raises(CorruptImageError) as raised:
        read_header(b"BM" + b"not really a bitmap" * 4)

    assert str(raised.value) == "the image header cannot be read (OSError)"  # (not Pillow's words)


def test_other_riff_files_are_unsupported_not_corrupt() -> None:
    with pytest.raises(UnsupportedImageError):
        read_header(b"RIFF" + bytes(4) + b"WAVEfmt " + bytes(20))


def test_an_error_message_does_not_pass_on_the_decoders_own_words() -> None:
    data = bytearray(encoded("PNG"))
    start = data.index(b"IDAT") + 4
    data[start : start + 40] = bytes(40)

    with pytest.raises(CorruptImageError) as raised:
        decode_image(bytes(data), max_pixels=LIMIT)

    assert str(raised.value) == "the PNG cannot be decoded (OSError)"


def test_a_png_naming_a_zero_size_is_corrupt() -> None:
    with pytest.raises(CorruptImageError):
        read_header(png_header_claiming(0, 10))
