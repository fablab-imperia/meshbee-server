"""
Turning an uploaded photo into the one that is stored (#3).

Nothing is kept as uploaded. The image is decoded, turned upright, scaled down
and re-encoded as WebP, which:

- drops every piece of metadata, the GPS position a phone writes included;
- leaves a file a phone app can show without downloading megabytes;
- means what is served was produced here, not crafted by the uploader: a file
  that only pretends to be an image does not survive the round trip.
"""

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from meshbee_core.errors import InvalidData
from meshbee_core.limits import FOTO_FORMATI, FOTO_MAX_LATO, FOTO_MAX_PIXELS

CONTENT_TYPE = "image/webp"
EXTENSION = "webp"
QUALITY = 80

INVALID = "Il file non è un'immagine valida (JPEG, PNG o WebP)"


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    extension: str
    width: int
    height: int


def process_photo(data: bytes) -> ProcessedImage:
    """
    Raises:
        InvalidData: if the bytes are not a JPEG, PNG or WebP image, or would
            decode into more than FOTO_MAX_PIXELS pixels.
    """
    try:
        with warnings.catch_warnings():
            # Past MAX_IMAGE_PIXELS Pillow only warns; past twice that it raises.
            # Both are a refusal here.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = _open(data)
            image = ImageOps.exif_transpose(image)
    # OSError covers UnidentifiedImageError (not an image) and a truncated file.
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as e:
        raise InvalidData(INVALID) from e

    # WebP takes RGB or RGBA: a PNG keeps its transparency, a palette or a
    # greyscale image is widened, a CMYK JPEG converted.
    mode = "RGBA" if image.has_transparency_data else "RGB"
    if image.mode != mode:
        image = image.convert(mode)
    image.thumbnail((FOTO_MAX_LATO, FOTO_MAX_LATO), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    # No exif=, no icc_profile=: nothing of the original's metadata is written.
    image.save(out, format="WEBP", quality=QUALITY, method=4)
    return ProcessedImage(
        data=out.getvalue(),
        content_type=CONTENT_TYPE,
        extension=EXTENSION,
        width=image.width,
        height=image.height,
    )


def _open(data: bytes) -> Image.Image:
    # Pillow's limit is a process-wide global; the bound is checked here too so
    # it holds whatever another library sets it to.
    Image.MAX_IMAGE_PIXELS = FOTO_MAX_PIXELS
    image = Image.open(io.BytesIO(data), formats=FOTO_FORMATI)
    width, height = image.size
    if width * height > FOTO_MAX_PIXELS:
        raise Image.DecompressionBombError(f"{width}x{height}")
    image.load()
    return image
