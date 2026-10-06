"""Small, dependency-free .cube 3D LUT parser and applicator."""

from pathlib import Path

import numpy as np


def display_name(path: Path) -> str:
    """Return the human-readable TITLE from a .cube file when available."""
    try:
        with path.open("r", encoding="utf-8") as source:
            for _ in range(128):
                line = source.readline()
                if not line:
                    break
                comment = line.strip()
                if comment.lower().startswith("#title:"):
                    title = comment.split(":", 1)[1].strip()
                    if title:
                        return title
                fields = line.split(None, 1)
                if len(fields) == 2 and fields[0].upper() == "TITLE":
                    title = fields[1].strip()
                    if len(title) >= 2 and title[0] == title[-1] and title[0] in {'"', "'"}:
                        title = title[1:-1]
                    if title:
                        return title
    except (OSError, UnicodeDecodeError):
        pass
    return path.stem


def load_cube(path: Path) -> dict:
    size = None
    domain_min = np.zeros(3, dtype=np.float32)
    domain_max = np.ones(3, dtype=np.float32)
    values = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        keyword = fields[0].upper()
        if keyword == "LUT_3D_SIZE":
            size = int(fields[1])
        elif keyword == "DOMAIN_MIN":
            domain_min = np.asarray([float(value) for value in fields[1:4]], dtype=np.float32)
        elif keyword == "DOMAIN_MAX":
            domain_max = np.asarray([float(value) for value in fields[1:4]], dtype=np.float32)
        elif keyword in {"TITLE", "LUT_1D_SIZE", "LUT_1D_INPUT_RANGE", "LUT_3D_INPUT_RANGE"}:
            # .cube metadata/header lines are not RGB table entries.
            continue
        elif len(fields) >= 3:
            values.append([float(value) for value in fields[:3]])
    if not size or len(values) != size ** 3:
        raise ValueError("Invalid .cube LUT: missing or incomplete LUT_3D_SIZE data")
    # The .cube format lists red fastest, then green, then blue. NumPy's
    # initial reshape makes the first axis the fastest-changing one, so the
    # parsed [blue, green, red] axes must be reordered for [red, green, blue]
    # indexing during interpolation.
    table = np.asarray(values, dtype=np.float32).reshape((size, size, size, 3)).transpose(2, 1, 0, 3)
    return {"size": size, "domain_min": domain_min, "domain_max": domain_max, "table": table}


def _srgb_to_linear(source: np.ndarray) -> np.ndarray:
    return np.where(source <= 0.04045, source / 12.92, ((source + 0.055) / 1.055) ** 2.4)


def _log_input(source: np.ndarray, profile: str) -> np.ndarray:
    """Approximate camera-log encoding for display-referred HEIC/JPEG input."""
    linear = _srgb_to_linear(source)
    if profile == "f_log2":
        encoded = np.where(
            linear >= 0.000122,
            0.245281 * np.log10(5.555556 * linear + 0.009468) + 0.384316,
            8.799461 * linear + 0.092864,
        )
    elif profile == "s_log3":
        encoded = np.where(
            linear >= 0.01125,
            (420.0 + 261.5 * np.log10((linear + 0.01) / 0.19)) / 1023.0,
            (171.2102946929 - 95.0) / 0.01125 * linear / 1023.0 + 95.0 / 1023.0,
        )
    else:
        return source
    return np.clip(encoded, 0.0, 1.0)


def apply_cube(image: np.ndarray, lut: dict, strength: float = 1.0, input_profile: str = "display") -> np.ndarray:
    """Apply a RGB LUT with trilinear interpolation."""
    strength = max(0.0, min(1.0, float(strength)))
    if strength <= 0:
        return image
    source = image.astype(np.float32) / 255.0
    lut_source = _log_input(source, input_profile)
    minimum, maximum = lut["domain_min"], lut["domain_max"]
    coordinates = np.clip((lut_source - minimum) / np.maximum(maximum - minimum, 1e-6), 0, 1) * (lut["size"] - 1)
    low = np.floor(coordinates).astype(np.int32)
    high = np.minimum(low + 1, lut["size"] - 1)
    fraction = coordinates - low
    table = lut["table"]
    r0, g0, b0 = low[..., 0], low[..., 1], low[..., 2]
    r1, g1, b1 = high[..., 0], high[..., 1], high[..., 2]
    fr, fg, fb = fraction[..., 0:1], fraction[..., 1:2], fraction[..., 2:3]
    c000 = table[r0, g0, b0]
    c100 = table[r1, g0, b0]
    c010 = table[r0, g1, b0]
    c110 = table[r1, g1, b0]
    c001 = table[r0, g0, b1]
    c101 = table[r1, g0, b1]
    c011 = table[r0, g1, b1]
    c111 = table[r1, g1, b1]
    c00 = c000 * (1 - fr) + c100 * fr
    c10 = c010 * (1 - fr) + c110 * fr
    c01 = c001 * (1 - fr) + c101 * fr
    c11 = c011 * (1 - fr) + c111 * fr
    mapped = (c00 * (1 - fg) + c10 * fg) * (1 - fb) + (c01 * (1 - fg) + c11 * fg) * fb
    if input_profile in {"f_log2", "s_log3"}:
        # A display-referred HEIC is not a real camera-log negative. After
        # the approximate log adaptation, creative camera LUTs commonly land
        # too low in the mids. Match the LUT result's median luminance back to
        # the source and compress only the resulting highlight excess.
        weights = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
        source_mid = float(np.percentile(source @ weights, 50))
        mapped_mid = float(np.percentile(mapped @ weights, 50))
        if mapped_mid > 1e-4:
            mapped *= np.clip(source_mid / mapped_mid, 0.75, 2.2)
        excess = np.maximum(mapped.max(axis=2, keepdims=True) - 0.985, 0.0)
        mapped = mapped / (1.0 + 1.5 * excess)
    return np.clip(source * (1 - strength) + mapped * strength, 0, 1)
