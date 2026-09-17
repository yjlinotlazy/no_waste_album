import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.catalog import Catalog
from backend.quality import QualityStore, assess


class QualityTests(unittest.TestCase):
    def test_assessment_is_versioned_and_explainable(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "dark.jpg"
            Image.new("RGB", (100, 100), (0, 0, 0)).save(image)

            result = assess(image)

            self.assertEqual(result["detector_version"], "hybrid-v2")
            self.assertGreater(result["badness_score"], 0.55)
            self.assertTrue(result["is_bad"])
            self.assertIn("resolution", result["reasons"])

    def test_quality_result_is_removed_with_catalog_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            Image.new("RGB", (100, 100), (0, 0, 0)).save(image)
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            store = QualityStore(root / "catalog.sqlite")
            store.save(asset.id, asset.modified_ns, assess(image))

            catalog.bulk_update([asset.id], "trash")
            catalog.clear_trash()

            self.assertIsNone(store.get(asset.id))


if __name__ == "__main__":
    unittest.main()
