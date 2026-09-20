"""Local worker for persisted background jobs."""

import argparse
import time
import uuid

from .catalog import Catalog
from .config import load
from .jobs import JobStore
from .analysis import FeatureStore, analyze
from .quality import DEFAULT_THRESHOLD, QualityStore, assess
from .autodevelop import estimate
from .stacking import group_assets, generation_config, phash
from .thumbnails import THUMBNAIL_VERSION, render as render_thumbnail


class Worker:
    def __init__(self, jobs: JobStore, catalog: Catalog, features: FeatureStore | None = None):
        self.jobs = jobs
        self.catalog = catalog
        self.features = features or FeatureStore(catalog.database_path.parent / "features.sqlite")
        self.quality = QualityStore(catalog.database_path)

    def run_once(self) -> dict | None:
        job = self.jobs.claim_next()
        if not job:
            return None
        return self.run_job(job)

    def run_job(self, job: dict) -> dict:
        if job["state"] == "queued":
            job = self.jobs.transition(job["id"], "running")
        try:
            if job["type"] == "analysis":
                assets, _ = self.catalog.page(page=1, page_size=200)
                requested = set(job["scope"].get("asset_ids", []))
                if requested: assets = [asset for asset in assets if asset.id in requested]
                for asset in assets:
                    self.features.save(asset.id, analyze(self.catalog.root / asset.relative_path))
                result = {"analyzed": len(assets)}
            elif job["type"] == "quality_detection":
                folder = job["scope"].get("folder", "")
                threshold = float(job["scope"].get("threshold", DEFAULT_THRESHOLD))
                assets = self.catalog.assets_in_scope(folder)
                total = len(assets)
                bad = 0
                errors = 0
                self.jobs.update_progress(job["id"], 0, {"folder": folder, "images_scanned": 0, "images_total": total, "bad_images": 0, "errors": 0})
                for index, asset in enumerate(assets, 1):
                    current = self.jobs.get(job["id"])
                    if current["state"] == "cancelled":
                        return current
                    try:
                        assessment = assess(self.catalog.root / asset.relative_path, threshold)
                        self.quality.save(asset.id, asset.modified_ns, assessment, job["id"])
                        bad += int(assessment["is_bad"])
                    except Exception:
                        errors += 1
                    self.jobs.update_progress(job["id"], round(index / max(1, total) * 100), {"folder": folder, "images_scanned": index, "images_total": total, "bad_images": bad, "errors": errors})
                result = {"folder": folder, "analyzed": total - errors, "bad_images": bad, "errors": errors}
            elif job["type"] == "auto_develop":
                folder = job["scope"].get("folder", "")
                assets = self.catalog.assets_in_scope(folder)
                total = len(assets)
                created = 0
                errors = 0
                self.jobs.update_progress(job["id"], 0, {"folder": folder, "images_scanned": 0, "images_total": total, "variants_created": 0, "errors": 0})
                for index, asset in enumerate(assets, 1):
                    current = self.jobs.get(job["id"])
                    if current["state"] == "cancelled":
                        return current
                    try:
                        recipe = estimate(self.catalog.root / asset.relative_path)
                        recipe.update({"filter": "auto_develop", "name": "auto", "source_job_id": job["id"], "adjustments": {"brightness": 0, "contrast": 0, "saturation": 0, "temperature": recipe["temperature"]}})
                        self.catalog.add_variant(asset.id, {"id": uuid.uuid4().hex, **recipe})
                        created += 1
                    except Exception:
                        errors += 1
                    self.jobs.update_progress(job["id"], round(index / max(1, total) * 100), {"folder": folder, "images_scanned": index, "images_total": total, "variants_created": created, "errors": errors})
                result = {"folder": folder, "analyzed": total - errors, "variants_created": created, "errors": errors}
            elif job["type"] == "thumbnail_generation":
                folder = job["scope"].get("folder", "")
                size = int(job["scope"].get("thumbnail_size", 256))
                quality = int(job["scope"].get("thumbnail_quality", 88))
                clean_start = bool(job["scope"].get("clean_start", False))
                assets = self.catalog.assets_in_scope(folder)
                total = len(assets)
                created = 0
                skipped = 0
                errors = 0
                thumbnail_dir = self.catalog.database_path.parent / "thumbnails"
                self.jobs.update_progress(job["id"], 0, {"folder": folder, "images_scanned": 0, "images_total": total, "thumbnails_created": 0, "thumbnails_skipped": 0, "errors": 0})
                for index, asset in enumerate(assets, 1):
                    current = self.jobs.get(job["id"])
                    if current["state"] == "cancelled":
                        return current
                    try:
                        target = thumbnail_dir / f"{asset.id}.jpg"
                        fingerprint = self.catalog.content_fingerprint(asset.id)
                        record = self.catalog.thumbnail_record(asset.id)
                        if not clean_start and record and record[0] == fingerprint and record[1] == f"thumbnails/{asset.id}.jpg" and record[4] == THUMBNAIL_VERSION and target.is_file():
                            skipped += 1
                        else:
                            width, height = render_thumbnail(self.catalog.root / asset.relative_path, target, size, quality)
                            self.catalog.save_thumbnail_record(asset.id, fingerprint, f"thumbnails/{asset.id}.jpg", width, height, THUMBNAIL_VERSION)
                            created += 1
                    except Exception:
                        errors += 1
                    self.jobs.update_progress(job["id"], round(index / max(1, total) * 100), {"folder": folder, "images_scanned": index, "images_total": total, "thumbnails_created": created, "thumbnails_skipped": skipped, "errors": errors})
                result = {"folder": folder, "analyzed": total - errors, "thumbnails_created": created, "thumbnails_skipped": skipped, "errors": errors}
            elif job["type"] == "stack_generation":
                folder = job["scope"].get("folder", "")
                max_gap = float(job["scope"].get("max_gap_minutes", 15))
                max_distance = int(job["scope"].get("max_phash_distance", 20))
                clean_start = bool(job["scope"].get("clean_start", False))
                assets = self.catalog.assets_in_scope(folder)
                total = len(assets)
                self.jobs.update_progress(job["id"], 0, {"folder": folder, "stage": "hashing", "stage_processed": 0, "stage_total": total, "max_gap_minutes": max_gap, "max_phash_distance": max_distance, "clean_start": clean_start, "images_total": total, "images_hashed": 0, "hashes_computed": 0, "hashes_skipped": 0, "stacks": 0, "errors": 0})
                def report_hash_progress(index, image_total, hashed, hashes_computed, hashes_skipped, hash_errors):
                    if index == image_total or index % 10 == 0:
                        self.jobs.update_progress(job["id"], round(index / max(1, image_total) * 70), {"folder": folder, "stage": "hashing", "stage_processed": index, "stage_total": image_total, "max_gap_minutes": max_gap, "max_phash_distance": max_distance, "clean_start": clean_start, "images_total": image_total, "images_hashed": hashed, "hashes_computed": hashes_computed, "hashes_skipped": hashes_skipped, "stacks": 0, "errors": hash_errors})

                try:
                    hashes, computed, skipped, hash_errors = self.catalog.stack_phashes(assets, phash, report_hash_progress, clean_start=clean_start)
                    usable = [asset for asset in assets if asset.id in hashes]
                    errors = hash_errors
                except Exception:
                    hashes, usable, computed, skipped = {}, [], 0, 0
                    errors = total
                self.jobs.update_progress(job["id"], 70, {"folder": folder, "stage": "grouping", "stage_processed": 0, "stage_total": 1, "max_gap_minutes": max_gap, "max_phash_distance": max_distance, "clean_start": clean_start, "images_total": total, "images_hashed": len(usable), "hashes_computed": computed, "hashes_skipped": skipped, "stacks": 0, "errors": errors})
                groups = group_assets(usable, hashes, max_gap, max_distance)
                config = generation_config(folder, max_gap, max_distance)
                self.jobs.update_progress(job["id"], 85, {"folder": folder, "stage": "storing", "stage_processed": 0, "stage_total": 1, "max_gap_minutes": max_gap, "max_phash_distance": max_distance, "clean_start": clean_start, "images_total": total, "images_hashed": len(usable), "hashes_computed": computed, "hashes_skipped": skipped, "stacks": len(groups), "errors": errors})
                stored = self.catalog.replace_stack_generation(folder, config, groups)
                self.jobs.update_progress(job["id"], 100, {"folder": folder, "stage": "storing", "stage_processed": 1, "stage_total": 1, "max_gap_minutes": max_gap, "max_phash_distance": max_distance, "clean_start": clean_start, "images_total": total, "images_hashed": len(usable), "hashes_computed": computed, "hashes_skipped": skipped, "stacks": len(groups), "errors": errors})
                result = {"folder": folder, "max_gap_minutes": max_gap, "max_phash_distance": max_distance, "images": len(usable), "stacks": len(groups), "errors": errors, **stored}
            elif job["type"] == "catalog_scan":
                result = self.catalog.scan(job["scope"].get("kind", "incremental"), lambda detail: self.jobs.update_progress(job["id"], detail["percent"], detail))
            else:
                raise RuntimeError(f"worker for {job['type']} is not implemented")
            return self.jobs.transition(job["id"], "completed") | {"result": result}
        except Exception as error:
            return self.jobs.transition(job["id"], "failed", str(error))


def main():
    parser = argparse.ArgumentParser(description="No Waste Album local job worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    config = load()
    data_dir = config.data_dir
    worker = Worker(JobStore(data_dir / "jobs.sqlite"), Catalog(config.library, data_dir / "catalog.sqlite"))
    while True:
        result = worker.run_once()
        if result: print(result)
        if args.once: break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
