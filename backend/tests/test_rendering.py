import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.rendering import Renderer


class RenderingTests(unittest.TestCase):
    def test_render_preserves_source_and_applies_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "photo.jpg"
            Image.new("RGB", (100, 80), (100, 120, 140)).save(source)
            destination = root / "exports" / "edit.jpg"
            Renderer(root).render("photo.jpg", {"crop": {"x": 0, "y": 0, "width": .5, "height": .5}}, destination)

            with Image.open(source) as original, Image.open(destination) as edited:
                self.assertEqual(original.size, (100, 80))
                self.assertEqual(edited.size, (50, 40))

    def test_raw_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw" / "photo.jpg"
            raw.parent.mkdir(); Image.new("RGB", (10, 10)).save(raw)
            with self.assertRaises(ValueError):
                Renderer(root).render("raw/photo.jpg", {}, root / "out.jpg")

    def test_kindle_filter_writes_16_level_grayscale_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (32, 16), (123, 87, 42)).save(root / "photo.jpg")
            destination = root / "kindle" / "photo_16gray.png"
            Renderer(root).render("photo.jpg", {"filter": "kindle_16gray"}, destination)
            with Image.open(destination) as edited:
                self.assertEqual(edited.format, "PNG")
                self.assertEqual(edited.mode, "L")
                self.assertEqual(edited.size, (600, 300))
                values = set(edited.getdata())
                self.assertLessEqual(len(values), 16)
                self.assertTrue(all(value % 17 == 0 for value in values))

    def test_shadow_recovery_changes_dark_tones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (2, 1), (24, 30, 36)).save(root / "photo.jpg")
            destination = root / "shadow.jpg"
            Renderer(root).render("photo.jpg", {"filter": "shadow_recovery"}, destination)
            with Image.open(destination) as edited:
                self.assertGreater(sum(edited.getpixel((0, 0))), 24 + 30 + 36)

    def test_local_clahe_writes_an_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (32, 24), (35, 40, 45)).save(root / "photo.jpg")
            destination = root / "clahe.jpg"
            Renderer(root).render("photo.jpg", {"filter": "local_clahe"}, destination)
            with Image.open(destination) as edited:
                self.assertEqual(edited.size, (32, 24))
                self.assertEqual(edited.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
