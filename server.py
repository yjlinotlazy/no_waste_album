#!/usr/bin/env python3
"""Dependency-free local POC server for No Waste Album."""

import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from backend.catalog import Catalog
from backend.domain import MetadataService
from backend.rendering import Renderer
from backend.jobs import JobStore
from backend.worker import Worker
from backend.recipes import normalize
from server_logging import CountingWriter, RequestLogger


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic", ".heif"}
MODE_HEADER = "X-App-Mode"


class Library:
    def __init__(self, root: Path, data_dir: Path):
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.catalog = Catalog(self.root, self.data_dir / "catalog.sqlite")
        self.metadata = MetadataService(self.catalog)
        self._migrate_legacy_recipes()
        self.renderer = Renderer(self.root)
        self.jobs = JobStore(self.data_dir / "jobs.sqlite")
        self.preview_dir = self.data_dir / "previews"
        self.preview_lock = threading.Lock()
        self.scan_state = "pending"
        self.scan_result = None

    def _migrate_legacy_recipes(self):
        legacy_path = self.data_dir / "recipes.json"
        if not legacy_path.is_file():
            return
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for legacy_asset_id, recipes in legacy.items():
            asset_id = self.catalog.asset_id_by_legacy_prefix(legacy_asset_id)
            if not asset_id or not isinstance(recipes, list):
                continue
            existing = {variant["id"] for variant in self.catalog.variants(asset_id)}
            for recipe in recipes:
                if not isinstance(recipe, dict):
                    continue
                variant_id = str(recipe.get("id", ""))
                if not variant_id or variant_id in existing:
                    continue
                try:
                    normalized = normalize(recipe)
                except ValueError:
                    continue
                normalized["id"] = variant_id
                self.catalog.add_variant(asset_id, normalized)
                existing.add(variant_id)

    def start_initial_scan(self):
        def scan():
            self.scan_state = "scanning"
            try:
                self.scan_result = self.catalog.scan("incremental")
                self.scan_state = "ready"
            except Exception as error:
                self.scan_result = {"error": str(error)}
                self.scan_state = "failed"
        threading.Thread(target=scan, name="catalog-initial-scan", daemon=True).start()

    def start_full_scan_job(self):
        job = self.jobs.create("catalog_scan", {"kind": "full"})
        self.start_job(job)
        return job

    def start_job(self, job):
        def run():
            Worker(self.jobs, self.catalog).run_job(job)
        threading.Thread(target=run, name=f"job-{job['id']}", daemon=True).start()

    def folders(self):
        return self.catalog.folders()

    def refresh(self):
        return self.catalog.scan("full")

    def page(self, folder, query, page, page_size, show_hidden=False, tag=""):
        with self.lock:
            self._migrate_legacy_recipes()
        assets, total = self.catalog.page(folder, query, page, page_size, show_hidden, tag=tag)
        return [{"id": a.id, "name": a.name, "path": a.relative_path, "folder": a.folder, "size": a.size, "modified": a.modified_ns / 1_000_000_000, "url": "/media/" + a.relative_path, "hidden": bool(a.hidden), "tags": self.catalog.tags_for_asset(a.id), "recipes": self.catalog.variants(a.id)} for a in assets], total

    def trash_page(self, page, page_size):
        assets, total = self.catalog.page(folder="", page=page, page_size=page_size, include_trashed=True)
        return [{"id": a.id, "name": a.name, "path": a.relative_path, "folder": a.folder, "size": a.size, "modified": a.modified_ns / 1_000_000_000, "url": "/media/" + a.relative_path, "hidden": bool(a.hidden), "tags": self.catalog.tags_for_asset(a.id), "recipes": self.catalog.variants(a.id)} for a in assets], total

    def asset_by_id(self, asset_id):
        asset = self.catalog.get(asset_id)
        if not asset: return None
        return {"id": asset.id, "name": asset.name, "path": asset.relative_path, "folder": asset.folder, "size": asset.size, "modified": asset.modified_ns / 1_000_000_000, "url": "/media/" + asset.relative_path, "hidden": bool(asset.hidden), "tags": self.catalog.tags_for_asset(asset.id), "recipes": self.catalog.variants(asset.id)}

    def source_path(self, asset_id):
        asset = self.catalog.get(asset_id)
        if not asset or asset.status != "available": return None
        return asset.relative_path

    def media_path(self, relative_path):
        path = safe_media_path(self, relative_path)
        if not path or path.suffix.casefold() not in {".heic", ".heif"}:
            return path
        # Some phone/photo tools leave JPEG bytes with a .heic extension.
        # Serve those bytes directly instead of sending them to an HEIF decoder.
        with path.open("rb") as source:
            if source.read(2) == b"\xff\xd8":
                return path
        if not shutil.which("heif-convert"):
            return None
        stat = path.stat()
        cache_key = hashlib.sha256(f"{relative_path}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")).hexdigest()
        target = self.preview_dir / f"{cache_key}.jpg"
        if target.is_file():
            return target
        with self.preview_lock:
            if target.is_file():
                return target
            self.preview_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.preview_dir / f".{cache_key}.tmp.jpg"
            try:
                subprocess.run(["heif-convert", str(path), str(temporary)], check=True, capture_output=True, timeout=120)
                temporary.replace(target)
            except (OSError, subprocess.SubprocessError):
                temporary.unlink(missing_ok=True)
                return None
        return target


