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
