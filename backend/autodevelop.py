"""Explainable automatic development parameter estimation."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def estimate(path: Path) -> dict:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((512, 512), Image.Resampling.BILINEAR)
        pixels = np.asarray(image, dtype=np.float32) / 255.0
    luminance = pixels @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    p05, p20, p50, p95 = np.percentile(luminance, [5, 20, 50, 95])
    exposure = float(np.clip(np.log2(0.43 / max(p50, 0.04)), -0.65, 0.65))
    red, green, blue = pixels.reshape(-1, 3).mean(axis=0)
    chroma_mean = max((red + green + blue) / 3, 0.05)
    temperature = float(np.clip((blue - red) / chroma_mean * 0.22, -0.35, 0.35))
    shadows = float(np.clip((0.26 - p20) * 1.8, 0.0, 0.55))
    highlights = float(np.clip((p95 - 0.78) * 1.8, 0.0, 0.45))
    local_contrast = bool(p20 < 0.24 or (p95 - p05) < 0.42)
    return {
        "exposure": round(exposure, 3),
        "temperature": round(temperature, 3),
        "shadows": round(shadows, 3),
        "highlights": round(highlights, 3),
        "local_contrast": local_contrast,
        "analysis": {"p05": round(float(p05), 3), "p20": round(float(p20), 3), "p50": round(float(p50), 3), "p95": round(float(p95), 3)},
    }