def safe_media_path(library, relative):
    if any(part.casefold() == "raw" for part in Path(unquote(relative)).parts):
        return None
    path = (library.root / unquote(relative)).resolve()
    if path != library.root and library.root not in path.parents:
        return None
    return path if path.is_file() else None


def load_config(path):
    """Read the small scalar YAML subset needed by the dependency-free POC."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise SystemExit("Missing config: %s" % path)
    config = {}
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        config[key.strip()] = value.strip().strip("'\"")
    return config


def save_config(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"library: {config['library']}",
        f"data_dir: {config.get('data_dir', str(Path(config['library']).expanduser() / 'no_waste_album'))}",
        f"host: {config.get('host', '127.0.0.1')}",
        f"port: {config.get('port', '7008')}",
        f"page_size: {config.get('page_size', '5')}",
        f"dev_reload: {config.get('dev_reload', 'true')}",
        f"kindle_gen7_output: {config.get('kindle_gen7_output', '')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def source_mtimes():
    files = [Path(__file__)]
    for root, directories, names in os.walk(Path(__file__).parent):
        directories[:] = [name for name in directories if name.casefold() != "raw"]
        files.extend(Path(root) / name for name in names if Path(name).suffix.casefold() in {".py", ".html", ".js", ".css", ".yaml"})
    return {str(path): path.stat().st_mtime_ns for path in files if path.is_file()}


def run_dev_reloader():
    environment = os.environ.copy()
    environment["NWA_RELOADED_CHILD"] = "1"
    print("No Waste Album: development hot reload enabled", flush=True)
    child = subprocess.Popen([sys.executable, "-u", __file__], env=environment)
    snapshot = source_mtimes()
    try:
        while True:
            time.sleep(0.4)
            current = source_mtimes()
            if child.poll() is not None:
                print(f"No Waste Album: server child exited with code {child.returncode}; waiting for a file change", flush=True)
                snapshot = current
            if current != snapshot:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)
                print("No Waste Album: source change detected; restarting server", flush=True)
                child = subprocess.Popen([sys.executable, "-u", __file__], env=environment)
                snapshot = current
    except KeyboardInterrupt:
        child.terminate()
        child.wait(timeout=5)


class Handler(BaseHTTPRequestHandler):
    library = None
    config_path = None
    config = None
    web_root = Path(__file__).parent / "web"
    request_logger = RequestLogger(Path(__file__).parent)
    _telemetry_status = HTTPStatus.INTERNAL_SERVER_ERROR

    def handle_one_request(self):
        started_at = time.time()
        original_wfile = self.wfile
        counted_wfile = CountingWriter(original_wfile)
        self.wfile = counted_wfile
        self._telemetry_status = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            super().handle_one_request()
        finally:
            self.wfile = original_wfile
            try:
                request_size = int(self.headers.get("Content-Length", "0") or 0)
            except (TypeError, ValueError):
                request_size = 0
            self.request_logger.record(
                target=getattr(self, "path", ""),
                method=getattr(self, "command", "UNKNOWN"),
                status=getattr(self, "_telemetry_status", HTTPStatus.INTERNAL_SERVER_ERROR),
                request_size=request_size,
                response_size=counted_wfile.bytes_written,
                started_at=started_at,
            )

    def send_response(self, code, message=None):
        self._telemetry_status = int(code)
        super().send_response(code, message)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def operator_only(self):
        if self.headers.get(MODE_HEADER, "visitor") != "operator":
            self.send_json({"error": "This action requires 牛马模式 (operator mode)."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings":
            return self.send_json({"library": str(self.library.root), "page_size": int(self.config.get("page_size", "5"))})
        if parsed.path == "/api/jobs":
            if not self.operator_only(): return
            return self.send_json({"jobs": self.library.jobs.list()})
        result_match = re.match(r"^/api/jobs/([^/]+)/results$", parsed.path)
        if result_match:
            job = self.library.jobs.get(result_match.group(1))
            if not job:
                return self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
            if job["type"] not in {"quality_detection", "auto_develop"}:
                return self.send_json({"error": "This job has no image results"}, HTTPStatus.BAD_REQUEST)
            query = parse_qs(parsed.query)
            page = max(1, int(query.get("page", ["1"])[0]))
            page_size = max(1, min(100, int(query.get("page_size", ["50"])[0])))
            if job["type"] == "auto_develop":
                results, total = self.library.catalog.auto_variants(job["scope"].get("folder", ""), job["id"], page, page_size)
                return self.send_json({"results": results, "page": page, "page_size": page_size, "total": total, "pages": max(1, (total + page_size - 1) // page_size)})
            bad_only = query.get("bad_only", ["false"])[0].lower() == "true"
            threshold_value = query.get("threshold", [""])[0]
            threshold = float(threshold_value) if threshold_value else None
            results, total = self.library.catalog.quality_results(job["id"], job["scope"].get("folder", ""), page, page_size, bad_only, threshold)
            return self.send_json({"results": results, "page": page, "page_size": page_size, "total": total, "pages": max(1, (total + page_size - 1) // page_size)})
        job_match = re.match(r"^/api/jobs/([^/]+)$", parsed.path)
        if job_match:
            job = self.library.jobs.get(job_match.group(1))
            return self.send_json(job or {"error": "Job not found"}, HTTPStatus.OK if job else HTTPStatus.NOT_FOUND)
        if parsed.path == "/api/folders":
            return self.send_json({"root": str(self.library.root), "folders": self.library.folders()})
        if parsed.path == "/api/tags":
            return self.send_json({"tags": self.library.catalog.tags()})
        asset_match = re.match(r"^/api/assets/([^/]+)$", parsed.path)
        if asset_match:
            asset = self.library.asset_by_id(asset_match.group(1))
            return self.send_json(asset or {"error": "Asset not found"}, HTTPStatus.OK if asset else HTTPStatus.NOT_FOUND)
        if parsed.path == "/api/trash":
            if self.headers.get(MODE_HEADER, "visitor") != "operator": return self.send_json({"error": "Trash requires 牛马模式."}, HTTPStatus.FORBIDDEN)
            query = parse_qs(parsed.query)
            page = max(1, int(query.get("page", ["1"])[0]))
            requested_page_size = int(query.get("page_size", ["5"])[0])
            page_size = requested_page_size if requested_page_size in {5, 10, 20, 50} else 5
            assets, total = self.library.trash_page(page, page_size)
            return self.send_json({"root": str(self.library.root), "assets": assets, "page": page, "page_size": page_size, "total": total, "pages": max(1, (total + page_size - 1) // page_size)})
        if parsed.path == "/api/catalog/status":
            return self.send_json({"state": self.library.scan_state, "result": self.library.scan_result})
        if parsed.path == "/api/library":
            query = parse_qs(parsed.query)
            folder = query.get("folder", [""])[0]
            search = query.get("q", [""])[0].strip().lower()
            tag = query.get("tag", [""])[0].strip()
            page = max(1, int(query.get("page", ["1"])[0]))
            requested_page_size = int(query.get("page_size", ["5"])[0])
            page_size = requested_page_size if requested_page_size in {5, 10, 20, 50} else 5
            show_hidden = query.get("show_hidden", ["false"])[0].lower() == "true"
            assets, total = self.library.page(folder, search, page, page_size, show_hidden, tag)
            return self.send_json({"root": str(self.library.root), "assets": assets, "page": page, "page_size": page_size, "total": total, "pages": max(1, (total + page_size - 1) // page_size)})
        if parsed.path.startswith("/media/"):
            relative = unquote(parsed.path[len("/media/"):])
            path = self.library.media_path(relative)
            if not path:
                return self.send_json({"error": "Image not found"}, HTTPStatus.NOT_FOUND)
            content_type = "image/jpeg" if path.suffix.casefold() in {".heic", ".heif"} else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=60")
            self.end_headers()
            return self.wfile.write(data)
        if parsed.path == "/api/health":
            return self.send_json({"ok": True})
        return self.static_file(parsed.path)

    def static_file(self, path):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (self.web_root / relative).resolve()
        if self.web_root not in target.parents and target != self.web_root:
            return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        if not target.is_file():
            return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings":
            if not self.operator_only(): return
            payload = self.body_json()
            raw_library = str(payload.get("library", "")).strip()
            try:
                page_size = int(payload.get("page_size", 5))
            except (TypeError, ValueError):
                return self.send_json({"error": "page_size must be one of 5, 10, 20, 50"}, HTTPStatus.BAD_REQUEST)
            root = Path(raw_library).expanduser().resolve()
            if not root.is_dir():
                return self.send_json({"error": "Album folder does not exist"}, HTTPStatus.BAD_REQUEST)
            if page_size not in {5, 10, 20, 50}:
                return self.send_json({"error": "page_size must be one of 5, 10, 20, 50"}, HTTPStatus.BAD_REQUEST)
            config = dict(self.config)
            config["library"] = str(root)
            config["page_size"] = str(page_size)
            try:
                save_config(self.config_path, config)
                library_changed = root != self.library.root
                if library_changed:
                    # Separate catalogs prevent stale assets from another root.
                    library_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
                    next_library = Library(root, self.library.data_dir / "libraries" / library_key)
                    Handler.library = next_library
                    next_library.start_initial_scan()
                self.config = config
                Handler.config = config
            except OSError as error:
                return self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return self.send_json({"library": str(root), "page_size": page_size, "library_changed": library_changed})
        apply_match = re.match(r"^/api/jobs/([^/]+)/apply-tags$", parsed.path)
        if apply_match:
            if not self.operator_only(): return
            job = self.library.jobs.get(apply_match.group(1))
            if not job or job["type"] != "quality_detection":
                return self.send_json({"error": "Quality detection job not found"}, HTTPStatus.NOT_FOUND)
            try:
                threshold = float(self.body_json().get("threshold", 0.55))
                applied = self.library.catalog.apply_quality_tags(job["id"], job["scope"].get("folder", ""), threshold)
            except (TypeError, ValueError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json({"tag": "bad_quality", "threshold": threshold, "applied": applied})
        delete_auto_match = re.match(r"^/api/jobs/([^/]+)/delete-auto-variants$", parsed.path)
        if delete_auto_match:
            if not self.operator_only(): return
            job = self.library.jobs.get(delete_auto_match.group(1))
            if not job or job["type"] != "auto_develop":
                return self.send_json({"error": "Auto Develop job not found"}, HTTPStatus.NOT_FOUND)
            deleted = self.library.catalog.delete_auto_variants(job["scope"].get("folder", ""), job["id"])
            return self.send_json({"deleted": deleted})
        tag_match = re.match(r"^/api/assets/([^/]+)/tags$", parsed.path)
        if tag_match:
            if not self.operator_only(): return
            asset_id = tag_match.group(1)
            if not self.library.asset_by_id(asset_id):
                return self.send_json({"error": "Asset not found"}, HTTPStatus.NOT_FOUND)
            tag = str(self.body_json().get("tag", "")).strip()
            if not tag or len(tag) > 80:
                return self.send_json({"error": "tag must be 1-80 characters"}, HTTPStatus.BAD_REQUEST)
            self.library.catalog.set_tag(asset_id, tag, "manual")
            return self.send_json({"asset_id": asset_id, "tags": self.library.catalog.tags_for_asset(asset_id)}, HTTPStatus.CREATED)
        if parsed.path == "/api/jobs":
            if not self.operator_only(): return
            payload = self.body_json()
            try:
                job = self.library.jobs.create(payload.get("type", ""), payload.get("scope", {}))
            except ValueError as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            self.library.start_job(job)
            return self.send_json(job, HTTPStatus.ACCEPTED)
        if parsed.path == "/api/assets/bulk":
            if not self.operator_only(): return
            payload = self.body_json()
            try:
                count = self.library.catalog.bulk_update(payload.get("asset_ids", []), payload.get("action", ""))
            except ValueError as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json({"updated": count})
        job_match = re.match(r"^/api/jobs/([^/]+)/(cancel|retry)$", parsed.path)
        if job_match:
            if not self.operator_only(): return
            try:
                job = self.library.jobs.cancel(job_match.group(1)) if job_match.group(2) == "cancel" else self.library.jobs.retry(job_match.group(1))
            except (KeyError, ValueError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json(job)
        if parsed.path == "/api/refresh":
            if not self.operator_only(): return
            return self.send_json(self.library.start_full_scan_job(), HTTPStatus.ACCEPTED)
        if parsed.path == "/api/recipes":
            if not self.operator_only(): return
            payload = self.body_json()
            asset_id = payload.get("asset_id")
            if not self.library.asset_by_id(asset_id):
                return self.send_json({"error": "Unknown asset"}, HTTPStatus.NOT_FOUND)
            recipe = payload.get("recipe", {})
            with self.library.lock:
                try:
                    recipe = self.library.metadata.create_variant(asset_id, recipe)
                except ValueError as error:
                    return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json(recipe, HTTPStatus.CREATED)
        rename_match = re.match(r"^/api/recipes/([^/]+)/([^/]+)/name$", parsed.path)
        if rename_match:
            asset_id, variant_id = rename_match.groups()
            payload = self.body_json()
            with self.library.lock:
                try:
                    recipe = self.library.metadata.rename_variant(asset_id, variant_id, payload.get("name", ""))
                except (KeyError, ValueError) as error:
                    return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json(recipe)
        if parsed.path == "/api/export":
            if not self.operator_only(): return
            payload = self.body_json()
            relative_path = self.library.source_path(payload.get("asset_id", ""))
            if not relative_path:
                return self.send_json({"error": "Asset not found or unavailable"}, HTTPStatus.NOT_FOUND)
            exports = self.library.data_dir / "exports"
            exports.mkdir(exist_ok=True)
            filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", payload.get("filename", "export"))
            if not filename.lower().endswith(".jpg"): filename += ".jpg"
            target = exports / filename
            try:
                self.library.renderer.render(relative_path, payload.get("recipe", {}), target)
            except (ValueError, FileNotFoundError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json({"path": str(target), "filename": filename})
        if parsed.path == "/api/device-export":
            if not self.operator_only(): return
            payload = self.body_json()
            if payload.get("device") != "kindle_gen_7":
                return self.send_json({"error": "Unsupported device"}, HTTPStatus.BAD_REQUEST)
            output_dir = self.config.get("kindle_gen7_output", "").strip()
            if not output_dir:
                return self.send_json({"error": "kindle_gen7_output is not configured"}, HTTPStatus.BAD_REQUEST)
            relative_path = self.library.source_path(payload.get("asset_id", ""))
            if not relative_path:
                return self.send_json({"error": "Asset not found or unavailable"}, HTTPStatus.NOT_FOUND)
            source_name = Path(relative_path).stem
            filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_name) + "_16gray.png"
            target = Path(output_dir).expanduser() / filename
            recipe = dict(payload.get("recipe") or {})
            recipe["filter"] = "kindle_16gray"
            try:
                self.library.renderer.render(relative_path, recipe, target)
            except (ValueError, FileNotFoundError, OSError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return self.send_json({"device": "kindle_gen_7", "path": str(target), "filename": filename})
        return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/trash":
            if not self.operator_only(): return
            return self.send_json(self.library.catalog.clear_trash())
        tag_match = re.match(r"^/api/assets/([^/]+)/tags/(.+)$", parsed.path)
        if tag_match:
            if not self.operator_only(): return
            asset_id, tag = tag_match.groups()
            if not self.library.asset_by_id(asset_id):
                return self.send_json({"error": "Asset not found"}, HTTPStatus.NOT_FOUND)
            self.library.catalog.remove_tag(asset_id, unquote(tag), "manual")
            return self.send_json({"asset_id": asset_id, "tags": self.library.catalog.tags_for_asset(asset_id)})
        match = re.match(r"^/api/recipes/([^/]+)/([^/]+)$", parsed.path)
        if not match:
            return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        if not self.operator_only(): return
        asset_id, variant_id = match.groups()
        with self.library.lock:
            try:
                self.library.metadata.delete_variant(asset_id, variant_id)
            except KeyError:
                return self.send_json({"error": "Variant not found"}, HTTPStatus.NOT_FOUND)
        return self.send_json({"deleted": variant_id})


def main():
    config_path = Path.home() / ".config" / "no_waste_album" / "config.yaml"
    config = load_config(config_path)
    if config.get("dev_reload", "true").lower() == "true" and os.environ.get("NWA_RELOADED_CHILD") != "1":
        return run_dev_reloader()
    root = Path(config.get("library", "")).expanduser()
    if not root.is_dir(): raise SystemExit("library folder does not exist: %s" % root)
    data_dir = Path(config.get("data_dir", str(root / "no_waste_album"))).expanduser()
    host = config.get("host", "127.0.0.1")
    port = int(config.get("port", "7008"))
    Handler.config_path = config_path
    Handler.config = config
    Handler.library = Library(root, data_dir)
    server = ThreadingHTTPServer((host, port), Handler)
    print("No Waste Album POC: http://%s:%s" % (host, port), flush=True)
    print("Library: %s" % Handler.library.root, flush=True)
    Handler.library.start_initial_scan()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__":
    main()
