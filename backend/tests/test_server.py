import io
import unittest
from pathlib import Path
from http import HTTPStatus

from server import Handler


class ServerRouteTests(unittest.TestCase):
    def test_spa_routes_fall_back_to_index(self):
        class TestHandler:
            web_root = Path(__file__).parents[2] / "web"

            def __init__(self):
                self.wfile = io.BytesIO()

            def send_response(self, status):
                self.status = status

            def send_header(self, *_args):
                pass

            def end_headers(self):
                pass

            def send_json(self, payload, status=HTTPStatus.OK):
                self.status = status
                self.wfile.write(str(payload).encode())

        for path in (
            "/library",
            "/library/2025/travel",
            "/assets/asset-1",
            "/jobs",
            "/jobs/job-1",
            "/jobs/thumbnail-generation",
            "/jobs/stacking",
            "/trash",
        ):
            with self.subTest(path=path):
                handler = TestHandler()
                Handler.static_file(handler, path)
                self.assertEqual(handler.status, HTTPStatus.OK)
                self.assertIn(b"No Waste Album", handler.wfile.getvalue())

        handler = TestHandler()
        Handler.static_file(handler, "/missing.js")
        self.assertEqual(handler.status, HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
