"""Authoritative full-resolution renderer for saved edit recipes."""

from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .recipes import normalize


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
