from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import click

from cli_anything.coda.core.repl import run_repl
from cli_anything.coda.core.state import DEFAULT_API_BASE_URL, SessionState, SessionStore, default_session_path
from cli_anything.coda.utils.coda_backend import CodaApiError, CodaBackend


@dataclass
class AppContext:
    json_output: bool
    store: SessionStore
    state: SessionState
    session_path: Path
    backend: Optional[CodaBackend]


def main() -> None:
    try:
        cli()
    except CodaApiError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--api-key", envvar=["CODA_API_KEY", "API_KEY"], help="Coda API key.")
@click.option(
    "--api-base-url",
    envvar="CODA_API_BASE_URL",
    default=None,
    help=f"Override the Coda API base URL. Defaults to {DEFAULT_API_BASE_URL}.",
)
@click.option(
    "--session-path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to the local session file.",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output for automation.")
@click.pass_context
def cli(
    ctx: click.Context,
    api_key: Optional[str],
    api_base_url: Optional[str],
    session_path: Optional[Path],
    json_output: bool,
) -> None:
    resolved_session_path = session_path or default_session_path()
    store = SessionStore(resolved_session_path)
    state = store.load()
    resolved_api_base_url = api_base_url or state.api_base_url or DEFAULT_API_BASE_URL
    if state.api_base_url != resolved_api_base_url:
        state.api_base_url = resolved_api_base_url
        store.save(state)

    backend = CodaBackend(api_key=api_key, api_base_url=resolved_api_base_url) if api_key else None
    ctx.obj = AppContext(
        json_output=json_output,
        store=store,
        state=state,
        session_path=resolved_session_path,
        backend=backend,
    )

    if ctx.invoked_subcommand is None:
        run_repl(cli, ctx.obj, ctx.info_name or "cli-anything-coda")


def emit(app: AppContext, payload: Any, text: Optional[str] = None) -> None:
    app.store.set_last_result(app.state, payload)
    if app.json_output:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if text is None:
        text = json.dumps(payload, indent=2, sort_keys=True)
    click.echo(text)


def require_backend(app: AppContext) -> CodaBackend:
    if app.backend is None:
        raise click.ClickException("Missing API key. Pass --api-key or set CODA_API_KEY/API_KEY.")
    return app.backend


def resolve_doc_id(app: AppContext, doc_id: Optional[str]) -> str:
    resolved = doc_id or app.state.current_doc_id
    if not resolved:
        raise click.ClickException("A document id is required. Pass --doc-id or select one with `docs use`.")
    return resolved


def resolve_table_id(app: AppContext, table_id_or_name: Optional[str]) -> str:
    resolved = table_id_or_name or app.state.current_table_id
    if not resolved:
        raise click.ClickException("A table id is required. Pass it explicitly or select one with `tables use`.")
    return resolved


def parse_json_input(raw: Optional[str], file_path: Optional[Path], label: str) -> Any:
    if bool(raw) == bool(file_path):
        raise click.ClickException(f"Provide exactly one of {label} inline JSON or {label} file input.")

    try:
        text = raw if raw is not None else file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Failed to read {label} file: {exc}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{label} is not valid JSON: {exc}") from exc


def parse_text_input(raw: Optional[str], file_path: Optional[Path], label: str) -> str:
    if bool(raw) == bool(file_path):
        raise click.ClickException(f"Provide exactly one of {label} text or {label} file input.")

    if raw is not None:
        return raw

    try:
        return file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Failed to read {label} file: {exc}") from exc


def parse_field_assignments(assignments: tuple[str, ...], label: str = "field") -> list[dict[str, Any]]:
    cells = []
    for assignment in assignments:
        if "=" not in assignment:
            raise click.ClickException(f"{label} assignments must look like COLUMN=JSON_VALUE.")
        column, raw_value = assignment.split("=", 1)
        column = column.strip()
        if not column:
            raise click.ClickException(f"{label} assignments must include a column name before '='.")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"{label} value for {column!r} is not valid JSON: {exc}") from exc
        cells.append({"column": column, "value": value})

    if not cells:
        raise click.ClickException(f"Provide at least one --{label}.")

    return cells


def set_selection(
    app: AppContext,
    *,
    doc_id: Optional[str] = None,
    table_id: Optional[str] = None,
    page_id: Optional[str] = None,
) -> None:
    app.store.mutate(
        app.state,
        current_doc_id=doc_id,
        current_table_id=table_id,
        current_page_id=page_id,
    )


