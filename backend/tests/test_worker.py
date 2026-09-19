import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.catalog import Catalog
from backend.jobs import JobStore
from backend.worker import Worker


class WorkerTests(unittest.TestCase):
    def test_worker_executes_catalog_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photo.jpg").write_bytes(b"photo")
            catalog = Catalog(root, root / "catalog.sqlite")
            jobs = JobStore(root / "jobs.sqlite")
            job = jobs.create("catalog_scan", {"kind": "full"})

            result = Worker(jobs, catalog).run_once()

            self.assertEqual(result["id"], job["id"])
            self.assertEqual(result["state"], "completed")
            self.assertEqual(catalog.page()[1], 1)

    def test_worker_marks_unimplemented_pipeline_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = Catalog(root, root / "catalog.sqlite")
            jobs = JobStore(root / "jobs.sqlite")
            jobs.create("clustering")

            result = Worker(jobs, catalog).run_once()

            self.assertEqual(result["state"], "failed")
            self.assertIn("not implemented", result["error"])

    def test_worker_runs_quality_detection_with_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album" / "child").mkdir(parents=True)
            Image.new("RGB", (100, 100), (0, 0, 0)).save(root / "album" / "bad.jpg")
            Image.effect_noise((1000, 1000), 80).convert("RGB").save(root / "album" / "child" / "good.jpg")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            jobs = JobStore(root / "jobs.sqlite")
            job = jobs.create("quality_detection", {"folder": "album", "threshold": 0.55})

            result = Worker(jobs, catalog).run_once()

            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["result"]["analyzed"], 2)
            self.assertEqual(result["result"]["bad_images"], 1)
            self.assertEqual(jobs.get(job["id"])["progress"], 100)
            self.assertEqual(jobs.get(job["id"])["progress_detail"]["images_scanned"], 2)
            quality_results, quality_total = catalog.quality_results(job["id"], "album", threshold=0.55)
            self.assertEqual(quality_total, 2)
            self.assertEqual(sum(result["is_bad"] for result in quality_results), 1)
            self.assertEqual(catalog.page(folder="album", tag="bad_quality")[1], 0)
            self.assertEqual(catalog.apply_quality_tags(job["id"], "album", 0.55), 1)
            bad_assets, bad_total = catalog.page(folder="album", tag="bad_quality")
            self.assertEqual(bad_total, 1)
            self.assertEqual(bad_assets[0].name, "bad.jpg")

    def test_worker_creates_auto_variants_for_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album").mkdir()
            Image.new("RGB", (80, 60), (35, 42, 50)).save(root / "album" / "photo.jpg")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            jobs = JobStore(root / "jobs.sqlite")
            job = jobs.create("auto_develop", {"folder": "album"})

            result = Worker(jobs, catalog).run_once()

            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["result"]["variants_created"], 1)
            asset = catalog.assets_in_scope("album")[0]
            variants = catalog.variants(asset.id)
            self.assertEqual(variants[0]["name"], "auto")
            self.assertEqual(variants[0]["source_job_id"], job["id"])
            self.assertEqual(catalog.delete_auto_variants("album", job["id"]), 1)
            self.assertEqual(catalog.variants(asset.id), [])

    def test_worker_runs_stack_generation_and_caches_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album").mkdir()
            for index in range(3):
                Image.new("RGB", (160, 120), (40 + index, 40, 40)).save(root / "album" / f"2024-01-01 10.0{index}.jpg")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            jobs = JobStore(root / "jobs.sqlite")
            job = jobs.create("stack_generation", {"folder": "album", "max_gap_minutes": 15, "max_phash_distance": 8})

            result = Worker(jobs, catalog).run_once()

            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["result"]["images"], 3)
            self.assertEqual(result["result"]["stacks"], 1)
            stacks, total = catalog.stack_results("album")
            self.assertEqual(total, 1)
            self.assertEqual(stacks[0]["member_count"], 3)

    def test_stack_generation_replaces_previous_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album").mkdir()
            Image.new("RGB", (160, 120), "black").save(root / "album" / "first.jpg")
            Image.new("RGB", (160, 120), "white").save(root / "album" / "second.jpg")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            jobs = JobStore(root / "jobs.sqlite")
            first = jobs.create("stack_generation", {"folder": "album", "max_gap_minutes": 15, "max_phash_distance": 0})
            second = jobs.create("stack_generation", {"folder": "album", "max_gap_minutes": 15, "max_phash_distance": 63})

            first_result = Worker(jobs, catalog).run_once()
            second_result = Worker(jobs, catalog).run_once()

            self.assertEqual(first_result["state"], "completed")
            self.assertEqual(second_result["state"], "completed")
            self.assertEqual(catalog.stack_results("album")[1], 1)

    def test_stack_results_are_ranked_by_member_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album").mkdir()
            for name in ("first.jpg", "second.jpg", "third.jpg"):
                Image.new("RGB", (40, 40), "black").save(root / "album" / name)
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            assets = catalog.assets_in_scope("album")

            catalog.replace_stack_generation("album", {}, [[assets[0]], [assets[1], assets[2]]])

            results, total = catalog.stack_results("album")
            self.assertEqual(total, 2)
            self.assertEqual([result["member_count"] for result in results], [2, 1])

    def test_worker_generates_and_reuses_thumbnails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album").mkdir()
            Image.new("RGB", (800, 600), "red").save(root / "album" / "photo.jpg")
            catalog = Catalog(root, root / "catalog.sqlite")
            catalog.scan("full")
            jobs = JobStore(root / "jobs.sqlite")

            first = jobs.create("thumbnail_generation", {"folder": "album", "thumbnail_size": 256, "thumbnail_quality": 88})
            first_result = Worker(jobs, catalog).run_once()
            second = jobs.create("thumbnail_generation", {"folder": "album", "thumbnail_size": 256, "thumbnail_quality": 88})
            second_result = Worker(jobs, catalog).run_once()

            self.assertEqual(first_result["state"], "completed")
            self.assertEqual(first_result["result"]["thumbnails_created"], 1)
            self.assertEqual(second_result["state"], "completed")
            self.assertEqual(second_result["result"]["thumbnails_skipped"], 1)

            clean = jobs.create("thumbnail_generation", {"folder": "album", "thumbnail_size": 256, "thumbnail_quality": 88, "clean_start": True})
            clean_result = Worker(jobs, catalog).run_once()
            self.assertEqual(clean_result["state"], "completed")
            self.assertEqual(clean_result["result"]["thumbnails_created"], 1)
            self.assertTrue((root / "thumbnails").exists())


if __name__ == "__main__":
    unittest.main()
