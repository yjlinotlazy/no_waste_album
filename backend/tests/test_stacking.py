import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from backend.catalog import Catalog
from backend.stacking import group_assets, hamming_distance, phash


class TestStacking(unittest.TestCase):
    def test_similar_images_have_small_hash_distance(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.jpg"
            second = Path(directory) / "second.jpg"
            for path, offset in ((first, 0), (second, 2)):
                image = Image.new("RGB", (400, 300), "white")
                draw = ImageDraw.Draw(image)
                draw.rectangle((80 + offset, 70, 300 + offset, 240), fill="black")
                image.save(path)
            self.assertLessEqual(hamming_distance(phash(first), phash(second)), 8)

    def test_grouping_only_compares_adjacent_same_folder(self):
        class Asset:
            def __init__(self, asset_id, folder, modified_ns):
                self.id, self.folder, self.modified_ns = asset_id, folder, modified_ns

        assets = [Asset("1", "2024", 0), Asset("2", "2024", 60_000_000_000), Asset("3", "2025", 120_000_000_000)]
        groups = group_assets(assets, {"1": 1, "2": 1, "3": 1}, 15, 0)
        self.assertEqual([[asset.id for asset in group] for group in groups], [["1", "2"], ["3"]])

    def test_phash_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "2024" / "photo.jpg"
            image_path.parent.mkdir()
            Image.new("RGB", (40, 40), "white").save(image_path)
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("incremental")
            assets = catalog.assets_in_scope("2024")
            first, computed_first, skipped_first, errors_first = catalog.stack_phashes(assets, phash)
            second, computed_second, skipped_second, errors_second = catalog.stack_phashes(assets, phash)
            self.assertEqual(first, second)
            self.assertEqual(computed_first, 1)
            self.assertEqual(skipped_first, 0)
            self.assertEqual(computed_second, 0)
            self.assertEqual(skipped_second, 1)
            third, computed_third, skipped_third, errors_third = catalog.stack_phashes(assets, phash, clean_start=True)
            self.assertEqual(third, first)
            self.assertEqual(computed_third, 1)
            self.assertEqual(skipped_third, 0)
            self.assertEqual(errors_third, 0)
            self.assertEqual(errors_first, 0)
            self.assertEqual(errors_second, 0)


if __name__ == "__main__":
    unittest.main()
