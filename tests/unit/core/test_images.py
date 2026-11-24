"""What a hive photo looks like once processed (#3)."""

import io

import pytest
from PIL import Image

from meshbee_core.errors import InvalidData
from meshbee_core.images import process_photo
from meshbee_core.limits import FOTO_MAX_LATO, FOTO_MAX_PIXELS
from tests.conftest import image_bytes

# EXIF tags, by number.
ORIENTATION = 0x0112
GPS_INFO = 0x8825


def decoded(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_every_accepted_format_is_stored_as_webp(fmt):
    """Clients get one format back, whatever the phone sent."""
    result = process_photo(image_bytes(fmt=fmt))

    assert result.content_type == "image/webp"
    assert decoded(result.data).format == "WEBP"
    assert (result.width, result.height) == (64, 48)


def test_a_large_photo_is_scaled_down_keeping_its_proportions():
    """A 12 MP phone photo would be megabytes over a mobile connection."""
    result = process_photo(image_bytes(size=(4000, 3000)))

    assert (result.width, result.height) == (FOTO_MAX_LATO, 1200)
    assert decoded(result.data).size == (FOTO_MAX_LATO, 1200)


def test_the_gps_position_a_phone_records_is_not_kept():
    """
    A hive photo would otherwise publish where the apiary is to everyone the
    hive is shared with, and to anyone the file is passed on to.
    """
    exif = Image.Exif()
    exif[GPS_INFO] = {1: "N", 2: (43.0, 53.0, 0.0)}
    upload = image_bytes(exif=exif.tobytes())
    assert decoded(upload).getexif().get_ifd(GPS_INFO)

    result = decoded(process_photo(upload).data)

    assert not result.getexif()
    assert "exif" not in result.info


def test_a_photo_taken_sideways_is_stored_upright():
    """
    Phones save the sensor's orientation and a tag saying how to turn it. With
    the tag stripped, the photo must already be turned, or it shows sideways.
    """
    exif = Image.Exif()
    exif[ORIENTATION] = 6  # rotate 90° clockwise to display
    upload = image_bytes(size=(64, 48), exif=exif.tobytes())

    result = process_photo(upload)

    assert (result.width, result.height) == (48, 64)


def test_transparency_survives():
    """A PNG logo on a transparent background must not turn black."""
    upload = image_bytes(fmt="PNG", mode="RGBA", color=(255, 165, 0, 128))

    result = decoded(process_photo(upload).data)

    assert result.mode == "RGBA"


@pytest.mark.parametrize(
    "upload",
    [
        b"not an image at all",
        b"",
        image_bytes(fmt="GIF", mode="P"),
        image_bytes(fmt="BMP"),
        image_bytes(fmt="JPEG")[:200],
    ],
    ids=["text", "empty", "gif", "bmp", "truncated"],
)
def test_anything_but_a_whole_jpeg_png_or_webp_is_refused(upload):
    with pytest.raises(InvalidData):
        process_photo(upload)


def test_a_small_file_that_decodes_into_a_huge_bitmap_is_refused():
    """
    A few kilobytes of PNG can claim to be 20000×20000 pixels: decoding it
    would take gigabytes of memory, whatever the upload size limit.
    """
    side = int(FOTO_MAX_PIXELS**0.5) + 100
    upload = image_bytes(size=(side, side), fmt="PNG", mode="1")
    assert len(upload) < 1024 * 1024

    with pytest.raises(InvalidData):
        process_photo(upload)
