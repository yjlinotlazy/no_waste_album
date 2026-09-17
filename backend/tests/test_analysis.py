import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.analysis import FeatureStore, analyze


class AnalysisTests(unittest.TestCase):
    def test_basic_features_are_versioned_and_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.png"
            Image.new("RGB", (100, 80), (100, 120, 140)).save(image)
            features = analyze(image)
            store = FeatureStore(root / "features.sqlite")
            store.save("asset-1", features)

            self.assertEqual(features["analyzer_version"], "basic-v1")
            self.assertEqual(store.get("asset-1")["width"], 100)
            self.assertEqual(store.get("asset-1")["average_color"], [100, 120, 140])


if __name__ == "__main__":
    unittest.main()
