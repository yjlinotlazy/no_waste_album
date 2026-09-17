"""Canonical, versioned non-destructive edit recipes."""

from copy import deepcopy

RECIPE_VERSION = 1
FILTERS = {"none", "warm", "mono", "fade", "matte", "vintage", "cinematic", "portrait_soft", "portrait_warm", "portrait_clear", "portrait_mono", "portrait_cinematic", "kindle_16gray", "shadow_recovery", "night_lift", "backlight", "highlight_recovery", "local_clahe", "auto_develop"}


def default_recipe() -> dict:
    return {"schema_version": RECIPE_VERSION, "crop": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}, "adjustments": {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0, "temperature": 0.0}, "filter": "none", "rotate": 0}


def _number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value, low, high):
    return max(low, min(high, _number(value)))


def normalize(recipe: dict) -> dict:
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be an object")
    base = default_recipe()
    crop = recipe.get("crop") or {}
    adjustments = recipe.get("adjustments") or {}
    base["crop"] = {"x": _clamp(crop.get("x"), 0, 1), "y": _clamp(crop.get("y"), 0, 1), "width": _clamp(crop.get("width", 1), 0.01, 1), "height": _clamp(crop.get("height", 1), 0.01, 1)}
    base["crop"]["x"] = min(base["crop"]["x"], 1 - base["crop"]["width"])
    base["crop"]["y"] = min(base["crop"]["y"], 1 - base["crop"]["height"])
    base["adjustments"] = {key: _clamp(adjustments.get(key), -1, 1) for key in ("brightness", "contrast", "saturation", "temperature")}
    selected_filter = recipe.get("filter", "none")
    if selected_filter not in FILTERS:
        raise ValueError(f"unsupported filter: {selected_filter}")
    base["filter"] = selected_filter
    base["rotate"] = round(_clamp(recipe.get("rotate"), -180, 180), 2)
    name = str(recipe.get("name", "")).strip()
    if name:
        base["name"] = name[:80]
    for key in ("exposure", "shadows", "highlights", "local_contrast", "analysis", "source_job_id"):
        if key in recipe:
            base[key] = recipe[key]
    return deepcopy(base)
