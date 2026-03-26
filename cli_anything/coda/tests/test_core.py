from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from cli_anything.coda.coda_cli import cli
from cli_anything.coda.core.state import SessionState, SessionStore
from cli_anything.coda.utils.coda_backend import CodaBackend


class FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload.encode("utf-8")

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
    def test_update_page_content_shapes_request(self) -> None:
        backend = CodaBackend(api_key="test-key")
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse("{}")

        with mock.patch("cli_anything.coda.utils.coda_backend.urlopen", side_effect=fake_urlopen):
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
            FakeResponse("# Heading\nBody"),
        ]

        with mock.patch("cli_anything.coda.utils.coda_backend.urlopen", side_effect=responses), mock.patch(
            "cli_anything.coda.utils.coda_backend.time.sleep", return_value=None
        ):
            content = backend.get_page_content("doc-1", "page-1")

        self.assertEqual(content, "# Heading\nBody")


class CliWorkflowTests(unittest.TestCase):
    def test_rows_update_fields_builds_cells_from_field_flags(self) -> None:
        runner = CliRunner()
        backend = mock.Mock()
        backend.update_row.return_value = {"ok": True}

        with runner.isolated_filesystem():
            session_path = Path("session.json")
            env = {"CODA_API_KEY": "test-key", "CODA_SESSION_PATH": str(session_path)}
            with mock.patch("cli_anything.coda.coda_cli.CodaBackend", return_value=backend):
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
            with mock.patch("cli_anything.coda.coda_cli.CodaBackend", return_value=backend):
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
