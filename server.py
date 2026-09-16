#!/usr/bin/env python3
"""Dependency-free local POC server for No Waste Album."""

import base64
import hashlib
import json
import mimetypes
import os
import re
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic"}
MODE_HEADER = "X-App-Mode"


class Library:
    def __init__(self, root: Path, data_dir: Path):
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.recipe_file = self.data_dir / "recipes.json"
        self.lock = threading.Lock()
        self.catalog_lock = threading.Lock()
        self.catalog = None
        self.recipes = self._load_json(self.recipe_file, {})

    @staticmethod
    def _load_json(path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return fallback

    def _save_recipes(self):
        tmp = self.recipe_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.recipes, indent=2), encoding="utf-8")
        tmp.replace(self.recipe_file)

    def _scan_assets(self):
        result = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            relative = path.relative_to(self.root).as_posix()
            stat = path.stat()
            asset_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            result.append({
                "id": asset_id,
                "name": path.name,
                "path": relative,
                "folder": path.parent.relative_to(self.root).as_posix() if path.parent != self.root else "",
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "url": "/media/" + relative,
            })
        return result

    def assets(self):
        with self.catalog_lock:
            if self.catalog is None:
                self.catalog = self._scan_assets()
            result = [dict(asset, recipes=self.recipes.get(asset["id"], [])) for asset in self.catalog]
        return result

    def folders(self):
        return sorted({a["folder"] for a in self.assets()})

    def refresh(self):
        with self.catalog_lock:
            self.catalog = self._scan_assets()
        return len(self.catalog)

    def asset_by_id(self, asset_id):
        return next((a for a in self.assets() if a["id"] == asset_id), None)


def safe_media_path(library, relative):
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


class Handler(BaseHTTPRequestHandler):
    library = None
    web_root = Path(__file__).parent / "web"

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
        if parsed.path == "/api/folders":
            return self.send_json({"root": str(self.library.root), "folders": self.library.folders()})
        if parsed.path == "/api/library":
            query = parse_qs(parsed.query)
            folder = query.get("folder", [""])[0]
            search = query.get("q", [""])[0].strip().lower()
            page = max(1, int(query.get("page", ["1"])[0]))
            page_size = 5
            all_assets = self.library.assets()
            filtered = [a for a in all_assets if (not folder or a["folder"] == folder) and (not search or search in (a["name"] + " " + a["path"]).lower())]
            total = len(filtered)
            start = (page - 1) * page_size
            assets = filtered[start:start + page_size]
            return self.send_json({"root": str(self.library.root), "assets": assets, "page": page, "page_size": page_size, "total": total, "pages": max(1, (total + page_size - 1) // page_size)})
        if parsed.path.startswith("/media/"):
            path = safe_media_path(self.library, parsed.path[len("/media/"):])
            if not path:
                return self.send_json({"error": "Image not found"}, HTTPStatus.NOT_FOUND)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
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
        if parsed.path == "/api/refresh":
            if not self.operator_only(): return
            return self.send_json({"assets": self.library.refresh()})
        if parsed.path == "/api/recipes":
            if not self.operator_only(): return
            payload = self.body_json()
            asset_id = payload.get("asset_id")
            if not self.library.asset_by_id(asset_id):
                return self.send_json({"error": "Unknown asset"}, HTTPStatus.NOT_FOUND)
            recipe = payload.get("recipe", {})
            recipe.setdefault("id", uuid.uuid4().hex[:12])
            recipe.setdefault("name", "Untitled variant")
            with self.library.lock:
                variants = self.library.recipes.setdefault(asset_id, [])
                variants.append(recipe)
                self.library._save_recipes()
            return self.send_json(recipe, HTTPStatus.CREATED)
        if parsed.path == "/api/export":
            if not self.operator_only(): return
            payload = self.body_json()
            match = re.match(r"^data:image/(png|jpeg);base64,(.+)$", payload.get("data_url", ""), re.S)
            if not match:
                return self.send_json({"error": "Expected a PNG or JPEG data URL"}, HTTPStatus.BAD_REQUEST)
            ext = ".jpg" if match.group(1) == "jpeg" else ".png"
            exports = self.library.data_dir / "exports"
            exports.mkdir(exist_ok=True)
            filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", payload.get("filename", "export"))
            if not filename.lower().endswith(ext): filename += ext
            target = exports / filename
            target.write_bytes(base64.b64decode(match.group(2)))
            return self.send_json({"path": str(target), "filename": filename})
        return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        match = re.match(r"^/api/recipes/([^/]+)/([^/]+)$", parsed.path)
        if not match:
            return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        if not self.operator_only(): return
        asset_id, variant_id = match.groups()
        with self.library.lock:
            variants = self.library.recipes.get(asset_id, [])
            remaining = [v for v in variants if v.get("id") != variant_id]
            if len(remaining) == len(variants):
                return self.send_json({"error": "Variant not found"}, HTTPStatus.NOT_FOUND)
            if remaining: self.library.recipes[asset_id] = remaining
            else: self.library.recipes.pop(asset_id, None)
            self.library._save_recipes()
        return self.send_json({"deleted": variant_id})


def main():
    config_path = Path.home() / ".config" / "no_waste_album" / "config.yaml"
    config = load_config(config_path)
    root = Path(config.get("library", "")).expanduser()
    if not root.is_dir(): raise SystemExit("library folder does not exist: %s" % root)
    data_dir = Path(config.get("data_dir", str(Path.home() / ".local" / "share" / "no_waste_album"))).expanduser()
    host = config.get("host", "127.0.0.1")
    port = int(config.get("port", "7008"))
    Handler.library = Library(root, data_dir)
    server = ThreadingHTTPServer((host, port), Handler)
    print("No Waste Album POC: http://%s:%s" % (host, port))
    print("Library: %s" % Handler.library.root)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__":
    main()
