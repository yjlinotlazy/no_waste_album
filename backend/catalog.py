"""Local photo-library catalog with append-oriented and full scans."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import json
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic", ".heif"}


@dataclass(frozen=True)
class CatalogAsset:
    id: str
    relative_path: str
    name: str
    folder: str
    size: int
    modified_ns: int
    status: str
    hidden: int = 0


class Catalog:
    def __init__(self, library_root: Path, database_path: Path):
        self.root = library_root.expanduser().resolve()
        self.database_path = database_path.expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS catalog_assets (
                    id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    content_fingerprint TEXT,
                    status TEXT NOT NULL DEFAULT 'available',
                    hidden INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_folder ON catalog_assets(folder);
                CREATE INDEX IF NOT EXISTS idx_catalog_status ON catalog_assets(status);
                CREATE TABLE IF NOT EXISTS catalog_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    files_seen INTEGER NOT NULL DEFAULT 0,
                    files_added INTEGER NOT NULL DEFAULT 0,
                    files_changed INTEGER NOT NULL DEFAULT 0,
                    files_missing INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running'
                );
                CREATE TABLE IF NOT EXISTS variants (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    recipe_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(asset_id) REFERENCES catalog_assets(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_variants_asset ON variants(asset_id);
                CREATE TABLE IF NOT EXISTS quality_assessments (
                    asset_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    detector_version TEXT NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    badness_score REAL NOT NULL,
                    threshold REAL NOT NULL,
                    is_bad INTEGER NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(asset_id, job_id),
                    FOREIGN KEY(asset_id) REFERENCES catalog_assets(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS tags (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS asset_tags (
                    asset_id TEXT NOT NULL,
                    tag_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(asset_id, tag_name, source),
                    FOREIGN KEY(asset_id) REFERENCES catalog_assets(id) ON DELETE CASCADE,
                    FOREIGN KEY(tag_name) REFERENCES tags(name) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_asset_tags_tag ON asset_tags(tag_name);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(catalog_assets)")}
            if "hidden" not in columns:
                db.execute("ALTER TABLE catalog_assets ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
            quality_columns = {row[1] for row in db.execute("PRAGMA table_info(quality_assessments)")}
            if "job_id" not in quality_columns:
                db.execute("ALTER TABLE quality_assessments ADD COLUMN job_id TEXT")
            quality_primary_key = [row[1] for row in db.execute("PRAGMA table_info(quality_assessments)") if row[5]]
            if quality_primary_key == ["asset_id"]:
                db.execute("ALTER TABLE quality_assessments RENAME TO quality_assessments_legacy")
                db.execute("""CREATE TABLE quality_assessments (
                    asset_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    detector_version TEXT NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    badness_score REAL NOT NULL,
                    threshold REAL NOT NULL,
                    is_bad INTEGER NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(asset_id, job_id),
                    FOREIGN KEY(asset_id) REFERENCES catalog_assets(id) ON DELETE CASCADE
                )""")
                db.execute("""INSERT INTO quality_assessments
                    (asset_id,job_id,detector_version,modified_ns,badness_score,threshold,is_bad,details_json,created_at)
                    SELECT asset_id,COALESCE(job_id,'legacy'),detector_version,modified_ns,badness_score,threshold,is_bad,details_json,created_at
                    FROM quality_assessments_legacy""")
                db.execute("DROP TABLE quality_assessments_legacy")

    @staticmethod
    def _asset_id(relative_path: str, fingerprint: str | None = None) -> str:
        # Path keeps a moved file traceable during catalog reconciliation; the
        # content fingerprint is stored separately and used for duplicate work.
        return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _fingerprint(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _iter_images(self) -> Iterable[tuple[Path, str]]:
        def walk(folder: Path):
            try:
                entries = sorted(os.scandir(folder), key=lambda entry: entry.name.casefold())
            except OSError:
                return
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() == "raw":
                        continue
                    yield from walk(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.casefold() in IMAGE_EXTENSIONS:
                    path = Path(entry.path)
                    yield path, path.relative_to(self.root).as_posix()
        yield from walk(self.root)

    def scan(self, kind: str = "incremental", progress=None) -> dict[str, int | str]:
        if kind not in {"incremental", "full"}:
            raise ValueError("scan kind must be incremental or full")
        counts = {"seen": 0, "added": 0, "changed": 0, "missing": 0}
        with closing(self._connect()) as db, db:
            scan_id = db.execute("INSERT INTO catalog_scans(kind) VALUES (?)", (kind,)).lastrowid
            seen: set[str] = set()
            entries = list(self._iter_images())
            total_images = len(entries)
            folders_total = len({path.parent.relative_to(self.root).as_posix() if path.parent != self.root else "" for path, _ in entries})
            folders_seen = set()
            for index, (path, relative) in enumerate(entries, 1):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                counts["seen"] += 1
                seen.add(relative)
                existing = db.execute("SELECT * FROM catalog_assets WHERE relative_path=?", (relative,)).fetchone()
                if existing is None:
                    fingerprint = self._fingerprint(path)
                    db.execute("INSERT INTO catalog_assets(id,relative_path,name,folder,size,modified_ns,content_fingerprint) VALUES (?,?,?,?,?,?,?)", (self._asset_id(relative), relative, path.name, path.parent.relative_to(self.root).as_posix() if path.parent != self.root else "", stat.st_size, stat.st_mtime_ns, fingerprint))
                    counts["added"] += 1
                elif existing["size"] != stat.st_size or existing["modified_ns"] != stat.st_mtime_ns or existing["status"] == "missing":
                    # Full fingerprinting is intentionally limited to changed files.
                    # A rescan must not resurrect a file that is in the trash.
                    status = "available" if existing["status"] == "missing" else existing["status"]
                    db.execute("UPDATE catalog_assets SET size=?, modified_ns=?, status=?, content_fingerprint=?, last_seen_at=CURRENT_TIMESTAMP WHERE relative_path=?", (stat.st_size, stat.st_mtime_ns, status, self._fingerprint(path), relative))
                    counts["changed"] += 1
                else:
                    db.execute("UPDATE catalog_assets SET last_seen_at=CURRENT_TIMESTAMP WHERE relative_path=?", (relative,))
                folders_seen.add(path.parent)
                if progress:
                    progress({"percent": round(index / max(1, total_images) * 100), "images_scanned": index, "images_total": total_images, "folders_scanned": len(folders_seen), "folders_total": folders_total})
            if kind == "full":
                rows = db.execute("SELECT relative_path FROM catalog_assets WHERE status='available'").fetchall()
                missing = [row["relative_path"] for row in rows if row["relative_path"] not in seen]
                if missing:
                    db.executemany("UPDATE catalog_assets SET status='missing' WHERE relative_path=?", ((path,) for path in missing))
                    counts["missing"] = len(missing)
            db.execute("UPDATE catalog_scans SET finished_at=CURRENT_TIMESTAMP, files_seen=?, files_added=?, files_changed=?, files_missing=?, status='completed' WHERE id=?", (counts["seen"], counts["added"], counts["changed"], counts["missing"], scan_id))
        return {"kind": kind, **counts}

    def folders(self) -> list[str]:
        with closing(self._connect()) as db:
            return [row[0] for row in db.execute("SELECT DISTINCT folder FROM catalog_assets WHERE status='available' ORDER BY folder COLLATE NOCASE") if row[0]]

    def get(self, asset_id: str) -> CatalogAsset | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT id,relative_path,name,folder,size,modified_ns,status,hidden FROM catalog_assets WHERE id=?", (asset_id,)).fetchone()
        return CatalogAsset(**dict(row)) if row else None

    def assets_in_scope(self, folder: str) -> list[CatalogAsset]:
        if folder:
            where = "status='available' AND (folder=? OR folder LIKE ?)"
            params = (folder, folder.rstrip("/") + "/%")
        else:
            where = "status='available'"
            params = ()
        with closing(self._connect()) as db:
            rows = db.execute(f"SELECT id,relative_path,name,folder,size,modified_ns,status,hidden FROM catalog_assets WHERE {where} ORDER BY modified_ns ASC, relative_path COLLATE NOCASE", params).fetchall()
        return [CatalogAsset(**dict(row)) for row in rows]

    def set_tag(self, asset_id: str, tag_name: str, source: str = "manual") -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (tag_name,))
            db.execute("INSERT OR REPLACE INTO asset_tags(asset_id,tag_name,source) VALUES (?,?,?)", (asset_id, tag_name, source))

    def remove_tag(self, asset_id: str, tag_name: str, source: str | None = None) -> None:
        with closing(self._connect()) as db, db:
            if source is None:
                db.execute("DELETE FROM asset_tags WHERE asset_id=? AND tag_name=?", (asset_id, tag_name))
            else:
                db.execute("DELETE FROM asset_tags WHERE asset_id=? AND tag_name=? AND source=?", (asset_id, tag_name, source))

    def tags(self, include_trashed: bool = False) -> list[dict]:
        status = "" if include_trashed else "AND a.status='available'"
        with closing(self._connect()) as db:
            rows = db.execute(f"SELECT t.name, COUNT(DISTINCT at.asset_id) FROM tags t JOIN asset_tags at ON at.tag_name=t.name JOIN catalog_assets a ON a.id=at.asset_id {status} GROUP BY t.name ORDER BY t.name COLLATE NOCASE").fetchall()
        return [{"name": row[0], "count": row[1]} for row in rows]

    def tags_for_asset(self, asset_id: str) -> list[str]:
        with closing(self._connect()) as db:
            return [row[0] for row in db.execute("SELECT tag_name FROM asset_tags WHERE asset_id=? ORDER BY tag_name COLLATE NOCASE", (asset_id,))]

    def apply_quality_tags(self, job_id: str, folder: str, threshold: float) -> int:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        clauses = ["q.job_id=?", "a.status='available'"]
        params: list = [job_id]
        if folder:
            clauses.append("(a.folder=? OR a.folder LIKE ?)")
            params.extend([folder, folder.rstrip("/") + "/%"])
        where = " AND ".join(clauses)
        with closing(self._connect()) as db, db:
            rows = db.execute(f"SELECT q.asset_id,q.job_id,q.badness_score FROM quality_assessments q JOIN catalog_assets a ON a.id=q.asset_id WHERE {where}", params).fetchall()
            db.execute("INSERT OR IGNORE INTO tags(name) VALUES ('bad_quality')")
            applied = 0
            for asset_id, row_job_id, score in rows:
                if score >= threshold:
                    db.execute("INSERT OR REPLACE INTO asset_tags(asset_id,tag_name,source) VALUES (?,?,?)", (asset_id, "bad_quality", "quality_detection"))
                    applied += 1
                else:
                    db.execute("DELETE FROM asset_tags WHERE asset_id=? AND tag_name=? AND source=?", (asset_id, "bad_quality", "quality_detection"))
                db.execute("UPDATE quality_assessments SET threshold=?, is_bad=? WHERE asset_id=? AND job_id=?", (threshold, int(score >= threshold), asset_id, row_job_id))
        return applied

    def quality_results(self, job_id: str, folder: str, page: int = 1, page_size: int = 50, bad_only: bool = False, threshold: float | None = None) -> tuple[list[dict], int]:
        clauses = ["q.job_id=?", "a.status='available'"]
        params: list = [job_id]
        if folder:
            clauses.append("(a.folder=? OR a.folder LIKE ?)")
            params.extend([folder, folder.rstrip("/") + "/%"])
        if bad_only:
            clauses.append("q.badness_score>=?")
            params.append(threshold if threshold is not None else 0.55)
        where = " AND ".join(clauses)
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        with closing(self._connect()) as db:
            total = db.execute(f"SELECT COUNT(*) FROM quality_assessments q JOIN catalog_assets a ON a.id=q.asset_id WHERE {where}", params).fetchone()[0]
            rows = db.execute(f"SELECT a.id,a.name,a.relative_path,a.folder,q.badness_score,q.threshold,q.is_bad,q.details_json FROM quality_assessments q JOIN catalog_assets a ON a.id=q.asset_id WHERE {where} ORDER BY q.badness_score DESC,a.relative_path COLLATE NOCASE LIMIT ? OFFSET ?", [*params, page_size, (page - 1) * page_size]).fetchall()
        return [{"id": row[0], "name": row[1], "path": row[2], "folder": row[3], "url": "/media/" + row[2], "badness_score": row[4], "threshold": threshold if threshold is not None else row[5], "is_bad": bool(row[6]) if threshold is None else row[4] >= threshold, "details": json.loads(row[7])} for row in rows], total

    def variants(self, asset_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id, recipe_json FROM variants WHERE asset_id=? ORDER BY created_at, rowid", (asset_id,)).fetchall()
        return [dict(json.loads(row[1]), id=row[0]) for row in rows]

    def auto_variants(self, folder: str, job_id: str, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
        assets = self.assets_in_scope(folder)
        matches = []
        for asset in assets:
            for variant in self.variants(asset.id):
                if variant.get("source_job_id") == job_id:
                    matches.append({"id": asset.id, "name": asset.name, "folder": asset.folder, "url": "/media/" + asset.relative_path, "variant_id": variant["id"], "variant_name": variant.get("name", ""), "recipe": variant})
        total = len(matches)
        start = max(0, page - 1) * page_size
        return matches[start:start + page_size], total

    def delete_auto_variants(self, folder: str, job_id: str) -> int:
        assets = self.assets_in_scope(folder)
        deleted = 0
        with closing(self._connect()) as db, db:
            for asset in assets:
                rows = db.execute("SELECT id, recipe_json FROM variants WHERE asset_id=?", (asset.id,)).fetchall()
                for variant_id, recipe_json in rows:
                    if json.loads(recipe_json).get("source_job_id") == job_id:
                        db.execute("DELETE FROM variants WHERE asset_id=? AND id=?", (asset.id, variant_id))
                        deleted += 1
        return deleted

    def asset_id_by_legacy_prefix(self, prefix: str) -> str | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT id FROM catalog_assets WHERE id LIKE ? LIMIT 1", (f"{prefix}%",)).fetchone()
        return row[0] if row else None

    def add_variant(self, asset_id: str, variant: dict) -> dict:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO variants(id,asset_id,recipe_json) VALUES (?,?,?)", (variant["id"], asset_id, json.dumps(variant)))
        return variant

    def rename_variant(self, asset_id: str, variant_id: str, name: str) -> dict | None:
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT recipe_json FROM variants WHERE asset_id=? AND id=?", (asset_id, variant_id)).fetchone()
            if not row:
                return None
            recipe = json.loads(row[0])
            if name:
                recipe["name"] = name
            else:
                recipe.pop("name", None)
            db.execute("UPDATE variants SET recipe_json=? WHERE asset_id=? AND id=?", (json.dumps(recipe), asset_id, variant_id))
            return dict(recipe, id=variant_id)

    def delete_variant(self, asset_id: str, variant_id: str) -> bool:
        with closing(self._connect()) as db, db:
            result = db.execute("DELETE FROM variants WHERE asset_id=? AND id=?", (asset_id, variant_id))
        return result.rowcount == 1

    def page(self, folder: str = "", query: str = "", page: int = 1, page_size: int = 50, show_hidden: bool = False, include_trashed: bool = False, tag: str = "") -> tuple[list[CatalogAsset], int]:
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        clauses = ["status='trashed'" if include_trashed else "status='available'"]
        if not show_hidden and not include_trashed: clauses.append("hidden=0")
        params: list[str] = []
        if folder:
            clauses.append("folder=?"); params.append(folder)
        if query:
            clauses.append("(name LIKE ? OR relative_path LIKE ?)"); params.extend([f"%{query}%", f"%{query}%"])
        if tag:
            clauses.append("EXISTS (SELECT 1 FROM asset_tags filter_tags WHERE filter_tags.asset_id=catalog_assets.id AND filter_tags.tag_name=?)"); params.append(tag)
        where = " AND ".join(clauses)
        with closing(self._connect()) as db, db:
            total = db.execute(f"SELECT COUNT(*) FROM catalog_assets WHERE {where}", params).fetchone()[0]
            rows = db.execute(f"SELECT id,relative_path,name,folder,size,modified_ns,status,hidden FROM catalog_assets WHERE {where} ORDER BY modified_ns ASC, relative_path COLLATE NOCASE LIMIT ? OFFSET ?", [*params, page_size, (page - 1) * page_size]).fetchall()
        return [CatalogAsset(**dict(row)) for row in rows], total

    def bulk_update(self, asset_ids: list[str], action: str) -> int:
        if action not in {"hide", "unhide", "trash", "restore"}:
            raise ValueError("unsupported bulk action")
        if not asset_ids: return 0
        with closing(self._connect()) as db, db:
            placeholders = ",".join("?" for _ in asset_ids)
            if action == "trash":
                result = db.execute(f"UPDATE catalog_assets SET status='trashed' WHERE id IN ({placeholders}) AND status='available'", asset_ids)
            elif action == "restore":
                result = db.execute(f"UPDATE catalog_assets SET status='available' WHERE id IN ({placeholders}) AND status='trashed'", asset_ids)
            else:
                result = db.execute(f"UPDATE catalog_assets SET hidden=? WHERE id IN ({placeholders}) AND status='available'", [1 if action == "hide" else 0, *asset_ids])
        return result.rowcount

    def clear_trash(self) -> dict[str, int | list[str]]:
        removed = 0
        errors = []
        removed_ids = []
        with closing(self._connect()) as db, db:
            rows = db.execute("SELECT id, relative_path FROM catalog_assets WHERE status='trashed'").fetchall()
            for row in rows:
                path = (self.root / row[1]).resolve()
                try:
                    if self.root not in path.parents or any(part.casefold() == "raw" for part in path.relative_to(self.root).parts):
                        raise ValueError("unsafe trash path")
                    path.unlink(missing_ok=True)
                    db.execute("DELETE FROM catalog_assets WHERE id=?", (row[0],))
                    removed_ids.append(row[0])
                    removed += 1
                except (OSError, ValueError) as error:
                    errors.append(f"{row[1]}: {error}")
        feature_database = self.database_path.parent / "features.sqlite"
        if removed_ids and feature_database.exists():
            with closing(sqlite3.connect(feature_database)) as features, features:
                placeholders = ",".join("?" for _ in removed_ids)
                features.execute(f"DELETE FROM image_features WHERE asset_id IN ({placeholders})", removed_ids)
        return {"deleted": removed, "errors": errors}
