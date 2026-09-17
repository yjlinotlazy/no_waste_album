"""Explainable, dependency-light personal photo quality heuristics."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

from PIL import Image


DETECTOR_VERSION = "hybrid-v2"
DEFAULT_THRESHOLD = 0.55


class QualityStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def save(self, asset_id: str, modified_ns: int, assessment: dict, job_id: str | None = None) -> None:
        with closing(sqlite3.connect(self.database_path)) as db, db:
            db.execute("""INSERT OR REPLACE INTO quality_assessments
                (asset_id, job_id, detector_version, modified_ns, badness_score,
                 threshold, is_bad, details_json)
                VALUES (?,?,?,?,?,?,?,?)""", (
                    asset_id, job_id or "legacy", assessment["detector_version"], modified_ns,
                    assessment["badness_score"], assessment["threshold"],
                    int(assessment["is_bad"]), json.dumps(assessment["details"]),
                ))

    def get(self, asset_id: str) -> dict | None:
        with closing(sqlite3.connect(self.database_path)) as db:
            row = db.execute("SELECT asset_id,detector_version,modified_ns,badness_score,threshold,is_bad,details_json FROM quality_assessments WHERE asset_id=?", (asset_id,)).fetchone()
        if not row:
            return None
        return {"asset_id": row[0], "detector_version": row[1], "modified_ns": row[2], "badness_score": row[3], "threshold": row[4], "is_bad": bool(row[5]), "details": json.loads(row[6])}


def _load_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            return source.convert("RGB")
    except (OSError, Image.UnidentifiedImageError):
        if path.suffix.casefold() not in {".heic", ".heif"} or not shutil.which("heif-convert"):
            raise
        with tempfile.TemporaryDirectory(prefix="no-waste-quality-") as directory:
            converted = Path(directory) / "preview.jpg"
            subprocess.run(["heif-convert", str(path), str(converted)], check=True, capture_output=True, timeout=120)
            with Image.open(converted) as source:
                return source.convert("RGB")


def assess(path: Path, threshold: float = DEFAULT_THRESHOLD) -> dict:
    image = _load_image(path)
    original_width, original_height = image.size
    image.thumbnail((512, 512))
    gray = image.convert("L")
    pixels = list(gray.getdata())
    total = max(1, len(pixels))
    mean = sum(pixels) / total / 255
    underexposed = sum(value <= 8 for value in pixels) / total
    overexposed = sum(value >= 247 for value in pixels) / total
    clipping = min(1.0, (underexposed + overexposed) / 0.25)
    exposure = min(1.0, max((0.14 - mean) / 0.14, (mean - 0.86) / 0.14, 0.0))
    width, height = gray.size
    horizontal = [abs(pixels[index] - pixels[index - 1]) for index in range(1, total) if index % width]
    vertical = [abs(pixels[index] - pixels[index - width]) for index in range(width, total)]
    edge_strength = (sum(horizontal) + sum(vertical)) / max(1, len(horizontal) + len(vertical)) / 255
    blur = max(0.0, min(1.0, 1.0 - edge_strength / 0.12))
    resolution = max(0.0, min(1.0, 1.0 - (original_width * original_height) ** 0.5 / 1000))
    histogram = [0] * 32
    for value in pixels:
        histogram[min(31, value * 32 // 256)] += 1
    entropy = -sum((count / total) * __import__("math").log2(count / total) for count in histogram if count) / 5
    quantized_colors = {(r // 32, g // 32, b // 32) for r, g, b in image.getdata()}
    color_diversity = min(1.0, len(quantized_colors) / 128)
    edge_density = sum(value >= 20 for value in horizontal + vertical) / max(1, len(horizontal) + len(vertical))
    edge_information = min(1.0, edge_density / 0.15)
    information = max(0.0, min(1.0, 0.45 * edge_information + 0.35 * entropy + 0.2 * color_diversity))
    low_information = 1.0 - information
    hard_reasons = []
    if blur >= 0.8:
        hard_reasons.append("blur")
    if resolution >= 0.6:
        hard_reasons.append("resolution")
    # Hard failures are represented as 1.0 so retagging with any normal
    # threshold cannot accidentally clear them.
    badness = round(max(1.0 if hard_reasons else 0.0, low_information), 4)
    details = {
        "blur": round(blur, 4),
        "exposure": round(exposure, 4),
        "clipping": round(clipping, 4),
        "resolution": round(resolution, 4),
        "edge_strength": round(edge_strength, 4),
        "edge_density": round(edge_density, 4),
        "entropy": round(entropy, 4),
        "color_diversity": round(color_diversity, 4),
        "information": round(information, 4),
        "low_information": round(low_information, 4),
        "hard_reasons": hard_reasons,
        "dimensions": [original_width, original_height],
    }
    reasons = hard_reasons + (["low_information"] if low_information >= 0.5 else [])
    return {"detector_version": DETECTOR_VERSION, "badness_score": badness, "threshold": threshold, "is_bad": badness >= threshold, "details": details, "reasons": reasons}