def render_named_items(items: list[dict[str, Any]], label: str) -> str:
    if not items:
        return f"No {label} found."
    lines = []
    for item in items:
        name = item.get("name") or item.get("displayName") or "<unnamed>"
        item_id = item.get("id") or item.get("rowId") or "<no-id>"
        lines.append(f"{name} ({item_id})")
    return "\n".join(lines)


@cli.group()
def docs() -> None:
    """Document operations."""


@docs.command("list")
@click.option("--query", default=None, help="Optional search query.")
@click.pass_obj
def docs_list(app: AppContext, query: Optional[str]) -> None:
    backend = require_backend(app)
    payload = backend.list_documents(query=query)
    emit(app, payload, render_named_items(payload.get("items", []), "documents"))


@docs.command("use")
@click.argument("doc_id")
@click.pass_obj
def docs_use(app: AppContext, doc_id: str) -> None:
    set_selection(app, doc_id=doc_id, table_id=None, page_id=None)
    emit(app, {"current_doc_id": doc_id}, f"Current document: {doc_id}")


@cli.group()
def pages() -> None:
    """Page operations."""


@pages.command("list")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--limit", type=int, default=None)
@click.option("--next-page-token", default=None)
@click.pass_obj
def pages_list(app: AppContext, doc_id: Optional[str], limit: Optional[int], next_page_token: Optional[str]) -> None:
    backend = require_backend(app)
    payload = backend.list_pages(resolve_doc_id(app, doc_id), limit=limit, next_page_token=next_page_token)
    emit(app, payload, render_named_items(payload.get("items", []), "pages"))


@pages.command("use")
@click.argument("page_id")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def pages_use(app: AppContext, page_id: str, doc_id: Optional[str]) -> None:
    resolved_doc_id = resolve_doc_id(app, doc_id)
    set_selection(app, doc_id=resolved_doc_id, table_id=app.state.current_table_id, page_id=page_id)
    emit(app, {"current_doc_id": resolved_doc_id, "current_page_id": page_id}, f"Current page: {page_id}")


