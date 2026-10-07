"""Authoritative full-resolution renderer for saved edit recipes."""

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .depth import extract, extract_portrait_matte
from .luts import apply_cube, load_cube
from .quality import _load_image
from .recipes import normalize


def _curve_lut(points: list[list[int]]) -> list[int]:
    points = sorted(points, key=lambda point: point[0])
    lut = []
    if len(points) == 2:
        left, right = points
        span = max(1, right[0] - left[0])
        return [round(left[1] + (right[1] - left[1]) * max(0, min(1, (value - left[0]) / span))) for value in range(256)]
    for value in range(256):
        if value <= points[0][0]:
            lut.append(points[0][1])
            continue
        if value >= points[-1][0]:
            lut.append(points[-1][1])
            continue
        for index, (left, right) in enumerate(zip(points, points[1:])):
            if value <= right[0]:
                span = max(1, right[0] - left[0])
                t = (value - left[0]) / span
                previous = points[max(0, index - 1)]
                following = points[min(len(points) - 1, index + 2)]
                y = 0.5 * ((2 * left[1]) + (-previous[1] + right[1]) * t + (2 * previous[1] - 5 * left[1] + 4 * right[1] - following[1]) * t * t + (-previous[1] + 3 * left[1] - 3 * right[1] + following[1]) * t * t * t)
                lut.append(round(max(0, min(255, y))))
                break
    return lut


def _apply_curves(image: Image.Image, curves: dict) -> Image.Image:
    result = image
    rgb_lut = _curve_lut(curves.get("rgb", [[0, 0], [255, 255]]))
    if result.mode == "L":
        return result.point(rgb_lut)
    result = result.point(rgb_lut * 3)
    channels = list(result.split())
    for index, channel in enumerate(("red", "green", "blue")):
        channels[index] = channels[index].point(_curve_lut(curves.get(channel, [[0, 0], [255, 255]])))
    return Image.merge("RGB", channels)


