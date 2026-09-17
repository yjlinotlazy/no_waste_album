"""Persistent local job state and lifecycle management."""

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

JOB_TYPES = {"analysis", "quality_detection", "clustering", "indexing", "catalog_scan"}
TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "failed": {"queued"},
    "completed": set(),
    "cancelled": {"queued"},
}


class JobStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path.expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, state TEXT NOT NULL,
                scope_json TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                progress_detail TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "progress_detail" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN progress_detail TEXT NOT NULL DEFAULT '{}'")

    def _connect(self):
        db = sqlite3.connect(self.database_path)
        db.row_factory = sqlite3.Row
        return db

    def create(self, job_type: str, scope: dict | None = None) -> dict:
        if job_type not in JOB_TYPES:
            raise ValueError(f"unsupported job type: {job_type}")
        job_id = uuid.uuid4().hex
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO jobs(id,type,state,scope_json) VALUES (?,?,?,?)", (job_id, job_type, "queued", json.dumps(scope or {})))
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row: return None
        result = dict(row)
        result["scope"] = json.loads(result.pop("scope_json"))
        result["progress_detail"] = json.loads(result["progress_detail"])
        return result

    def list(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (max(1, min(500, limit)),)).fetchall()
        return [self.get(row[0]) for row in rows]

    def update_progress(self, job_id: str, progress: int, detail: dict | None = None) -> dict:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET progress=?, progress_detail=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (max(0, min(100, progress)), json.dumps(detail or {}), job_id))
        return self.get(job_id)

    def transition(self, job_id: str, state: str, error: str | None = None) -> dict:
        current = self.get(job_id)
        if not current: raise KeyError("job not found")
        if state not in TRANSITIONS[current["state"]]:
            raise ValueError(f"cannot transition {current['state']} to {state}")
        attempts = current["attempts"] + (1 if state == "running" else 0)
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET state=?, error=?, attempts=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, error, attempts, job_id))
        return self.get(job_id)

    def cancel(self, job_id: str) -> dict:
        return self.transition(job_id, "cancelled")

    def retry(self, job_id: str) -> dict:
        return self.transition(job_id, "queued")

    def claim_next(self) -> dict | None:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created_at, rowid LIMIT 1").fetchone()
            if not row: return None
            job_id = row[0]
            db.execute("UPDATE jobs SET state='running', attempts=attempts+1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        return self.get(job_id)
