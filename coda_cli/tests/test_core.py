from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from coda_cli.coda_cli import cli
from coda_cli.core.state import SessionState, SessionStore
from coda_cli.utils.coda_backend import CodaApiError, CodaBackend


class FakeResponse:
    def __init__(self, payload: bytes | str, headers: dict[str, str] | None = None):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.payload = payload
        self.headers = headers or {}

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class SessionStoreTests(unittest.TestCase):
    def test_undo_and_redo_restore_selection_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(Path(tmpdir) / "session.json")
            state = store.load()

            store.mutate(state, current_doc_id="doc-1", current_table_id=None, current_page_id=None)
            store.mutate(state, current_doc_id="doc-1", current_table_id="grid-1", current_page_id=None)

            self.assertEqual(state.current_doc_id, "doc-1")
            self.assertEqual(state.current_table_id, "grid-1")

            self.assertTrue(store.undo(state))
            self.assertEqual(state.current_doc_id, "doc-1")
            self.assertIsNone(state.current_table_id)

            self.assertTrue(store.redo(state))
            self.assertEqual(state.current_table_id, "grid-1")

    def test_last_result_persists_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.json"
            store = SessionStore(path)
            state = SessionState()
            store.set_last_result(state, {"ok": True})

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["last_result"], {"ok": True})


