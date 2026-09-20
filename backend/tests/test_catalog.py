import tempfile
import unittest
import os
import sqlite3
from pathlib import Path

from backend.catalog import Catalog
from backend.analysis import FeatureStore


class CatalogTests(unittest.TestCase):
    def test_raw_trees_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026").mkdir()
            (root / "2026" / "photo.jpg").write_bytes(b"photo")
            (root / "raw" / "nested").mkdir(parents=True)
            (root / "raw" / "nested" / "source.jpg").write_bytes(b"raw")
            catalog = Catalog(root, root / "data" / "catalog.sqlite")

            result = catalog.scan("full")
            assets, total = catalog.page(page_size=50)

            self.assertEqual(result["seen"], 1)
            self.assertEqual(total, 1)
            self.assertEqual(assets[0].relative_path, "2026/photo.jpg")

    def test_catalog_data_directory_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026" / "photo.jpg").parent.mkdir(parents=True)
            (root / "2026" / "photo.jpg").write_bytes(b"photo")
            data_dir = root / "no_waste_album"
            (data_dir / "thumbnails").mkdir(parents=True)
            (data_dir / "thumbnails" / "not-a-photo.jpg").write_bytes(b"thumbnail")
            catalog = Catalog(root, data_dir / "catalog.sqlite")

            result = catalog.scan("full")

            self.assertEqual(result["seen"], 1)
            self.assertEqual(catalog.page()[1], 1)

    def test_folder_counts_include_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026" / "trip").mkdir(parents=True)
            (root / "2026" / "other.jpg").write_bytes(b"other")
            (root / "2026" / "trip" / "photo.jpg").write_bytes(b"photo")
            (root / "raw" / "2026").mkdir(parents=True)
            (root / "raw" / "2026" / "ignored.jpg").write_bytes(b"ignored")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")

            self.assertEqual(catalog.folder_counts(), {"2026": 2, "2026/trip": 1})

    def test_current_variant_is_persisted_and_cleared_on_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("incremental")
            asset = catalog.page(page_size=1)[0][0]
            variant = {"id": "variant-1", "crop": {"x": 0, "y": 0, "width": 1, "height": 1}}
            catalog.add_variant(asset.id, variant)
            self.assertIsNone(catalog.current_variant_id(asset.id))
            catalog.set_current_variant(asset.id, "variant-1")
            self.assertEqual(catalog.current_variant_id(asset.id), "variant-1")
            catalog.delete_variant(asset.id, "variant-1")
            self.assertIsNone(catalog.current_variant_id(asset.id))

    def test_unchanged_files_are_not_rehashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")

            first = catalog.scan("incremental")
            second = catalog.scan("incremental")

            self.assertEqual(first["added"], 1)
            self.assertEqual(second["added"], 0)
            self.assertEqual(second["changed"], 0)

    def test_full_scan_marks_external_deletion_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            image.unlink()

            result = catalog.scan("full")

            self.assertEqual(result["missing"], 1)
            self.assertEqual(catalog.page()[1], 0)

    def test_scan_reports_image_and_folder_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "a.jpg").write_bytes(b"a")
            (root / "two" / "b.jpg").write_bytes(b"b")
            catalog = Catalog(root, root / "catalog.sqlite")
            updates = []

            catalog.scan("full", updates.append)

            self.assertEqual(updates[-1]["percent"], 100)
            self.assertEqual(updates[-1]["images_scanned"], 2)
            self.assertEqual(updates[-1]["folders_scanned"], 2)

    def test_hidden_assets_are_excluded_until_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photo.jpg").write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]

            self.assertEqual(catalog.bulk_update([asset.id], "hide"), 1)
            self.assertEqual(catalog.page()[1], 0)
            self.assertEqual(catalog.page(show_hidden=True)[1], 1)
            self.assertEqual(catalog.bulk_update([asset.id], "trash"), 1)
            self.assertEqual(catalog.page(show_hidden=True)[1], 0)

    def test_page_is_earliest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "older.jpg"
            newer = root / "newer.jpg"
            older.write_bytes(b"older")
            newer.write_bytes(b"newer")
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")

            assets, _ = catalog.page(page_size=5)

            self.assertEqual([asset.name for asset in assets], ["older.jpg", "newer.jpg"])

    def test_variant_insert_is_committed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photo.jpg").write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            catalog.add_variant(asset.id, {"id": "variant-1", "filter": "none"})

            self.assertEqual(catalog.variants(asset.id)[0]["id"], "variant-1")

    def test_clear_trash_deletes_the_original_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            catalog.bulk_update([asset.id], "trash")

            result = catalog.clear_trash()

            self.assertEqual(result["deleted"], 1)
            self.assertFalse(image.exists())
            self.assertEqual(catalog.page(show_hidden=True, include_trashed=True)[1], 0)

    def test_trash_timestamp_filters_recent_items_and_restore_clears_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            catalog.bulk_update([asset.id], "trash")

            self.assertEqual(catalog.page(include_trashed=True)[1], 1)
            self.assertEqual(catalog.page(include_trashed=True, trash_minutes=5)[1], 1)
            with sqlite3.connect(root / "catalog.sqlite") as db:
                db.execute("UPDATE catalog_assets SET trashed_at=datetime('now', '-10 minutes') WHERE id=?", (asset.id,))
                db.commit()

            self.assertEqual(catalog.page(include_trashed=True, trash_minutes=5)[1], 0)
            self.assertEqual(catalog.bulk_update([asset.id], "restore", trash_minutes=5), 0)
            self.assertEqual(catalog.bulk_update([asset.id], "restore"), 1)
            self.assertEqual(catalog.page()[1], 1)

    def test_clear_trash_deletes_thumbnail_file_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            thumbnail = root / "thumbnails" / f"{asset.id}.jpg"
            thumbnail.parent.mkdir()
            thumbnail.write_bytes(b"thumbnail")
            catalog.save_thumbnail_record(asset.id, catalog.content_fingerprint(asset.id), f"thumbnails/{asset.id}.jpg", 10, 10, "thumbnail-v1")
            catalog.bulk_update([asset.id], "trash")

            result = catalog.clear_trash()

            self.assertFalse(thumbnail.exists())
            self.assertIsNone(catalog.thumbnail_record(asset.id))
            self.assertEqual(result["thumbnails_deleted"], 1)

    def test_clear_trash_removes_orphan_thumbnail_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "thumbnails").mkdir()
            orphan = root / "thumbnails" / "orphan.jpg"
            orphan.write_bytes(b"thumbnail")
            catalog = Catalog(root, root / "catalog.sqlite")

            result = catalog.clear_trash()

            self.assertEqual(result["thumbnails_deleted"], 1)
            self.assertFalse(orphan.exists())

    def test_clear_trash_removes_separate_feature_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            FeatureStore(root / "features.sqlite").save(asset.id, {"analyzer_version": "basic-v1", "width": 1, "height": 1, "average_color": [0, 0, 0], "brightness": 0, "contrast": 0, "sharpness": 0})
            catalog.bulk_update([asset.id], "trash")

            catalog.clear_trash()

            self.assertIsNone(FeatureStore(root / "features.sqlite").get(asset.id))

    def test_trash_is_global_across_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("one", "two"):
                (root / folder).mkdir()
                (root / folder / "photo.jpg").write_bytes(folder.encode())
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            assets, _ = catalog.page(page_size=50)
            catalog.bulk_update([asset.id for asset in assets], "trash")

            trashed, total = catalog.page(folder="", page_size=50, include_trashed=True)

            self.assertEqual(total, 2)
            self.assertEqual({asset.folder for asset in trashed}, {"one", "two"})

    def test_trash_includes_assets_that_were_hidden_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            catalog.bulk_update([asset.id], "hide")
            catalog.bulk_update([asset.id], "trash")

            _, total = catalog.page(include_trashed=True)

            self.assertEqual(total, 1)

    def test_tags_filter_assets_and_cascade_on_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.jpg").write_bytes(b"one")
            (root / "two.jpg").write_bytes(b"two")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            assets, _ = catalog.page(page_size=50)
            catalog.set_tag(assets[0].id, "bad_quality", "quality_detection")

            filtered, total = catalog.page(tag="bad_quality")

            self.assertEqual(total, 1)
            self.assertEqual(filtered[0].id, assets[0].id)
            self.assertEqual(catalog.tags(), [{"name": "bad_quality", "count": 1}])
            catalog.bulk_update([assets[0].id], "trash")
            catalog.clear_trash()
            self.assertEqual(catalog.tags(), [])

    def test_rescan_does_not_resurrect_trashed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.jpg"
            image.write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            asset = catalog.page()[0][0]
            catalog.bulk_update([asset.id], "trash")

            catalog.scan("full")

            available, _ = catalog.page()
            trashed, total = catalog.page(include_trashed=True)
            self.assertEqual(available, [])
            self.assertEqual(total, 1)
            self.assertEqual(trashed[0].id, asset.id)


if __name__ == "__main__":
    unittest.main()
