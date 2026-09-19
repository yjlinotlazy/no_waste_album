"""Persistent, orientation-correct thumbnails for catalog assets."""

from pathlib import Path

from PIL import Image, ImageOps

from .quality import _load_image


THUMBNAIL_VERSION = "thumbnail-v1"


def render(source: Path, target: Path, size: int = 256, quality: int = 88) -> tuple[int, int]:
    image = ImageOps.exif_transpose(_load_image(source)).convert("RGB")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    image.save(temporary, format="JPEG", quality=quality, optimize=True)
    temporary.replace(target)
    return image.width, image.height
