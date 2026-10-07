import tempfile
import unittest
from pathlib import Path

from PIL import Image
import numpy as np

from backend.rendering import Renderer
from backend.luts import apply_cube, category, display_name, load_cube
from backend.recipes import normalize


class RenderingTests(unittest.TestCase):
    def test_cube_display_name_uses_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "550e8400-e29b-41d4-a716-446655440000.cube"
            lut_path.write_text('TITLE "Soft Portrait"\n', encoding="utf-8")
            self.assertEqual(display_name(lut_path), "Soft Portrait")

    def test_cube_display_name_uses_comment_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "550e8400-e29b-41d4-a716-446655440000.cube"
            lut_path.write_text("#title:FLog2C_to_Velvia\nLUT_3D_SIZE 2\n", encoding="utf-8")
            self.assertEqual(display_name(lut_path), "FLog2C_to_Velvia")

    def test_kodak_luts_have_their_own_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "IWLTBAP Aspen - Standard.cube"
            lut_path.write_text('TITLE "IWLTBAP Aspen (Rec.709)"\n', encoding="utf-8")
            self.assertEqual(category(lut_path), "kodak")

    def test_cube_parser_ignores_title_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "portrait.cube"
            lut_path.write_text('TITLE "Soft Portrait"\nLUT_3D_SIZE 2\n' + "\n".join("0 0 0" for _ in range(8)), encoding="utf-8")
            self.assertEqual(load_cube(lut_path)["size"], 2)

    def test_auto_wb_is_a_separate_node(self):
        recipe = normalize({"auto_wb": {"enabled": True, "temperature": 0.4}})
        self.assertEqual([node["type"] for node in recipe["nodes"]], ["auto_wb"])
        disabled = normalize({"auto_wb": {"enabled": True, "temperature": 0.4}, "nodes": [{"type": "auto_wb", "enabled": False}]})
        self.assertFalse(disabled["nodes"][0]["enabled"])

    def test_cube_uses_red_as_fastest_varying_axis(self):
        with tempfile.TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "axis.cube"
            rows = []
            for blue in (0, 1):
                for green in (0, 1):
                    for red in (0, 1):
                        rows.append(f"{red} {green} {blue}")
            lut_path.write_text("LUT_3D_SIZE 2\n" + "\n".join(rows), encoding="utf-8")
            result = apply_cube(np.asarray([[[255, 0, 0]]], dtype=np.uint8), load_cube(lut_path))
            self.assertTrue(np.allclose(result[0, 0], [1, 0, 0]))

    def test_cube_lut_parser_and_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "invert.cube"
            rows = []
            for blue in (0, 1):
                for green in (0, 1):
                    for red in (0, 1):
                        rows.append(f"{1-red} {1-green} {1-blue}")
            lut_path.write_text("LUT_3D_SIZE 2\n" + "\n".join(rows), encoding="utf-8")
            lut = load_cube(lut_path)
            result = apply_cube(np.asarray([[[64, 128, 192]]], dtype=np.uint8), lut)
            self.assertLess(result[0, 0, 0], .8)
            self.assertGreater(result[0, 0, 2], .1)
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

    def test_preview_render_downscales_before_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (1600, 1000), (100, 120, 140)).save(root / "photo.jpg")
            destination = root / "preview.jpg"
            Renderer(root).render("photo.jpg", {}, destination, max_size=400)
            with Image.open(destination) as preview:
                self.assertEqual(preview.size, (400, 250))

    def test_raw_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw" / "photo.jpg"
            raw.parent.mkdir(); Image.new("RGB", (10, 10)).save(raw)
            with self.assertRaises(ValueError):
                Renderer(root).render("raw/photo.jpg", {}, root / "out.jpg")

    def test_render_applies_exif_orientation_before_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "oriented.jpg"
            image = Image.new("RGB", (60, 40), (100, 120, 140))
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif.tobytes())
            destination = root / "oriented.png"
            Renderer(root).render("oriented.jpg", {}, destination)
            with Image.open(destination) as edited:
                self.assertEqual(edited.size, (40, 60))

    def test_rotation_crops_rotated_corners(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (100, 80), (255, 255, 255)).save(root / "photo.jpg")
            destination = root / "rotated.png"
            Renderer(root).render("photo.jpg", {"rotate": 10}, destination)
            with Image.open(destination) as edited:
                self.assertEqual(edited.size, (90, 65))
                self.assertTrue(all(min(edited.getpixel(point)) > 200 for point in ((0, 0), (89, 0), (0, 64), (89, 64))))

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