def _autumn_grade(image: Image.Image) -> Image.Image:
    """Apply the color portion of the supplied autumn reference grade.

    The reference's learned RGB mapping needs a pixel-aligned original and
    reference pair, which the editor does not have for arbitrary photos. This
    keeps its reusable parts: warm base grade, two foliage passes, and sky/tree
    boundary protection. Depth-of-field processing intentionally lives in the
    separate aperture node.
    """
    rgb = np.asarray(image, dtype=np.uint8)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    lightness, a_channel, b_channel = cv2.split(lab)
    lightness = np.clip(lightness * 1.035 + 2.0, 0, 255)
    a_channel = np.clip(a_channel + 1.5, 0, 255)
    b_channel = np.clip(b_channel + 3.5, 0, 255)
    base = cv2.cvtColor(cv2.merge([lightness, a_channel, b_channel]).astype(np.uint8), cv2.COLOR_LAB2RGB)

    def foliage_pass(source, final=False):
        hsv = cv2.cvtColor(source, cv2.COLOR_RGB2HSV).astype(np.float32)
        hue, saturation, value = cv2.split(hsv)
        gate = np.clip((saturation - (48 if final else 45)) / (115 if final else 120), 0, 1)
        yellow = np.exp(-0.5 * ((hue - 28) / 9) ** 2)
        orange = np.exp(-0.5 * ((hue - 16) / 8) ** 2)
        green = np.exp(-0.5 * ((hue - 43) / 11) ** 2)
        foliage = np.clip((
            (0.95 if final else 0.85) * yellow
            + (0.75 if final else 0.42) * orange
            + (0.40 if final else 0.62) * green
        ) * gate, 0, 1)
        hue = np.clip(hue - (2.8 if final else 2.0) * yellow * gate - (4.0 if final else 3.0) * green * gate, 0, 179)
        saturation = np.clip(saturation * (1 + (0.24 if final else 0.18) * foliage), 0, 255)
        value = np.clip(value * (1 + (0.008 if final else 0.015) * foliage), 0, 255)
        return cv2.cvtColor(cv2.merge([hue, saturation, value]).astype(np.uint8), cv2.COLOR_HSV2RGB)

    autumn = foliage_pass(base)

    # Protect foliage and branch edges touching the sky from hard hue seams.
    original_hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, saturation, value = cv2.split(original_hsv)
    sky = ((hue > 88) & (hue < 135) & (saturation > 25) & (value > 105)).astype(np.uint8) * 255
    sky = cv2.morphologyEx(sky, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    dilated = cv2.dilate(sky, np.ones((13, 13), np.uint8))
    eroded = cv2.erode(sky, np.ones((7, 7), np.uint8))
    boundary = cv2.GaussianBlur(((dilated > 0) & (eroded == 0)).astype(np.float32), (0, 0), 2.0)
    boundary = np.clip(boundary, 0, 1)[..., None]
    result = autumn.astype(np.float32) * (1 - boundary) + base.astype(np.float32) * boundary

    final = foliage_pass(np.clip(result, 0, 255).astype(np.uint8), final=True)
    return Image.fromarray(np.clip(final, 0, 255).astype(np.uint8), mode="RGB")


def _apply_aperture(image: Image.Image, aperture: dict) -> Image.Image:
    if not aperture.get("enabled"):
        return image
    width, height = image.size
    y, x = np.mgrid[0:height, 0:width]
    nx, ny = x / max(1, width), y / max(1, height)
    radius = max(0.03, float(aperture.get("radius", 0.18)))
    distance = np.sqrt(((nx - float(aperture.get("x", 0.5))) / radius) ** 2 + ((ny - float(aperture.get("y", 0.6))) / radius) ** 2)
    mask = np.clip((distance - 0.72) / 1.35, 0, 1) * float(aperture.get("strength", 1.0))
    blurred = image.filter(ImageFilter.GaussianBlur(max(0.5, 10 * float(aperture.get("strength", 1.0)))))
    original = np.asarray(image, dtype=np.float32)
    softened = np.asarray(blurred, dtype=np.float32)
    result = original * (1 - mask[..., None]) + softened * mask[..., None]
    sharp = np.asarray(image.filter(ImageFilter.UnsharpMask(radius=1.4, percent=135, threshold=3)), dtype=np.float32)
    focus = np.clip((1.12 - np.sqrt(((nx - float(aperture.get("x", 0.5))) / radius) ** 2 + ((ny - float(aperture.get("y", 0.6))) / radius) ** 2)) / 1.12, 0, 1)
    result = result * (1 - focus[..., None] * 0.72) + sharp * (focus[..., None] * 0.72)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), mode="RGB")


