import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
