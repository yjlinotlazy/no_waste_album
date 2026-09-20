import tempfile
import unittest
import sqlite3
from pathlib import Path

from backend.jobs import JobStore


class JobTests(unittest.TestCase):
    def test_job_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite")
            job = store.create("analysis", {"asset_ids": ["a"]})
            self.assertEqual(job["state"], "queued")
            self.assertEqual(store.transition(job["id"], "running")["attempts"], 1)
            self.assertEqual(store.transition(job["id"], "completed")["state"], "completed")

    def test_invalid_transition_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite")
            job = store.create("indexing")
            with self.assertRaises(ValueError):
                store.transition(job["id"], "completed")

    def test_stale_running_job_is_reconciled_as_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite"
            store = JobStore(path)
            running = store.transition(store.create("analysis")["id"], "running")
            queued = store.create("indexing")
            with sqlite3.connect(path) as db:
                db.execute("UPDATE jobs SET updated_at=datetime('now', '-10 minutes') WHERE id=?", (running["id"],))
            self.assertEqual(store.reconcile_stale(60), 1)
            self.assertEqual(store.get(running["id"])["state"], "failed")
            self.assertEqual(store.get(running["id"])["error"], "worker interrupted")
            self.assertEqual(store.get(queued["id"])["state"], "queued")


if __name__ == "__main__":
    unittest.main()
