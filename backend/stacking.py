"""Fast adjacent-image stacking using thumbnail perceptual hashes."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from .quality import _load_image


def phash(path: Path, size: int = 32) -> int:
    """Return a 64-bit pHash for a small, oriented grayscale thumbnail."""
    image = ImageOps.exif_transpose(_load_image(path)).convert("L")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    pixels = np.asarray(canvas, dtype=np.float32)
    coefficients = cv2.dct(pixels)[:8, :8]
    values = coefficients.flatten()[1:]
    median = float(np.median(values))
    result = 0
    for value in values:
        result = (result << 1) | int(value > median)
    return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def group_assets(assets, hashes: dict[str, int], max_gap_minutes: float, max_distance: int):
    """Group adjacent assets; comparisons never cross folder boundaries."""
    groups = UnionFind(len(assets))
    for index in range(1, len(assets)):
        previous, current = assets[index - 1], assets[index]
        if previous.folder != current.folder:
            continue
        gap_minutes = (current.modified_ns - previous.modified_ns) / 60_000_000_000
        if gap_minutes < 0 or gap_minutes > max_gap_minutes:
            continue
        if hamming_distance(hashes[previous.id], hashes[current.id]) <= max_distance:
            groups.union(index - 1, index)
    grouped: dict[int, list] = {}
    for index, asset in enumerate(assets):
        grouped.setdefault(groups.find(index), []).append(asset)
    return [grouped[key] for key in sorted(grouped)]


def generation_config(scope: str, max_gap_minutes: float, max_distance: int) -> dict:
    return {
        "scope": scope,
        "max_gap_minutes": max_gap_minutes,
        "max_phash_distance": max_distance,
        "hash": "phash64-v1",
    }