def _apply_depth_of_field(image: Image.Image, depth: Image.Image, matte: Image.Image | None, strength: float) -> Image.Image:
    """Render HEIC portrait depth as optical defocus, not a flat blur overlay.

    Apple's portrait result defocuses anything in front of or behind the
    selected focal plane.  The old implementation only blurred pixels judged
    to be far away, then retained too much of the original image.  That made
    the background look like a sharp photo with Gaussian blur painted on it.
    """
    amount = max(0.0, min(1.0, float(strength)))
    if amount <= 0:
        return image
    source = np.asarray(image, dtype=np.float32)
    height, width = source.shape[:2]
    depth_values = np.asarray(depth.convert("L").resize((width, height), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0

    # The portrait matte identifies the focal subject.  Use its depth as the
    # focal plane, so both the distant sky/buildings and near snow defocus.
    if matte is not None:
        matte_probe = np.asarray(matte.convert("L").resize((width, height), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
        subject_depth = depth_values[matte_probe > 0.55]
        focus_depth = float(np.median(subject_depth)) if subject_depth.size else 0.52
    else:
        matte_probe = None
        focus_depth = 0.52

    defocus = np.abs(depth_values - focus_depth)
    defocus = np.clip((defocus - 0.035) / 0.43, 0.0, 1.0)
    defocus = np.power(cv2.GaussianBlur(defocus, (0, 0), 1.4), 0.88)
    defocus = np.clip(defocus * amount * 1.35, 0.0, 1.0)

    if matte is not None:
        matte_values = matte_probe
        foreground = np.clip((matte_values - 0.08) / 0.32, 0.0, 1.0)
    else:
        foreground = np.zeros((height, width), dtype=np.float32)

    # Keep the hard subject out of the blur kernel; feather only the final edge.
    foreground_core = (foreground > 0.42).astype(np.float32)
    background_support = 1.0 - foreground_core
    feathered_foreground = cv2.GaussianBlur(foreground, (0, 0), 1.4)

    def protected_blur(sigma: float) -> np.ndarray:
        support = cv2.GaussianBlur(background_support, (0, 0), sigma)
        numerator = cv2.GaussianBlur(source * background_support[..., None], (0, 0), sigma)
        return np.divide(numerator, np.maximum(support[..., None], 1e-3), out=source.copy(), where=support[..., None] > 1e-3)

    blurred = [source, protected_blur(4.0), protected_blur(9.0), protected_blur(16.0)]
    position = np.clip(defocus * 3.0, 0.0, 2.999)
    index = np.floor(position).astype(np.int32)
    fraction = position - index
    background = np.zeros_like(source)
    for level in range(3):
        selected = index == level
        blend = blurred[level] * (1.0 - fraction[..., None]) + blurred[level + 1] * fraction[..., None]
        background[selected] = blend[selected]

    blur_alpha = np.clip(defocus, 0.0, 1.0) * (1.0 - np.clip(feathered_foreground * 0.99, 0.0, 1.0))
    result = source * (1.0 - blur_alpha[..., None]) + background * blur_alpha[..., None]

    # The subject remains the original pixels.  Do not sharpen it here: the
    # old extra sharpening created a visible digital halo around the child.
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), mode="RGB")


def _largest_inner_rect(width: float, height: float, angle: float) -> tuple[int, int]:
    """Return the largest axis-aligned rectangle inside a rotated rectangle.

    Rotation expands the canvas, which otherwise leaves triangular background
    corners.  This returns the centered crop size that removes those corners
    while keeping as much of the rotated image as possible.
    """
    width, height = float(width), float(height)
    if width <= 0 or height <= 0:
        return 1, 1
    angle = abs(float(angle)) % 180
    if angle > 90:
        angle = 180 - angle
    quarter_turn = angle > 45
    if quarter_turn:
        angle = 90 - angle
    swap_base = width < height
    if swap_base:
        width, height = height, width
    radians = math.radians(angle)
    sine, cosine = abs(math.sin(radians)), abs(math.cos(radians))
    if sine < 1e-9:
        inner_width, inner_height = width, height
    elif height <= 2 * sine * cosine * width:
        half_height = height / 2
        inner_width = half_height / sine
        inner_height = half_height / cosine
    else:
        cosine_twice = cosine * cosine - sine * sine
        inner_width = (width * cosine - height * sine) / cosine_twice
        inner_height = (height * cosine - width * sine) / cosine_twice
    if swap_base:
        inner_width, inner_height = inner_height, inner_width
    if quarter_turn:
        inner_width, inner_height = inner_height, inner_width
    return max(1, math.floor(inner_width)), max(1, math.floor(inner_height))


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


def _reduce_overexposure(image: Image.Image, mask_strokes: list[dict] | None = None) -> Image.Image:
    """Warm autumn grade with restrained highlight reduction and optical blur.

    The recovery mask is derived from the image, not from a fixed subject
    polygon.  It favors non-sky, low-saturation areas where veiling glare is
    most visible, so the filter remains useful across different compositions.
    """
    rgb = np.asarray(image, dtype=np.uint8)
    height, width = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lightness, a_channel, b_channel = cv2.split(lab)
    lightness = np.clip(lightness * 1.035 + 2.0, 0, 255)
    a_channel = np.clip(a_channel + 1.5, 0, 255)
    b_channel = np.clip(b_channel + 3.5, 0, 255)
    base = cv2.cvtColor(cv2.merge([lightness, a_channel, b_channel]).astype(np.uint8), cv2.COLOR_LAB2BGR)

    def autumn_pass(source: np.ndarray, final: bool = False) -> np.ndarray:
        hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV).astype(np.float32)
        hue, saturation, value = cv2.split(hsv)
        gate = np.clip((saturation - (48 if final else 45)) / (115 if final else 120), 0, 1)
        yellow = np.exp(-0.5 * ((hue - 28) / 9) ** 2)
        orange = np.exp(-0.5 * ((hue - 16) / 8) ** 2)
        green = np.exp(-0.5 * ((hue - 43) / 11) ** 2)
        foliage = np.clip((0.95 * yellow + 0.75 * orange + 0.40 * green if final else 0.85 * yellow + 0.42 * green + 0.62 * orange) * gate, 0, 1)
        hue = np.clip(hue - (2.8 * yellow * gate + 4.0 * green * gate if final else 2.0 * yellow * gate + 3.0 * green * gate), 0, 179)
        saturation = np.clip(saturation * (1 + (0.24 if final else 0.18) * foliage), 0, 255)
        value = np.clip(value * (1 + (0.008 if final else 0.015) * foliage), 0, 255)
        return cv2.cvtColor(cv2.merge([hue, saturation, value]).astype(np.uint8), cv2.COLOR_HSV2BGR)

    autumn = autumn_pass(base)
    original_hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(original_hsv)
    sky = (((hue > 88) & (hue < 135) & (saturation > 25) & (value > 105)).astype(np.uint8) * 255)
    sky = cv2.morphologyEx(sky, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    boundary = ((cv2.dilate(sky, np.ones((13, 13), np.uint8)) > 0) & (cv2.erode(sky, np.ones((7, 7), np.uint8)) == 0)).astype(np.float32)
    boundary = np.clip(cv2.GaussianBlur(boundary, (0, 0), 2.0), 0, 1)
    result = autumn.astype(np.float32) * (1 - boundary[..., None]) + base.astype(np.float32) * boundary[..., None]

    final = autumn_pass(np.clip(result, 0, 255).astype(np.uint8), final=True)

    # Detect likely veiling glare generically: exclude sky and favor
    # low-saturation scene regions.  This catches gray subjects, buildings,
    # roads, and vehicles without assuming a train or a particular location.
    non_sky = 1.0 - cv2.GaussianBlur(sky.astype(np.float32) / 255, (0, 0), 4)
    low_saturation = np.clip((120 - saturation.astype(np.float32)) / 100, 0, 1)
    repair_mask = cv2.GaussianBlur(non_sky * (0.25 + 0.75 * low_saturation), (0, 0), 4)
    manual_mask = None
    if mask_strokes:
        manual = np.zeros((height, width), np.uint8)
        for stroke in mask_strokes:
            center = (round(float(stroke["x"]) * width), round(float(stroke["y"]) * height))
            radius = max(1, round(float(stroke["radius"]) * max(width, height)))
            color = 0 if stroke.get("mode") == "erase" else 255
            cv2.circle(manual, center, radius, color, -1)
        manual_mask = cv2.GaussianBlur(manual.astype(np.float32) / 255, (0, 0), 3)
        repair_mask *= manual_mask

    # Apply restrained local contrast and a small shadow lift only inside that
    # adaptive mask; global sharpening would make flare boundaries crunchy.
    final_lab = cv2.cvtColor(final, cv2.COLOR_BGR2LAB)
    train_lightness, train_a, train_b = cv2.split(final_lab)
    local = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(32, 32)).apply(train_lightness)
    detail = train_lightness.astype(np.float32) - cv2.GaussianBlur(train_lightness, (0, 0), 18).astype(np.float32)
    lifted = 255 * np.power(train_lightness.astype(np.float32) / 255, 0.68)
    repaired_lightness = np.clip(0.55 * train_lightness + 0.25 * local + 0.20 * lifted + 0.85 * detail, 0, 255).astype(np.uint8)
    repaired = cv2.cvtColor(cv2.merge([repaired_lightness, train_a, train_b]), cv2.COLOR_LAB2BGR)
    final = final.astype(np.float32) * (1 - repair_mask[..., None]) + repaired.astype(np.float32) * repair_mask[..., None]
    final = np.clip(final, 0, 255).astype(np.uint8)
    if manual_mask is not None:
        final = np.clip(bgr.astype(np.float32) * (1 - manual_mask[..., None]) + final.astype(np.float32) * manual_mask[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(cv2.cvtColor(final, cv2.COLOR_BGR2RGB), mode="RGB")


class Renderer:
    def __init__(self, library_root: Path, lut_dir: Path | None = None):
        self.root = library_root.resolve()
        self.lut_dir = lut_dir.resolve() if lut_dir else None

    def render(self, relative_path: str, recipe: dict, destination: Path, max_size: int | None = None) -> Path:
        source = (self.root / relative_path).resolve()
        if self.root not in source.parents or any(part.casefold() == "raw" for part in source.relative_to(self.root).parts):
            raise ValueError("source is outside the catalog")
        if not source.is_file():
            raise FileNotFoundError(relative_path)
        recipe = normalize(recipe)
        disabled_nodes = {node["type"] for node in recipe.get("nodes", []) if not node["enabled"]}
        if "canvas" in disabled_nodes:
            recipe["crop"] = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
            recipe["rotate"] = 0
        if "adjustments" in disabled_nodes:
            recipe["adjustments"] = {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0, "temperature": 0.0, "depth": 0.0}
        image = ImageOps.exif_transpose(_load_image(source)).convert("RGB")
        depth = None
        matte = None
        if recipe["adjustments"].get("depth", 0) and source.suffix.casefold() in {".heic", ".heif"}:
            import tempfile
            with tempfile.TemporaryDirectory(prefix="no-waste-depth-render-") as directory:
                depth_path = extract(source, Path(directory) / "depth.jpg")
                matte_path = extract_portrait_matte(source, Path(directory) / "matte.jpg")
                if depth_path:
                    with Image.open(depth_path) as depth_image:
                        depth = ImageOps.exif_transpose(depth_image).convert("L").resize(image.size, Image.Resampling.BILINEAR)
                if matte_path:
                    with Image.open(matte_path) as matte_image:
                        matte = ImageOps.exif_transpose(matte_image).convert("L").resize(image.size, Image.Resampling.BILINEAR)
        crop = recipe["crop"]
        width, height = image.size
        box = (round(crop["x"] * width), round(crop["y"] * height), round((crop["x"] + crop["width"]) * width), round((crop["y"] + crop["height"]) * height))
        image = image.crop(box)
        if depth:
            depth = depth.crop(box)
        if matte:
            matte = matte.crop(box)
        if recipe["rotate"]:
            image = image.rotate(recipe["rotate"], expand=True, fillcolor=(0, 0, 0))
            crop_width, crop_height = _largest_inner_rect(width=box[2] - box[0], height=box[3] - box[1], angle=recipe["rotate"])
            left = max(0, (image.width - crop_width) // 2)
            top = max(0, (image.height - crop_height) // 2)
            image = image.crop((left, top, left + crop_width, top + crop_height))
            if depth:
                depth = depth.rotate(recipe["rotate"], expand=True, fillcolor=0)
                depth = depth.crop((left, top, left + crop_width, top + crop_height))
            if matte:
                matte = matte.rotate(recipe["rotate"], expand=True, fillcolor=0)
                matte = matte.crop((left, top, left + crop_width, top + crop_height))
        # Crop and rotate at source resolution first. Downscaling the whole
        # image before the crop wastes the pixels needed for a sharp close-up.
        if max_size:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            if depth:
                depth = depth.resize(image.size, Image.Resampling.BILINEAR)
            if matte:
                matte = matte.resize(image.size, Image.Resampling.BILINEAR)
        depth_strength = recipe["adjustments"].get("depth", 0)
        if depth is not None and depth_strength:
            image = _apply_depth_of_field(image, depth, matte, depth_strength)
        adjustments = recipe["adjustments"]
        image = ImageEnhance.Brightness(image).enhance(1 + adjustments["brightness"])
        image = ImageEnhance.Contrast(image).enhance(1 + adjustments["contrast"])
        image = ImageEnhance.Color(image).enhance(1 + adjustments["saturation"])
        temperature = adjustments["temperature"]
        auto_wb = recipe.get("auto_wb") or {}
        if auto_wb.get("enabled") and "auto_wb" not in disabled_nodes:
            temperature += auto_wb.get("temperature", 0)
        if temperature:
            color = (255, 145, 55) if temperature > 0 else (65, 140, 255)
            overlay = Image.new("RGB", image.size, color)
            image = Image.blend(image, overlay, abs(temperature) * 0.2)
        selected_filter = recipe["filter"]
        if selected_filter == "fade":
            image = ImageEnhance.Contrast(image).enhance(0.76)
            image = ImageEnhance.Brightness(image).enhance(1.06)
        elif selected_filter == "matte":
            image = ImageEnhance.Contrast(image).enhance(0.78)
            image = ImageEnhance.Color(image).enhance(0.78)
            image = ImageEnhance.Brightness(image).enhance(1.05)
        elif selected_filter == "vintage":
            image = ImageEnhance.Contrast(image).enhance(0.82)
            image = ImageEnhance.Color(image).enhance(0.72)
            image = Image.blend(image, Image.new("RGB", image.size, (255, 170, 90)), 0.16)
        elif selected_filter == "cinematic":
            image = ImageEnhance.Contrast(image).enhance(1.16)
            image = ImageEnhance.Color(image).enhance(0.76)
            image = Image.blend(image, Image.new("RGB", image.size, (70, 105, 160)), 0.10)
        elif selected_filter == "autumn":
            image = _autumn_grade(image)
        elif selected_filter == "portrait_soft":
            image = ImageEnhance.Contrast(image).enhance(0.84)
            image = ImageEnhance.Color(image).enhance(0.92)
            image = ImageEnhance.Brightness(image).enhance(1.06)
        elif selected_filter == "portrait_warm":
            image = ImageEnhance.Color(image).enhance(1.10)
            image = ImageEnhance.Brightness(image).enhance(1.06)
            image = Image.blend(image, Image.new("RGB", image.size, (255, 150, 75)), 0.12)
        elif selected_filter == "portrait_clear":
            image = ImageEnhance.Contrast(image).enhance(1.14)
            image = ImageEnhance.Color(image).enhance(1.10)
            image = ImageEnhance.Brightness(image).enhance(1.04)
        elif selected_filter == "portrait_mono":
            image = image.convert("L").convert("RGB")
            image = ImageEnhance.Contrast(image).enhance(1.10)
        elif selected_filter == "portrait_cinematic":
            image = ImageEnhance.Contrast(image).enhance(1.12)
            image = ImageEnhance.Color(image).enhance(0.82)
            image = Image.blend(image, Image.new("RGB", image.size, (75, 105, 155)), 0.08)
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
            image = Image.blend(image, overlay, 0.18)
        if selected_filter == "portrait_depth":
            # Keep the filter color-neutral.  Depth controls the background;
            # this filter only restores local subject detail after compositing.
            sharpened = image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=115, threshold=4))
            if matte is not None:
                foreground = matte
            elif depth is not None:
                foreground = depth.point(lambda value: round(max(0, min(255, (value - 95) * 2.2))))
            else:
                foreground = None
            if foreground is not None:
                image = Image.composite(sharpened, image, foreground)
            else:
                image = sharpened
        if recipe.get("local_correction") == "reduce_overexposure":
            image = _reduce_overexposure(image, recipe.get("mask_strokes"))
        lut = recipe.get("lut") or {}
        if self.lut_dir and lut.get("id") and not any(node["type"] == "lut" and not node["enabled"] for node in recipe.get("nodes", [])):
            lut_path = self.lut_dir / str(lut["id"])
            if lut_path.is_file():
                rgb = np.asarray(image, dtype=np.uint8)
                image = Image.fromarray(np.uint8(apply_cube(rgb, load_cube(lut_path), lut.get("intensity", 1.0), lut.get("input_profile", "display")) * 255), mode="RGB")
        if not any(node["type"] == "curves" and not node["enabled"] for node in recipe.get("nodes", [])):
            image = _apply_curves(image, recipe.get("curves", {}))
        if not any(node["type"] == "aperture" and not node["enabled"] for node in recipe.get("nodes", [])):
            image = _apply_aperture(image, recipe.get("aperture", {}))
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
