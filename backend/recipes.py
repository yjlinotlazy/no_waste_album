"""Canonical, versioned non-destructive edit recipes."""

from copy import deepcopy

RECIPE_VERSION = 1
CURVE_CHANNELS = ("rgb", "red", "green", "blue")
HSL_CHANNELS = ("red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta")
FILTERS = {"none", "warm", "mono", "fade", "matte", "vintage", "cinematic", "autumn", "portrait_soft", "portrait_warm", "portrait_clear", "portrait_mono", "portrait_cinematic", "portrait_depth", "reduce_overexposure", "kindle_16gray", "shadow_recovery", "night_lift", "backlight", "highlight_recovery", "local_clahe", "auto_develop"}


def default_recipe() -> dict:
    identity = [[0, 0], [255, 255]]
    return {"schema_version": RECIPE_VERSION, "crop": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}, "adjustments": {"exposure": 0.0, "brightness": 0.0, "contrast": 0.0, "highlights": 0.0, "shadows": 0.0, "blacks": 0.0, "saturation": 0.0, "vibrance": 0.0, "temperature": 0.0, "tint": 0.0, "sharpness": 0.0, "clarity": 0.0, "noise_reduction": 0.0, "vignette": 0.0, "depth": 0.0}, "auto_wb": {"enabled": False, "temperature": 0.0}, "curves": {channel: identity[:] for channel in CURVE_CHANNELS}, "hsl": {channel: {"hue": 0.0, "saturation": 0.0, "luminance": 0.0} for channel in HSL_CHANNELS}, "aperture": {"enabled": False, "x": 0.5, "y": 0.6, "radius": 0.18, "strength": 1.0}, "lut": {"id": "", "intensity": 1.0, "input_profile": "display"}, "filter": "none", "local_correction": "none", "nodes": [], "rotate": 0}


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
    base["rotate"] = round(_clamp(recipe.get("rotate"), -180, 180), 2)
    adjustment_keys = ("exposure", "brightness", "contrast", "highlights", "shadows", "blacks", "saturation", "vibrance", "temperature", "tint", "sharpness", "clarity", "noise_reduction", "vignette")
    base["adjustments"] = {key: _clamp(adjustments.get(key), -1, 1) for key in adjustment_keys}
    base["adjustments"]["depth"] = _clamp(adjustments.get("depth"), 0, 1)
    raw_auto_wb = recipe.get("auto_wb") or {}
    base["auto_wb"] = {"enabled": bool(raw_auto_wb.get("enabled", False)), "temperature": _clamp(raw_auto_wb.get("temperature"), -1, 1)}
    raw_curves = recipe.get("curves") or {}
    curves = {}
    for channel in CURVE_CHANNELS:
        points = []
        for point in (raw_curves.get(channel) or [[0, 0], [255, 255]])[:33]:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            points.append([round(_clamp(point[0], 0, 255)), round(_clamp(point[1], 0, 255))])
        points.sort(key=lambda point: point[0])
        if not points or points[0][0] != 0:
            points.insert(0, [0, 0])
        if points[-1][0] != 255:
            points.append([255, 255])
        curves[channel] = points
    base["curves"] = curves
    raw_hsl = recipe.get("hsl") or {}
    base["hsl"] = {
        channel: {
            "hue": _clamp((raw_hsl.get(channel) or {}).get("hue"), -100, 100),
            "saturation": _clamp((raw_hsl.get(channel) or {}).get("saturation"), -100, 100),
            "luminance": _clamp((raw_hsl.get(channel) or {}).get("luminance"), -100, 100),
        }
        for channel in HSL_CHANNELS
    }
    raw_aperture = recipe.get("aperture") or {}
    base["aperture"] = {"enabled": bool(raw_aperture.get("enabled", False)), "x": _clamp(raw_aperture.get("x", 0.5), 0, 1), "y": _clamp(raw_aperture.get("y", 0.6), 0, 1), "radius": _clamp(raw_aperture.get("radius", 0.18), 0.03, 0.8), "strength": _clamp(raw_aperture.get("strength", 1.0), 0, 1)}
    raw_lut = recipe.get("lut") or {}
    input_profile = str(raw_lut.get("input_profile", "display"))
    if input_profile not in {"display", "f_log2", "s_log3", "leica_l_log"}:
        input_profile = "display"
    base["lut"] = {"id": str(raw_lut.get("id", ""))[:128], "intensity": _clamp(raw_lut.get("intensity", 1.0), 0, 1), "input_profile": input_profile}
    strokes = []
    for stroke in (recipe.get("mask_strokes") or [])[:4000]:
        if not isinstance(stroke, dict):
            continue
        mode = "erase" if stroke.get("mode") == "erase" else "add"
        strokes.append({"x": _clamp(stroke.get("x"), 0, 1), "y": _clamp(stroke.get("y"), 0, 1), "radius": _clamp(stroke.get("radius", 0.04), 0.002, 0.25), "mode": mode})
    if strokes:
        base["mask_strokes"] = strokes
    selected_filter = recipe.get("filter", "none")
    local_correction = recipe.get("local_correction", "none")
    if selected_filter == "reduce_overexposure":
        local_correction = "reduce_overexposure"
        selected_filter = "none"
    if selected_filter not in FILTERS:
        raise ValueError(f"unsupported filter: {selected_filter}")
    if local_correction not in {"none", "reduce_overexposure"}:
        raise ValueError(f"unsupported local correction: {local_correction}")
    base["filter"] = selected_filter
    base["local_correction"] = local_correction
    raw_nodes = recipe.get("nodes")
    if raw_nodes is None:
        raw_nodes = []
        if selected_filter != "none":
            raw_nodes.append({"type": "filter", "name": selected_filter, "enabled": True})
        if local_correction != "none":
            raw_nodes.append({"type": "local_correction", "name": local_correction, "enabled": True})
        if base["crop"] != default_recipe()["crop"] or base["rotate"]:
            raw_nodes.append({"type": "canvas", "name": "画布调整", "enabled": True})
        if any(abs(_number(base["adjustments"].get(key))) > 1e-9 for key in (*adjustment_keys, "depth")):
            raw_nodes.append({"type": "adjustments", "name": "画面调整", "enabled": True})
        if base["auto_wb"]["enabled"]:
            raw_nodes.append({"type": "auto_wb", "name": "自动白平衡", "enabled": True})
        if any(points != [[0, 0], [255, 255]] for points in curves.values()):
            raw_nodes.append({"type": "curves", "name": "曲线", "enabled": True})
        if any(abs(value) > 1e-9 for channel in base["hsl"].values() for value in channel.values()):
            raw_nodes.append({"type": "hsl", "name": "HSL", "enabled": True})
        if base["aperture"]["enabled"]:
            raw_nodes.append({"type": "aperture", "name": "Aperture", "enabled": True})
        if base["lut"]["id"]:
            raw_nodes.append({"type": "lut", "name": "LUT", "enabled": True})
    has_adjustments = any(abs(_number(base["adjustments"].get(key))) > 1e-9 for key in (*adjustment_keys, "depth"))
    has_curves = any(points != [[0, 0], [255, 255]] for points in curves.values())
    has_hsl = any(abs(value) > 1e-9 for channel in base["hsl"].values() for value in channel.values())
    nodes = []
    for index, node in enumerate(raw_nodes[:100]):
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type", "adjustments"))[:40]
        if node_type == "adjustments" and str(node.get("name", "")).strip() in {"调色", "画面调整"}:
            node_type = "adjustments"
        if node_type == "adjustments" and not has_adjustments:
            continue
        if node_type == "curves" and not has_curves:
            continue
        node_name = str(node.get("name", node_type)).strip()[:80] or node_type
        if node_type == "canvas":
            node_name = "画布调整"
        elif node_type == "adjustments":
            node_name = "画面调整"
        elif node_type == "auto_wb":
            node_name = "自动白平衡"
        elif node_type == "hsl":
            node_name = "HSL"
        nodes.append({"id": str(node.get("id", f"node-{index + 1}"))[:80], "type": node_type, "name": node_name, "enabled": bool(node.get("enabled", True))})
    existing_types = {node["type"] for node in nodes}
    has_canvas = base["crop"] != default_recipe()["crop"] or bool(base["rotate"])
    if has_canvas and "canvas" not in existing_types:
        nodes.insert(0, {"id": "canvas", "type": "canvas", "name": "画布调整", "enabled": True})
    if has_adjustments and "adjustments" not in existing_types:
        nodes.append({"id": "adjustments", "type": "adjustments", "name": "画面调整", "enabled": True})
    if base["auto_wb"]["enabled"] and "auto_wb" not in existing_types:
        nodes.append({"id": "auto-wb", "type": "auto_wb", "name": "自动白平衡", "enabled": True})
    if selected_filter != "none" and "filter" not in existing_types:
        nodes.append({"id": "filter", "type": "filter", "name": selected_filter, "enabled": True})
    if local_correction != "none" and "local_correction" not in existing_types:
        nodes.append({"id": "local", "type": "local_correction", "name": local_correction, "enabled": True})
    if has_curves and "curves" not in existing_types:
        nodes.append({"id": "curves", "type": "curves", "name": "曲线", "enabled": True})
    if has_hsl and "hsl" not in existing_types:
        nodes.append({"id": "hsl", "type": "hsl", "name": "HSL", "enabled": True})
    if base["aperture"]["enabled"] and "aperture" not in existing_types:
        nodes.append({"id": "aperture", "type": "aperture", "name": "Aperture", "enabled": True})
    if base["lut"]["id"] and "lut" not in existing_types:
        nodes.append({"id": "lut", "type": "lut", "name": "LUT", "enabled": True})
    base["nodes"] = nodes
    disabled_types = {node["type"] for node in nodes if not node["enabled"]}
    # The explicit recipe value is authoritative. The node-toggle UI sets
    # recipe["filter"] to "none" when a filter node is disabled, so a stale
    # disabled node cannot cancel a new filter selection.
    if "local_correction" in disabled_types:
        base["local_correction"] = "none"
    if "aperture" in disabled_types:
        base["aperture"]["enabled"] = False
    name = str(recipe.get("name", "")).strip()
    if name:
        base["name"] = name[:80]
    for key in ("exposure", "shadows", "highlights", "local_contrast", "analysis", "source_job_id", "preset"):
        if key in recipe:
            base[key] = recipe[key]
    return deepcopy(base)