class CodaBackendTests(unittest.TestCase):
    def test_requests_default_to_no_timeout(self) -> None:
        backend = CodaBackend(api_key="test-key")
        captured = {}

        def fake_urlopen(request, timeout, context=None):
            captured["timeout"] = timeout
            return FakeResponse("{}")

        with mock.patch("coda_cli.utils.coda_backend.urlopen", side_effect=fake_urlopen):
            backend.list_documents()

        self.assertIsNone(captured["timeout"])

    def test_update_page_content_shapes_request(self) -> None:
        backend = CodaBackend(api_key="test-key")
        captured = {}

        def fake_urlopen(request, timeout, context=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse("{}")

        with mock.patch("coda_cli.utils.coda_backend.urlopen", side_effect=fake_urlopen):
            backend.update_page_content("doc-1", "page-1", "# Updated", insertion_mode="append", element_id="el-1")

        self.assertEqual(captured["method"], "PUT")
        self.assertIn("/docs/doc-1/pages/page-1", captured["url"])
        self.assertEqual(captured["body"]["contentUpdate"]["insertionMode"], "append")
        self.assertEqual(captured["body"]["contentUpdate"]["elementId"], "el-1")

    def test_get_page_content_polls_until_download(self) -> None:
        backend = CodaBackend(api_key="test-key", export_poll_interval=0, export_max_attempts=3)
        responses = [
            FakeResponse(json.dumps({"id": "export-1"})),
            FakeResponse(json.dumps({"status": "inProgress"})),
            FakeResponse(json.dumps({"status": "complete", "downloadLink": "http://download.local/file.md"})),
            FakeResponse(gzip.compress(b"# Heading\nBody"), headers={"Content-Encoding": "gzip"}),
        ]

        with mock.patch("coda_cli.utils.coda_backend.urlopen", side_effect=responses), mock.patch(
            "coda_cli.utils.coda_backend.time.sleep", return_value=None
        ):
            content = backend.get_page_content("doc-1", "page-1")

        self.assertEqual(content, "# Heading\nBody")

    def test_get_page_content_raises_clean_decode_error(self) -> None:
        backend = CodaBackend(api_key="test-key", export_poll_interval=0, export_max_attempts=1)
        responses = [
            FakeResponse(json.dumps({"id": "export-1"})),
            FakeResponse(json.dumps({"status": "complete", "downloadLink": "http://download.local/file.md"})),
            FakeResponse(b"\xff\xfe\xfd"),
        ]

        with mock.patch("coda_cli.utils.coda_backend.urlopen", side_effect=responses):
            with self.assertRaises(CodaApiError) as context:
                backend.get_page_content("doc-1", "page-1")

        self.assertIn("Failed to decode exported page markdown as UTF-8 text.", str(context.exception))


class CliWorkflowTests(unittest.TestCase):
    def test_docs_list_accepts_json_after_subcommand(self) -> None:
        runner = CliRunner()
        backend = mock.Mock()
        backend.list_documents.return_value = {"items": [{"id": "doc-1", "name": "Example"}]}

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_API_KEY": "test-key", "CODA_SESSION_PATH": str(session_path)}
            with mock.patch("coda_cli.coda_cli.CodaBackend", return_value=backend):
                result = runner.invoke(cli, ["docs", "list", "--json"], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["items"][0]["id"], "doc-1")

    def test_docs_use_accepts_dash_prefixed_ids_via_option(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_SESSION_PATH": str(session_path)}
            result = runner.invoke(cli, ["docs", "use", "--doc-id", "-LNk7c4rKF", "--json"], env=env)

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["current_doc_id"], "-LNk7c4rKF")

            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["current_doc_id"], "-LNk7c4rKF")

    def test_pages_find_filters_across_paths(self) -> None:
        runner = CliRunner()
        backend = mock.Mock()
        backend.list_all_pages.return_value = {
            "items": [
                {"id": "page-1", "name": "Engineering"},
                {"id": "page-2", "name": "GrowwBot SDK", "parent": {"id": "page-1", "name": "Engineering"}},
            ]
        }

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_API_KEY": "test-key", "CODA_SESSION_PATH": str(session_path)}
            SessionStore(session_path).save(SessionState(current_doc_id="doc-1"))
            with mock.patch("coda_cli.coda_cli.CodaBackend", return_value=backend):
                result = runner.invoke(cli, ["pages", "find", "growwbot", "--json"], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["items"][0]["path"], "Engineering/GrowwBot SDK")

    def test_pages_get_rejects_ambiguous_page_names(self) -> None:
        runner = CliRunner()
        backend = mock.Mock()
        backend.list_all_pages.return_value = {
            "items": [
                {"id": "page-1", "name": "Watchlist", "parent": {"id": "root-1", "name": "Web Team"}},
                {"id": "page-2", "name": "Watchlist", "parent": {"id": "root-2", "name": "Mobile Team"}},
            ]
        }

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_API_KEY": "test-key", "CODA_SESSION_PATH": str(session_path)}
            SessionStore(session_path).save(SessionState(current_doc_id="doc-1"))
            with mock.patch("coda_cli.coda_cli.CodaBackend", return_value=backend):
                result = runner.invoke(cli, ["pages", "get", "Watchlist"], env=env)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("ambiguous", result.output.casefold())
        self.assertIn("Web Team/Watchlist", result.output)

    def test_rows_update_fields_builds_cells_from_field_flags(self) -> None:
        runner = CliRunner()
        backend = mock.Mock()
        backend.update_row.return_value = {"ok": True}

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_API_KEY": "test-key", "CODA_SESSION_PATH": str(session_path)}
            with mock.patch("coda_cli.coda_cli.CodaBackend", return_value=backend):
                result = runner.invoke(
                    cli,
                    [
                        "rows",
                        "update-fields",
                        "row-1",
                        "--doc-id",
                        "doc-1",
                        "--table-id",
                        "grid-1",
                        "--field",
                        'Status="Done"',
                        "--field",
                        "Points=3",
                    ],
                    env=env,
                )

        self.assertEqual(result.exit_code, 0, result.output)
        backend.update_row.assert_called_once_with(
            "doc-1",
            "grid-1",
            "row-1",
            cells=[
                {"column": "Status", "value": "Done"},
                {"column": "Points", "value": 3},
            ],
            disable_parsing=False,
        )

    def test_tables_schema_combines_table_and_columns(self) -> None:
        runner = CliRunner()
        backend = mock.Mock()
        backend.get_table.return_value = {"id": "grid-1", "name": "Tasks", "tableType": "table"}
        backend.list_columns.return_value = {
            "items": [
                {"id": "c-name", "name": "Name", "type": "text"},
                {"id": "c-status", "name": "Status", "type": "select"},
            ]
        }

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_API_KEY": "test-key", "CODA_SESSION_PATH": str(session_path)}
            with mock.patch("coda_cli.coda_cli.CodaBackend", return_value=backend):
                result = runner.invoke(
                    cli,
                    ["--json", "tables", "schema", "--doc-id", "doc-1", "grid-1"],
                    env=env,
                )

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["table"]["id"], "grid-1")
        self.assertEqual(len(payload["columns"]), 2)


if __name__ == "__main__":
    unittest.main()
