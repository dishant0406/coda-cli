from __future__ import annotations

import gzip
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]


class StubCodaHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_text(self, payload: str, status: int = 200) -> None:
        encoded = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_bytes(self, payload: bytes, status: int = 200, *, content_type: str = "application/octet-stream", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/docs" and query.get("query") == ["example"]:
            self._send_json({"items": [{"id": "doc-1", "name": "Example Doc"}]})
            return

        if parsed.path == "/docs/doc-1":
            self._send_json({"id": "doc-1", "name": "Example Doc"})
            return

        if parsed.path == "/docs/doc-1/pages":
            self._send_json({"items": [{"id": "page-1", "name": "Example Page"}]})
            return

        if parsed.path == "/docs/doc-1/tables":
            self._send_json({"items": [{"id": "grid-1", "name": "Tasks"}]})
            return

        if parsed.path == "/docs/doc-1/tables/grid-1":
            self._send_json({"id": "grid-1", "name": "Tasks", "tableType": "table"})
            return

        if parsed.path == "/docs/doc-1/tables/grid-1/columns":
            self._send_json({"items": [{"id": "c-name", "name": "Name", "type": "text"}]})
            return

        if parsed.path == "/docs/doc-1/pages/page-1/export/export-1":
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            self._send_json({"status": "complete", "downloadLink": f"{base}/download/page-1.md"})
            return

        if parsed.path == "/download/page-1.md":
            self._send_bytes(
                gzip.compress(b"# Example Page\nBody"),
                content_type="text/markdown",
                headers={"Content-Encoding": "gzip"},
            )
            return

        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/docs/doc-1/pages/page-1/export":
            self._send_json({"id": "export-1"}, status=202)
            return

        self.send_error(404)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


class FullE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadedTCPServer(("127.0.0.1", 0), StubCodaHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.session_path = Path(self.tempdir.name) / "session.json"
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cli_bin = shutil.which("coda-cli")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def cli_command(self) -> list[str]:
        if self.cli_bin:
            return [self.cli_bin]
        return [sys.executable, "-m", "coda_cli"]

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CODA_API_KEY"] = "test-key"
        env["CODA_API_BASE_URL"] = self.base_url
        env["CODA_SESSION_PATH"] = str(self.session_path)
        env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
        env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
        return subprocess.run(
            [*self.cli_command(), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_docs_list_json(self) -> None:
        result = self.run_cli("docs", "list", "--query", "example", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["items"][0]["id"], "doc-1")

    def test_session_selection_is_used_by_tables_list(self) -> None:
        select = self.run_cli("docs", "use", "doc-1")
        self.assertEqual(select.returncode, 0, select.stderr)

        result = self.run_cli("--json", "tables", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["items"][0]["id"], "grid-1")

    def test_pages_get_uses_export_flow(self) -> None:
        result = self.run_cli("pages", "get", "page-1", "--doc-id", "doc-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Example Page", result.stdout)
        self.assertIn("Resolving page", result.stderr)

    def test_pages_find_shows_progress_while_fetching(self) -> None:
        result = self.run_cli("pages", "find", "Example", "--doc-id", "doc-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Example Page", result.stdout)
        self.assertIn("Fetching pages", result.stderr)

    def test_tables_schema_json(self) -> None:
        result = self.run_cli("--json", "tables", "schema", "grid-1", "--doc-id", "doc-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["table"]["id"], "grid-1")
        self.assertEqual(payload["columns"][0]["name"], "Name")


if __name__ == "__main__":
    unittest.main()