@pages.command("create")
@click.argument("name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--parent-page-id", default=None)
@click.option("--content", default=None, help="Inline markdown content.")
@click.option("--file", "content_file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.pass_obj
def pages_create(
    app: AppContext,
    name: str,
    doc_id: Optional[str],
    parent_page_id: Optional[str],
    content: Optional[str],
    content_file: Optional[Path],
) -> None:
    backend = require_backend(app)
    if content is not None or content_file is not None:
        content_value = parse_text_input(content, content_file, "page content")
    else:
        content_value = None
    payload = backend.create_page(resolve_doc_id(app, doc_id), name, content=content_value, parent_page_id=parent_page_id)
    emit(app, payload)


@pages.command("get")
@click.argument("page_id_or_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def pages_get(app: AppContext, page_id_or_name: str, doc_id: Optional[str]) -> None:
    backend = require_backend(app)
    content = backend.get_page_content(resolve_doc_id(app, doc_id), page_id_or_name)
    emit(app, {"content": content, "page": page_id_or_name}, content)


@pages.command("peek")
@click.argument("page_id_or_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--lines", "num_lines", type=int, default=30, show_default=True)
@click.pass_obj
def pages_peek(app: AppContext, page_id_or_name: str, doc_id: Optional[str], num_lines: int) -> None:
    backend = require_backend(app)
    content = backend.get_page_content(resolve_doc_id(app, doc_id), page_id_or_name)
    preview = "\n".join(content.splitlines()[:num_lines])
    emit(app, {"content": preview, "page": page_id_or_name, "lines": num_lines}, preview)


@pages.command("update-content")
@click.argument("page_id_or_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option(
    "--mode",
    "insertion_mode",
    type=click.Choice(["append", "prepend", "replace"], case_sensitive=False),
    default="replace",
    show_default=True,
)
@click.option("--element-id", default=None, help="Optional element id for relative content edits.")
@click.option("--content", default=None, help="Inline markdown content.")
@click.option("--file", "content_file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.pass_obj
def pages_update_content(
    app: AppContext,
    page_id_or_name: str,
    doc_id: Optional[str],
    insertion_mode: str,
    element_id: Optional[str],
    content: Optional[str],
    content_file: Optional[Path],
) -> None:
    backend = require_backend(app)
    content_value = parse_text_input(content, content_file, "page content")
    payload = backend.update_page_content(
        resolve_doc_id(app, doc_id),
        page_id_or_name,
        content_value,
        insertion_mode=insertion_mode,
        element_id=element_id,
    )
    emit(app, payload)


@pages.command("duplicate")
@click.argument("page_id_or_name")
@click.argument("new_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def pages_duplicate(app: AppContext, page_id_or_name: str, new_name: str, doc_id: Optional[str]) -> None:
    backend = require_backend(app)
    payload = backend.duplicate_page(resolve_doc_id(app, doc_id), page_id_or_name, new_name)
    emit(app, payload)


@pages.command("rename")
@click.argument("page_id_or_name")
@click.argument("new_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def pages_rename(app: AppContext, page_id_or_name: str, new_name: str, doc_id: Optional[str]) -> None:
    backend = require_backend(app)
    payload = backend.rename_page(resolve_doc_id(app, doc_id), page_id_or_name, new_name)
    emit(app, payload)


@pages.command("copy-content")
@click.argument("source_page_id_or_name")
@click.argument("target_page_id_or_name")
@click.option("--doc-id", default=None, help="Source document id. Falls back to the current session doc.")
@click.option("--target-doc-id", default=None, help="Target document id. Defaults to the source doc.")
@click.option(
    "--mode",
    "insertion_mode",
    type=click.Choice(["append", "prepend", "replace"], case_sensitive=False),
    default="replace",
    show_default=True,
)
@click.option("--target-element-id", default=None, help="Optional target element id for relative content edits.")
@click.pass_obj
def pages_copy_content(
    app: AppContext,
    source_page_id_or_name: str,
    target_page_id_or_name: str,
    doc_id: Optional[str],
    target_doc_id: Optional[str],
    insertion_mode: str,
    target_element_id: Optional[str],
) -> None:
    backend = require_backend(app)
    source_doc_id = resolve_doc_id(app, doc_id)
    resolved_target_doc_id = target_doc_id or source_doc_id
    content = backend.get_page_content(source_doc_id, source_page_id_or_name)
    result = backend.update_page_content(
        resolved_target_doc_id,
        target_page_id_or_name,
        content,
        insertion_mode=insertion_mode,
        element_id=target_element_id,
    )
    emit(
        app,
        {
            "source_doc_id": source_doc_id,
            "source_page_id_or_name": source_page_id_or_name,
            "target_doc_id": resolved_target_doc_id,
            "target_page_id_or_name": target_page_id_or_name,
            "result": result,
        },
    )


@cli.group()
def tables() -> None:
    """Table operations."""


@tables.command("list")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--limit", type=int, default=None)
@click.option("--next-page-token", default=None)
@click.option("--sort-by", type=click.Choice(["createdAt", "natural", "updatedAt"], case_sensitive=False), default=None)
@click.option("--table-type", "table_types", multiple=True, type=click.Choice(["table", "view"], case_sensitive=False))
@click.pass_obj
def tables_list(
    app: AppContext,
    doc_id: Optional[str],
    limit: Optional[int],
    next_page_token: Optional[str],
    sort_by: Optional[str],
    table_types: tuple[str, ...],
) -> None:
    backend = require_backend(app)
    payload = backend.list_tables(
        resolve_doc_id(app, doc_id),
        limit=limit,
        next_page_token=next_page_token,
        sort_by=sort_by,
        table_types=list(table_types) or None,
    )
    emit(app, payload, render_named_items(payload.get("items", []), "tables"))


@tables.command("use")
@click.argument("table_id")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def tables_use(app: AppContext, table_id: str, doc_id: Optional[str]) -> None:
    resolved_doc_id = resolve_doc_id(app, doc_id)
    set_selection(app, doc_id=resolved_doc_id, table_id=table_id, page_id=app.state.current_page_id)
    emit(app, {"current_doc_id": resolved_doc_id, "current_table_id": table_id}, f"Current table: {table_id}")


@tables.command("columns")
@click.argument("table_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--limit", type=int, default=None)
@click.option("--next-page-token", default=None)
@click.option("--visible-only/--all-columns", default=None)
@click.pass_obj
def tables_columns(
    app: AppContext,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    limit: Optional[int],
    next_page_token: Optional[str],
    visible_only: Optional[bool],
) -> None:
    backend = require_backend(app)
    payload = backend.list_columns(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        limit=limit,
        next_page_token=next_page_token,
        visible_only=visible_only,
    )
    emit(app, payload, render_named_items(payload.get("items", []), "columns"))


@tables.command("schema")
@click.argument("table_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--visible-only/--all-columns", default=None)
@click.option("--updated-layouts", is_flag=True, default=False, help="Request updated detail/form layout labels.")
@click.pass_obj
def tables_schema(
    app: AppContext,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    visible_only: Optional[bool],
    updated_layouts: bool,
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    resolved_table_id = resolve_table_id(app, table_id_or_name)
    table = backend.get_table(resolved_doc_id, resolved_table_id, use_updated_table_layouts=updated_layouts)
    columns = backend.list_columns(resolved_doc_id, resolved_table_id, visible_only=visible_only)
    payload = {"table": table, "columns": columns.get("items", [])}
    if app.json_output:
        emit(app, payload)
        return

    lines = [
        f"Table: {table.get('name', '<unnamed>')} ({table.get('id', resolved_table_id)})",
        f"Type: {table.get('tableType', table.get('type', 'unknown'))}",
        "Columns:",
    ]
    for column in columns.get("items", []):
        lines.append(
            f"- {column.get('name', '<unnamed>')} ({column.get('id', '<no-id>')}) [{column.get('type', 'unknown')}]"
        )
    emit(app, payload, "\n".join(lines))


@cli.group()
def rows() -> None:
    """Row operations."""


@rows.command("list")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--query", default=None, help='Coda row query, for example "Status":"Open".')
@click.option("--sort-by", type=click.Choice(["createdAt", "natural", "updatedAt"], case_sensitive=False), default=None)
@click.option("--use-column-names/--use-column-ids", default=True)
@click.option("--value-format", type=click.Choice(["simple", "simpleWithArrays", "rich"], case_sensitive=False), default="rich")
@click.option("--visible-only/--all-rows", default=None)
@click.option("--limit", type=int, default=None)
@click.option("--next-page-token", default=None)
@click.option("--sync-token", default=None)
@click.pass_obj
def rows_list(
    app: AppContext,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    query: Optional[str],
    sort_by: Optional[str],
    use_column_names: bool,
    value_format: str,
    visible_only: Optional[bool],
    limit: Optional[int],
    next_page_token: Optional[str],
    sync_token: Optional[str],
) -> None:
    backend = require_backend(app)
    payload = backend.list_rows(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        query=query,
        sort_by=sort_by,
        use_column_names=use_column_names,
        value_format=value_format,
        visible_only=visible_only,
        limit=limit,
        next_page_token=next_page_token,
        sync_token=sync_token,
    )
    emit(app, payload, render_named_items(payload.get("items", []), "rows"))


@rows.command("get")
@click.argument("row_id_or_name")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--use-column-names/--use-column-ids", default=True)
@click.option("--value-format", type=click.Choice(["simple", "simpleWithArrays", "rich"], case_sensitive=False), default="rich")
@click.pass_obj
def rows_get(
    app: AppContext,
    table_id_or_name: Optional[str],
    row_id_or_name: str,
    doc_id: Optional[str],
    use_column_names: bool,
    value_format: str,
) -> None:
    backend = require_backend(app)
    payload = backend.get_row(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        row_id_or_name,
        use_column_names=use_column_names,
        value_format=value_format,
    )
    emit(app, payload)


@rows.command("upsert")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--rows", "rows_json", default=None, help="Inline JSON array of rows.")
@click.option("--rows-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.option("--key-columns", default=None, help="Inline JSON array of key columns.")
@click.option("--key-columns-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.option("--disable-parsing", is_flag=True, default=False)
@click.pass_obj
def rows_upsert(
    app: AppContext,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    rows_json: Optional[str],
    rows_file: Optional[Path],
    key_columns: Optional[str],
    key_columns_file: Optional[Path],
    disable_parsing: bool,
) -> None:
    backend = require_backend(app)
    rows_value = parse_json_input(rows_json, rows_file, "rows")
    key_columns_value = None
    if key_columns is not None or key_columns_file is not None:
        key_columns_value = parse_json_input(key_columns, key_columns_file, "key columns")
    payload = backend.upsert_rows(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        rows=rows_value,
        key_columns=key_columns_value,
        disable_parsing=disable_parsing,
    )
    emit(app, payload)


@rows.command("update")
@click.argument("row_id_or_name")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--cells", default=None, help="Inline JSON array of cell edits.")
@click.option("--cells-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.option("--disable-parsing", is_flag=True, default=False)
@click.pass_obj
def rows_update(
    app: AppContext,
    table_id_or_name: Optional[str],
    row_id_or_name: str,
    doc_id: Optional[str],
    cells: Optional[str],
    cells_file: Optional[Path],
    disable_parsing: bool,
) -> None:
    backend = require_backend(app)
    payload = backend.update_row(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        row_id_or_name,
        cells=parse_json_input(cells, cells_file, "cells"),
        disable_parsing=disable_parsing,
    )
    emit(app, payload)


@rows.command("update-fields")
@click.argument("row_id_or_name")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option(
    "--field",
    "fields",
    multiple=True,
    help='Repeatable field assignment in the form COLUMN=JSON_VALUE, for example --field Status="Done".',
)
@click.option("--disable-parsing", is_flag=True, default=False)
@click.pass_obj
def rows_update_fields(
    app: AppContext,
    row_id_or_name: str,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    fields: tuple[str, ...],
    disable_parsing: bool,
) -> None:
    backend = require_backend(app)
    payload = backend.update_row(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        row_id_or_name,
        cells=parse_field_assignments(fields),
        disable_parsing=disable_parsing,
    )
    emit(app, payload)


@rows.command("upsert-one")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option(
    "--field",
    "fields",
    multiple=True,
    help='Repeatable field assignment in the form COLUMN=JSON_VALUE, for example --field Name="Alice".',
)
@click.option(
    "--key-column",
    "key_columns",
    multiple=True,
    help="Optional repeatable key column for upsert matching.",
)
@click.option("--disable-parsing", is_flag=True, default=False)
@click.pass_obj
def rows_upsert_one(
    app: AppContext,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    fields: tuple[str, ...],
    key_columns: tuple[str, ...],
    disable_parsing: bool,
) -> None:
    backend = require_backend(app)
    row = {"cells": parse_field_assignments(fields)}
    payload = backend.upsert_rows(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        rows=[row],
        key_columns=list(key_columns) or None,
        disable_parsing=disable_parsing,
    )
    emit(app, payload)


@rows.command("delete")
@click.argument("row_id_or_name")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def rows_delete(app: AppContext, table_id_or_name: Optional[str], row_id_or_name: str, doc_id: Optional[str]) -> None:
    backend = require_backend(app)
    payload = backend.delete_row(resolve_doc_id(app, doc_id), resolve_table_id(app, table_id_or_name), row_id_or_name)
    emit(app, payload)


@rows.command("delete-many")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--row-ids", default=None, help="Inline JSON array of row ids.")
@click.option("--row-ids-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@click.pass_obj
def rows_delete_many(
    app: AppContext,
    table_id_or_name: Optional[str],
    doc_id: Optional[str],
    row_ids: Optional[str],
    row_ids_file: Optional[Path],
) -> None:
    backend = require_backend(app)
    payload = backend.delete_rows(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        row_ids=parse_json_input(row_ids, row_ids_file, "row ids"),
    )
    emit(app, payload)


@rows.command("push-button")
@click.argument("row_id_or_name")
@click.argument("column_id_or_name")
@click.option("--table-id", "table_id_or_name", default=None, help="Table id or name. Falls back to the current session table.")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.pass_obj
def rows_push_button(
    app: AppContext,
    table_id_or_name: Optional[str],
    row_id_or_name: str,
    column_id_or_name: str,
    doc_id: Optional[str],
) -> None:
    backend = require_backend(app)
    payload = backend.push_button(
        resolve_doc_id(app, doc_id),
        resolve_table_id(app, table_id_or_name),
        row_id_or_name,
        column_id_or_name,
    )
    emit(app, payload)


@cli.group()
def links() -> None:
    """Link helpers."""


@links.command("resolve")
@click.argument("url")
@click.option("--degrade-gracefully", is_flag=True, default=False)
@click.pass_obj
def links_resolve(app: AppContext, url: str, degrade_gracefully: bool) -> None:
    backend = require_backend(app)
    payload = backend.resolve_link(url, degrade_gracefully=degrade_gracefully)
    emit(app, payload)


@cli.group()
def session() -> None:
    """Local session state."""


@session.command("show")
@click.pass_obj
def session_show(app: AppContext) -> None:
    emit(
        app,
        {
            "session_path": str(app.session_path),
            "api_base_url": app.state.api_base_url,
            "current_doc_id": app.state.current_doc_id,
            "current_table_id": app.state.current_table_id,
            "current_page_id": app.state.current_page_id,
            "history_depth": len(app.state.history),
            "future_depth": len(app.state.future),
        },
    )


@session.command("last")
@click.pass_obj
def session_last(app: AppContext) -> None:
    emit(app, {"last_result": app.state.last_result})


@session.command("clear")
@click.pass_obj
def session_clear(app: AppContext) -> None:
    set_selection(app, doc_id=None, table_id=None, page_id=None)
    emit(app, {"current_doc_id": None, "current_table_id": None, "current_page_id": None}, "Session selection cleared.")


@session.command("undo")
@click.pass_obj
def session_undo(app: AppContext) -> None:
    if not app.store.undo(app.state):
        raise click.ClickException("There is no session state to undo.")
    emit(app, app.state.snapshot(), "Session selection restored to the previous state.")


@session.command("redo")
@click.pass_obj
def session_redo(app: AppContext) -> None:
    if not app.store.redo(app.state):
        raise click.ClickException("There is no session state to redo.")
    emit(app, app.state.snapshot(), "Session selection restored to the next state.")
