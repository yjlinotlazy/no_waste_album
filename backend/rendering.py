"""Authoritative full-resolution renderer for saved edit recipes."""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .recipes import normalize


def _tone_map(image, shadows: float, highlights: float, gamma: float) -> Image.Image:
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue = pixels[x, y]
            luminance = (red + green + blue) / 765
            shadow_weight = (1 - luminance) ** 2
            highlight_weight = luminance ** 2
            values = []
            for value in (red, green, blue):
                lifted = ((value / 255) ** gamma) * 255
                adjusted = value + (lifted - value) * shadows * shadow_weight
                adjusted *= 1 - highlights * highlight_weight
                values.append(max(0, min(255, round(adjusted))))
            pixels[x, y] = tuple(values)
    return image


def _clahe_luminance(image: Image.Image) -> Image.Image:
    """Apply OpenCV's contrast-limited adaptive histogram equalization to L."""
    rgb = np.asarray(image, dtype=np.uint8)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return Image.fromarray(enhanced, mode="RGB")


def _auto_develop(image: Image.Image, recipe: dict) -> Image.Image:
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    exposure = float(recipe.get("exposure", 0))
    rgb *= 2 ** exposure
    temperature = float(recipe.get("adjustments", {}).get("temperature", 0))
    rgb[:, :, 0] *= 1 + max(0, temperature) * 0.35
    rgb[:, :, 2] *= 1 + max(0, -temperature) * 0.35
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    shadows = float(recipe.get("shadows", 0))
    highlights = float(recipe.get("highlights", 0))
    shadow_weight = (1 - np.clip(luminance, 0, 1)) ** 2
    highlight_weight = np.clip(luminance, 0, 1) ** 2
    rgb += (np.power(np.clip(rgb, 0, 1), 0.78) - rgb) * shadows * shadow_weight[:, :, None]
    rgb *= 1 - highlights * highlight_weight[:, :, None]
    result = Image.fromarray(np.uint8(np.clip(rgb, 0, 1) * 255), mode="RGB")
    if recipe.get("local_contrast"):
        result = _clahe_luminance(result)
    return result


class Renderer:
    def __init__(self, library_root: Path):
        self.root = library_root.resolve()

    def render(self, relative_path: str, recipe: dict, destination: Path) -> Path:
        source = (self.root / relative_path).resolve()
        if self.root not in source.parents or any(part.casefold() == "raw" for part in source.relative_to(self.root).parts):
            raise ValueError("source is outside the catalog")
        if not source.is_file():
            raise FileNotFoundError(relative_path)
        recipe = normalize(recipe)
        with Image.open(source) as original:
            image = original.convert("RGB")
        crop = recipe["crop"]
        width, height = image.size
        box = (round(crop["x"] * width), round(crop["y"] * height), round((crop["x"] + crop["width"]) * width), round((crop["y"] + crop["height"]) * height))
        image = image.crop(box)
        if recipe["rotate"]:
            image = image.rotate(recipe["rotate"], expand=True)
        adjustments = recipe["adjustments"]
        image = ImageEnhance.Brightness(image).enhance(1 + adjustments["brightness"])
        image = ImageEnhance.Contrast(image).enhance(1 + adjustments["contrast"])
        image = ImageEnhance.Color(image).enhance(1 + adjustments["saturation"])
        temperature = adjustments["temperature"]
        if temperature:
            color = (255, 145, 55) if temperature > 0 else (65, 140, 255)
            overlay = Image.new("RGB", image.size, color)
            image = Image.blend(image, overlay, abs(temperature) * 0.2)
        selected_filter = recipe["filter"]
        if selected_filter == "fade":
            image = ImageEnhance.Contrast(image).enhance(0.84)
            image = ImageEnhance.Brightness(image).enhance(1.04)
        elif selected_filter == "matte":
            image = ImageEnhance.Contrast(image).enhance(0.88)
            image = ImageEnhance.Color(image).enhance(0.88)
            image = ImageEnhance.Brightness(image).enhance(1.03)
        elif selected_filter == "vintage":
            image = ImageEnhance.Contrast(image).enhance(0.88)
            image = ImageEnhance.Color(image).enhance(0.82)
            image = Image.blend(image, Image.new("RGB", image.size, (255, 170, 90)), 0.10)
        elif selected_filter == "cinematic":
            image = ImageEnhance.Contrast(image).enhance(1.08)
            image = ImageEnhance.Color(image).enhance(0.84)
            image = Image.blend(image, Image.new("RGB", image.size, (70, 105, 160)), 0.05)
        elif selected_filter == "portrait_soft":
            image = ImageEnhance.Contrast(image).enhance(0.90)
            image = ImageEnhance.Color(image).enhance(0.96)
            image = ImageEnhance.Brightness(image).enhance(1.04)
        elif selected_filter == "portrait_warm":
            image = ImageEnhance.Color(image).enhance(1.06)
            image = ImageEnhance.Brightness(image).enhance(1.03)
            image = Image.blend(image, Image.new("RGB", image.size, (255, 150, 75)), 0.08)
        elif selected_filter == "portrait_clear":
            image = ImageEnhance.Contrast(image).enhance(1.08)
            image = ImageEnhance.Color(image).enhance(1.06)
            image = ImageEnhance.Brightness(image).enhance(1.03)
        elif selected_filter == "portrait_mono":
            image = image.convert("L").convert("RGB")
            image = ImageEnhance.Contrast(image).enhance(1.10)
        elif selected_filter == "portrait_cinematic":
            image = ImageEnhance.Contrast(image).enhance(1.06)
            image = ImageEnhance.Color(image).enhance(0.88)
            image = Image.blend(image, Image.new("RGB", image.size, (75, 105, 155)), 0.04)
        elif selected_filter == "kindle_16gray":
            image = image.convert("L")
        elif selected_filter == "shadow_recovery":
            image = _tone_map(image, 0.62, 0.12, 0.78)
        elif selected_filter == "night_lift":
            image = _tone_map(image, 0.78, 0.22, 0.70)
            image = ImageEnhance.Color(image).enhance(0.90)
        elif selected_filter == "backlight":
            image = _tone_map(image, 0.68, 0.32, 0.76)
        elif selected_filter == "highlight_recovery":
            image = _tone_map(image, 0.22, 0.62, 0.92)
        elif selected_filter == "local_clahe":
            image = _clahe_luminance(image)
        elif selected_filter == "auto_develop":
            image = _auto_develop(image, recipe)
        if selected_filter in {"mono", "portrait_mono"}:
            image = image.convert("L").convert("RGB")
        elif selected_filter == "warm":
            overlay = Image.new("RGB", image.size, (255, 150, 50))
            image = Image.blend(image, overlay, 0.12)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if selected_filter == "kindle_16gray":
            fitted = ImageOps.contain(image, (600, 800), method=Image.Resampling.LANCZOS)
            image = fitted.point(lambda value: round(value / 17) * 17)
            image.save(destination, format="PNG", optimize=True)
        elif destination.suffix.casefold() == ".png":
            image.save(destination, format="PNG", optimize=True)
        else:
            image.save(destination, format="JPEG", quality=92, optimize=True)
        return destination
