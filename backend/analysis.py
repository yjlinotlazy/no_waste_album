"""Versioned, dependency-light image analysis and feature storage."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from PIL import Image, ImageStat

ANALYZER_VERSION = "basic-v1"


class FeatureStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS image_features (
                asset_id TEXT NOT NULL, analyzer_version TEXT NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL,
                average_color TEXT NOT NULL, brightness REAL NOT NULL,
                contrast REAL NOT NULL, sharpness REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(asset_id, analyzer_version)
            )""")

    def save(self, asset_id: str, features: dict) -> None:
        with closing(sqlite3.connect(self.database_path)) as db, db:
            db.execute("""INSERT OR REPLACE INTO image_features
                (asset_id, analyzer_version, width, height, average_color,
                 brightness, contrast, sharpness)
                VALUES (?,?,?,?,?,?,?,?)""", (asset_id, features["analyzer_version"], features["width"], features["height"], json.dumps(features["average_color"]), features["brightness"], features["contrast"], features["sharpness"]))

    def get(self, asset_id: str, version: str = ANALYZER_VERSION) -> dict | None:
        with closing(sqlite3.connect(self.database_path)) as db:
            row = db.execute("SELECT asset_id,analyzer_version,width,height,average_color,brightness,contrast,sharpness FROM image_features WHERE asset_id=? AND analyzer_version=?", (asset_id, version)).fetchone()
        if not row: return None
        return {"asset_id": row[0], "analyzer_version": row[1], "width": row[2], "height": row[3], "average_color": json.loads(row[4]), "brightness": row[5], "contrast": row[6], "sharpness": row[7]}


def analyze(path: Path) -> dict:
    with Image.open(path) as source:
        image = source.convert("RGB")
    # A small working copy keeps analysis bounded for very large photos.
    image.thumbnail((256, 256))
    stat = ImageStat.Stat(image)
    channels = stat.mean
    brightness = sum(channels) / (3 * 255)
    contrast = sum(stat.rms[i] - channels[i] for i in range(3)) / (3 * 255)
    pixels = list(image.convert("L").tobytes())
    width, height = image.size
    horizontal = [abs(pixels[i] - pixels[i - 1]) for i in range(1, len(pixels)) if i % width]
    sharpness = sum(horizontal) / max(1, len(horizontal)) / 255
    return {"analyzer_version": ANALYZER_VERSION, "width": width, "height": height, "average_color": [round(value) for value in channels], "brightness": round(brightness, 4), "contrast": round(contrast, 4), "sharpness": round(sharpness, 4)}
