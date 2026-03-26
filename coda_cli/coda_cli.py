from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import click

from coda_cli.core.repl import run_repl
from coda_cli.core.state import DEFAULT_API_BASE_URL, SessionState, SessionStore, default_session_path
from coda_cli.utils.coda_backend import CodaApiError, CodaBackend


@dataclass
class AppContext:
    json_output: bool
    store: SessionStore
    state: SessionState
    session_path: Path
    backend: Optional[CodaBackend]


def main() -> None:
    try:
        os.environ.setdefault("NODE_TLS_REJECT_UNAUTHORIZED", "0")
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
    json_output = json_output or bool(ctx.meta.get("json_output_override"))
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
        run_repl(cli, ctx.obj, ctx.info_name or "coda-cli")


def emit(app: AppContext, payload: Any, text: Optional[str] = None) -> None:
    app.store.set_last_result(app.state, payload)
    if app.json_output:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if text is None:
        text = json.dumps(payload, indent=2, sort_keys=True)
    click.echo(text)


def json_option(command: Callable[..., Any]) -> Callable[..., Any]:
    return click.option(
        "--json",
        "json_output",
        is_flag=True,
        expose_value=False,
        help="Emit JSON output for automation.",
        callback=_enable_json_output,
    )(command)


def _enable_json_output(ctx: click.Context, param: click.Parameter, value: bool) -> bool:
    if value:
        root_ctx = ctx.find_root()
        root_ctx.meta["json_output_override"] = True
        app = root_ctx.obj
        if isinstance(app, AppContext):
            app.json_output = True
    return value


def emit_progress(app: AppContext, message: str) -> None:
    if not app.json_output:
        click.echo(message, err=True)


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


def resolve_required_value(
    direct_value: Optional[str],
    option_value: Optional[str],
    current_value: Optional[str],
    label: str,
    *,
    option_name: str,
    use_session_hint: Optional[str] = None,
) -> str:
    if direct_value and option_value:
        raise click.ClickException(f"Pass either {label} or {option_name}, not both.")

    resolved = option_value or direct_value or current_value
    if resolved:
        return resolved

    hint = f" or select one with `{use_session_hint}`" if use_session_hint else ""
    raise click.ClickException(f"A {label} is required. Pass it explicitly with {option_name}{hint}.")


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


def page_name(page: dict[str, Any]) -> str:
    return str(page.get("name") or page.get("displayName") or "<unnamed>")


def page_id(page: dict[str, Any]) -> str:
    return str(page.get("id") or "<no-id>")


def page_parent_id(page: dict[str, Any]) -> Optional[str]:
    for key in ("parent", "parentPage"):
        value = page.get(key)
        if isinstance(value, dict) and value.get("id"):
            return str(value["id"])
    for key in ("parentPageId", "parentId"):
        value = page.get(key)
        if value:
            return str(value)
    return None


def page_parent_name(page: dict[str, Any]) -> Optional[str]:
    for key in ("parent", "parentPage"):
        value = page.get(key)
        if isinstance(value, dict):
            name = value.get("name") or value.get("displayName")
            if name:
                return str(name)
    return None


def page_author_name(page: dict[str, Any]) -> Optional[str]:
    for key in ("author", "owner", "createdBy", "updatedBy"):
        value = page.get(key)
        if isinstance(value, dict):
            author = value.get("name") or value.get("email") or value.get("id")
            if author:
                return str(author)
        elif isinstance(value, str) and value:
            return value
    return None


def page_child_count(page: dict[str, Any]) -> Optional[int]:
    children = page.get("children")
    if isinstance(children, list):
        return len(children)
    if isinstance(children, dict) and isinstance(children.get("items"), list):
        return len(children["items"])
    return None


def build_page_lookup(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {page_id(item): item for item in pages if item.get("id")}


def normalize_page_path(value: str) -> str:
    return "/".join(segment.strip() for segment in value.split("/") if segment.strip()).casefold()


def build_page_path(page: dict[str, Any], page_lookup: dict[str, dict[str, Any]]) -> str:
    segments: list[str] = []
    current = page
    seen: set[str] = set()

    while True:
        current_id = page_id(current)
        if current_id in seen:
            break
        seen.add(current_id)
        segments.append(page_name(current))

        parent_id = page_parent_id(current)
        if parent_id and parent_id in page_lookup:
            current = page_lookup[parent_id]
            continue

        parent_name = page_parent_name(current)
        if parent_name:
            segments.append(parent_name)
        break

    return "/".join(reversed(segments))


def page_summary(page: dict[str, Any], page_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": page.get("id"),
        "name": page_name(page),
        "path": build_page_path(page, page_lookup),
        "parent_id": page_parent_id(page),
        "parent_name": page_parent_name(page),
        "updated_at": page.get("updatedAt"),
        "author": page_author_name(page),
        "is_hidden": page.get("isHidden"),
        "child_count": page_child_count(page),
    }


def render_page_items(items: list[dict[str, Any]], *, long_mode: bool = False) -> str:
    if not items:
        return "No pages found."

    page_lookup = build_page_lookup(items)
    lines = []
    for item in items:
        summary = page_summary(item, page_lookup)
        base = f"{summary['path']} ({summary['id'] or '<no-id>'})"
        if not long_mode:
            lines.append(base)
            continue
        lines.append(
            " | ".join(
                [
                    base,
                    f"parent={summary['parent_name'] or '-'}",
                    f"updated={summary['updated_at'] or '-'}",
                    f"author={summary['author'] or '-'}",
                    f"hidden={summary['is_hidden'] if summary['is_hidden'] is not None else '-'}",
                    f"children={summary['child_count'] if summary['child_count'] is not None else '-'}",
                ]
            )
        )
    return "\n".join(lines)


def render_page_matches(matches: list[dict[str, Any]], label: str) -> str:
    if not matches:
        return f"No {label} found."
    return "\n".join(f"- {match['path']} ({match['id']})" for match in matches)


def resolve_page_matches(
    pages: list[dict[str, Any]],
    page_ref: Optional[str],
    page_path: Optional[str],
    *,
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    page_lookup = build_page_lookup(pages)
    if page_path:
        normalized_target = normalize_page_path(page_path)
        matches = [page for page in pages if normalize_page_path(build_page_path(page, page_lookup)) == normalized_target]
        return matches, page_lookup

    if not page_ref:
        return [], page_lookup

    exact_id_matches = [page for page in pages if page_id(page) == page_ref]
    if exact_id_matches:
        return exact_id_matches, page_lookup

    if "/" in page_ref:
        normalized_target = normalize_page_path(page_ref)
        path_matches = [page for page in pages if normalize_page_path(build_page_path(page, page_lookup)) == normalized_target]
        if path_matches:
            return path_matches, page_lookup

    exact_name_matches = [page for page in pages if page_name(page).casefold() == page_ref.casefold()]
    return exact_name_matches, page_lookup


def resolve_page(
    app: AppContext,
    backend: CodaBackend,
    doc_id: str,
    *,
    page_ref: Optional[str],
    page_path: Optional[str],
    label: str = "page",
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    pages = backend.list_all_pages(doc_id).get("items", [])
    return resolve_page_from_inventory(
        app,
        pages,
        page_ref=page_ref,
        page_path=page_path,
        label=label,
    )


def resolve_page_from_inventory(
    app: AppContext,
    pages: list[dict[str, Any]],
    *,
    page_ref: Optional[str],
    page_path: Optional[str],
    label: str = "page",
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    resolved_ref = resolve_required_value(
        page_ref,
        page_path,
        app.state.current_page_id,
        label,
        option_name="--path",
        use_session_hint="pages use",
    )
    matches, page_lookup = resolve_page_matches(
        pages,
        None if page_path else resolved_ref,
        page_path or (resolved_ref if "/" in resolved_ref else None),
        label=label,
    )

    if len(matches) == 1:
        return matches[0], page_lookup

    if len(matches) > 1:
        rendered = render_page_matches([page_summary(match, page_lookup) for match in matches[:10]], f"{label} matches")
        raise click.ClickException(
            f"{label.capitalize()} {resolved_ref!r} is ambiguous. Use an id or --path.\n{rendered}"
        )

    if resolved_ref == app.state.current_page_id:
        return {"id": resolved_ref, "name": resolved_ref}, page_lookup

    raise click.ClickException(f"No {label} matched {resolved_ref!r}. Use `pages find` to search the current document.")


def filter_pages_by_query(
    pages: list[dict[str, Any]],
    query: str,
    page_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_query = query.casefold()
    matches = []
    for page in pages:
        haystacks = [page_name(page), page_id(page), build_page_path(page, page_lookup)]
        if any(normalized_query in haystack.casefold() for haystack in haystacks):
            matches.append(page)
    return matches


def fuzzy_find_pages(
    pages: list[dict[str, Any]],
    query: str,
    page_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    normalized_query = query.casefold()
    for page in pages:
        candidates = [page_name(page), build_page_path(page, page_lookup), page_id(page)]
        score = max(difflib.SequenceMatcher(a=normalized_query, b=candidate.casefold()).ratio() for candidate in candidates)
        if score >= 0.5:
            scored.append((score, page))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [page for _, page in scored]


def progress_callback_for(app: AppContext) -> Callable[[str], None]:
    return lambda message: emit_progress(app, message)


@cli.group()
def docs() -> None:
    """Document operations."""


@docs.command("list")
@click.option("--query", default=None, help="Optional search query.")
@json_option
@click.pass_obj
def docs_list(app: AppContext, query: Optional[str]) -> None:
    backend = require_backend(app)
    payload = backend.list_documents(query=query)
    emit(app, payload, render_named_items(payload.get("items", []), "documents"))


@docs.command("use")
@click.argument("doc_ref", required=False)
@click.option("--doc-id", default=None, help="Document id. Use this form for ids that begin with '-'.")
@json_option
@click.pass_obj
def docs_use(app: AppContext, doc_ref: Optional[str], doc_id: Optional[str]) -> None:
    resolved_doc_id = resolve_required_value(doc_ref, doc_id, None, "document id", option_name="--doc-id")
    set_selection(app, doc_id=resolved_doc_id, table_id=None, page_id=None)
    emit(app, {"current_doc_id": resolved_doc_id}, f"Current document: {resolved_doc_id}")


@cli.group()
def pages() -> None:
    """Page operations."""


@pages.command("list")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--limit", type=int, default=None)
@click.option("--next-page-token", default=None)
@click.option("--query", default=None, help="Filter pages by id, name, or path.")
@click.option("--parent-page", default=None, help="Only include direct children of this parent page id or name.")
@click.option("--parent-path", default=None, help="Only include direct children of this parent page path.")
@click.option("--all", "all_pages", is_flag=True, default=False, help="Fetch every page in the document before rendering.")
@click.option("--long", "long_mode", is_flag=True, default=False, help="Show parent/path metadata in human-readable output.")
@json_option
@click.pass_obj
def pages_list(
    app: AppContext,
    doc_id: Optional[str],
    limit: Optional[int],
    next_page_token: Optional[str],
    query: Optional[str],
    parent_page: Optional[str],
    parent_path: Optional[str],
    all_pages: bool,
    long_mode: bool,
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    use_inventory = bool(query or parent_page or parent_path or all_pages or long_mode)

    if use_inventory:
        pages_payload = backend.list_all_pages(resolved_doc_id)
        items = list(pages_payload.get("items", []))
        page_lookup = build_page_lookup(items)

        if parent_page or parent_path:
            parent, _ = resolve_page_from_inventory(
                app,
                items,
                page_ref=parent_page,
                page_path=parent_path,
                label="parent page",
            )
            items = [page for page in items if page_parent_id(page) == page_id(parent)]
            page_lookup = build_page_lookup(items)

        if query:
            items = filter_pages_by_query(items, query, page_lookup)

        if limit is not None:
            items = items[:limit]

        payload = {"items": items}
        emit(app, payload, render_page_items(items, long_mode=long_mode))
        return

    payload = backend.list_pages(resolved_doc_id, limit=limit, next_page_token=next_page_token)
    emit(app, payload, render_page_items(payload.get("items", []), long_mode=long_mode))


@pages.command("find")
@click.argument("query")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option(
    "--mode",
    type=click.Choice(["contains", "exact", "fuzzy"], case_sensitive=False),
    default="contains",
    show_default=True,
)
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--parent-page", default=None, help="Optional parent page id or name scope.")
@click.option("--parent-path", default=None, help="Optional parent page path scope.")
@json_option
@click.pass_obj
def pages_find(
    app: AppContext,
    query: str,
    doc_id: Optional[str],
    mode: str,
    limit: int,
    parent_page: Optional[str],
    parent_path: Optional[str],
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    items = backend.list_all_pages(resolved_doc_id).get("items", [])
    page_lookup = build_page_lookup(items)

    if parent_page or parent_path:
        parent, _ = resolve_page_from_inventory(
            app,
            items,
            page_ref=parent_page,
            page_path=parent_path,
            label="parent page",
        )
        items = [page for page in items if page_parent_id(page) == page_id(parent)]
        page_lookup = build_page_lookup(items)

    if mode == "exact":
        normalized_query = query.casefold()
        matches = [
            page
            for page in items
            if normalized_query in {page_name(page).casefold(), page_id(page).casefold(), build_page_path(page, page_lookup).casefold()}
        ]
    elif mode == "fuzzy":
        matches = fuzzy_find_pages(items, query, page_lookup)
    else:
        matches = filter_pages_by_query(items, query, page_lookup)

    matches = matches[:limit]
    payload = {
        "query": query,
        "mode": mode,
        "items": [page_summary(page, page_lookup) for page in matches],
    }
    emit(app, payload, render_page_matches(payload["items"], "matching pages"))


@pages.command("use")
@click.argument("page_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
@json_option
@click.pass_obj
def pages_use(app: AppContext, page_id_or_name: Optional[str], doc_id: Optional[str], page_path: Optional[str]) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, page_lookup = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    resolved_page_id = page_id(page)
    set_selection(app, doc_id=resolved_doc_id, table_id=app.state.current_table_id, page_id=resolved_page_id)
    payload = {
        "current_doc_id": resolved_doc_id,
        "current_page_id": resolved_page_id,
        "current_page": page_summary(page, page_lookup),
    }
    emit(app, payload, f"Current page: {payload['current_page']['path']} ({resolved_page_id})")


@pages.command("create")
@click.argument("name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--parent-page-id", default=None, help="Parent page id or name.")
@click.option("--parent-path", default=None, help="Parent page path for disambiguation.")
@click.option("--content", default=None, help="Inline markdown content.")
@click.option("--file", "content_file", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=None)
@json_option
@click.pass_obj
def pages_create(
    app: AppContext,
    name: str,
    doc_id: Optional[str],
    parent_page_id: Optional[str],
    parent_path: Optional[str],
    content: Optional[str],
    content_file: Optional[Path],
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    if content is not None or content_file is not None:
        content_value = parse_text_input(content, content_file, "page content")
    else:
        content_value = None
    resolved_parent_page_id = None
    if parent_page_id or parent_path:
        parent_page, _ = resolve_page(
            app,
            backend,
            resolved_doc_id,
            page_ref=parent_page_id,
            page_path=parent_path,
            label="parent page",
        )
        resolved_parent_page_id = page_id(parent_page)
    payload = backend.create_page(
        resolved_doc_id,
        name,
        content=content_value,
        parent_page_id=resolved_parent_page_id,
    )
    emit(app, payload)


@pages.command("get")
@click.argument("page_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
@json_option
@click.pass_obj
def pages_get(app: AppContext, page_id_or_name: Optional[str], doc_id: Optional[str], page_path: Optional[str]) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, page_lookup = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    content = backend.get_page_content(
        resolved_doc_id,
        page_id(page),
        progress_callback=progress_callback_for(app),
    )
    emit(app, {"content": content, "page": page_summary(page, page_lookup)}, content)


@pages.command("peek")
@click.argument("page_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
@click.option("--lines", "num_lines", type=int, default=30, show_default=True)
@json_option
@click.pass_obj
def pages_peek(
    app: AppContext,
    page_id_or_name: Optional[str],
    doc_id: Optional[str],
    page_path: Optional[str],
    num_lines: int,
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, page_lookup = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    content = backend.get_page_content(
        resolved_doc_id,
        page_id(page),
        progress_callback=progress_callback_for(app),
    )
    preview = "\n".join(content.splitlines()[:num_lines])
    emit(app, {"content": preview, "page": page_summary(page, page_lookup), "lines": num_lines}, preview)


@pages.command("export")
@click.argument("page_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "html"], case_sensitive=False),
    default="markdown",
    show_default=True,
)
@click.option("--output", "output_path", type=click.Path(path_type=Path, dir_okay=False), default=None)
@json_option
@click.pass_obj
def pages_export(
    app: AppContext,
    page_id_or_name: Optional[str],
    doc_id: Optional[str],
    page_path: Optional[str],
    output_format: str,
    output_path: Optional[Path],
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, page_lookup = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    content = backend.export_page(
        resolved_doc_id,
        page_id(page),
        output_format=output_format,
        progress_callback=progress_callback_for(app),
    )

    payload = {"page": page_summary(page, page_lookup), "format": output_format, "content": content}
    if output_path is not None:
        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Failed to write export file: {exc}") from exc
        payload["output"] = str(output_path)
        emit(app, payload, f"Wrote {output_format} export to {output_path}")
        return

    emit(app, payload, content)


@pages.command("update-content")
@click.argument("page_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
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
@json_option
@click.pass_obj
def pages_update_content(
    app: AppContext,
    page_id_or_name: Optional[str],
    doc_id: Optional[str],
    page_path: Optional[str],
    insertion_mode: str,
    element_id: Optional[str],
    content: Optional[str],
    content_file: Optional[Path],
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, _ = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    content_value = parse_text_input(content, content_file, "page content")
    payload = backend.update_page_content(
        resolved_doc_id,
        page_id(page),
        content_value,
        insertion_mode=insertion_mode,
        element_id=element_id,
    )
    emit(app, payload)


@pages.command("duplicate")
@click.argument("page_id_or_name", required=False)
@click.argument("new_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
@json_option
@click.pass_obj
def pages_duplicate(
    app: AppContext,
    page_id_or_name: Optional[str],
    new_name: str,
    doc_id: Optional[str],
    page_path: Optional[str],
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, _ = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    payload = backend.duplicate_page(resolved_doc_id, page_id(page), new_name)
    emit(app, payload)


@pages.command("rename")
@click.argument("page_id_or_name", required=False)
@click.argument("new_name")
@click.option("--doc-id", default=None, help="Document id. Falls back to the current session doc.")
@click.option("--path", "page_path", default=None, help="Full page path, for example Team/Project/Page.")
@json_option
@click.pass_obj
def pages_rename(
    app: AppContext,
    page_id_or_name: Optional[str],
    new_name: str,
    doc_id: Optional[str],
    page_path: Optional[str],
) -> None:
    backend = require_backend(app)
    resolved_doc_id = resolve_doc_id(app, doc_id)
    page, _ = resolve_page(
        app,
        backend,
        resolved_doc_id,
        page_ref=page_id_or_name,
        page_path=page_path,
    )
    payload = backend.rename_page(resolved_doc_id, page_id(page), new_name)
    emit(app, payload)


@pages.command("copy-content")
@click.argument("source_page_id_or_name", required=False)
@click.argument("target_page_id_or_name", required=False)
@click.option("--doc-id", default=None, help="Source document id. Falls back to the current session doc.")
@click.option("--target-doc-id", default=None, help="Target document id. Defaults to the source doc.")
@click.option("--source-path", default=None, help="Full source page path.")
@click.option("--target-path", default=None, help="Full target page path.")
@click.option(
    "--mode",
    "insertion_mode",
    type=click.Choice(["append", "prepend", "replace"], case_sensitive=False),
    default="replace",
    show_default=True,
)
@click.option("--target-element-id", default=None, help="Optional target element id for relative content edits.")
@json_option
@click.pass_obj
def pages_copy_content(
    app: AppContext,
    source_page_id_or_name: Optional[str],
    target_page_id_or_name: Optional[str],
    doc_id: Optional[str],
    target_doc_id: Optional[str],
    source_path: Optional[str],
    target_path: Optional[str],
    insertion_mode: str,
    target_element_id: Optional[str],
) -> None:
    backend = require_backend(app)
    source_doc_id = resolve_doc_id(app, doc_id)
    resolved_target_doc_id = target_doc_id or source_doc_id
    source_page, source_lookup = resolve_page(
        app,
        backend,
        source_doc_id,
        page_ref=source_page_id_or_name,
        page_path=source_path,
        label="source page",
    )
    target_page, target_lookup = resolve_page(
        app,
        backend,
        resolved_target_doc_id,
        page_ref=target_page_id_or_name,
        page_path=target_path,
        label="target page",
    )
    content = backend.get_page_content(
        source_doc_id,
        page_id(source_page),
        progress_callback=progress_callback_for(app),
    )
    result = backend.update_page_content(
        resolved_target_doc_id,
        page_id(target_page),
        content,
        insertion_mode=insertion_mode,
        element_id=target_element_id,
    )
    emit(
        app,
        {
            "source_doc_id": source_doc_id,
            "source_page": page_summary(source_page, source_lookup),
            "target_doc_id": resolved_target_doc_id,
            "target_page": page_summary(target_page, target_lookup),
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
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
@json_option
@click.pass_obj
def links_resolve(app: AppContext, url: str, degrade_gracefully: bool) -> None:
    backend = require_backend(app)
    payload = backend.resolve_link(url, degrade_gracefully=degrade_gracefully)
    emit(app, payload)


@cli.group()
def session() -> None:
    """Local session state."""


@session.command("show")
@json_option
@click.pass_obj
def session_show(app: AppContext) -> None:
    payload: dict[str, Any] = {
        "session_path": str(app.session_path),
        "api_base_url": app.state.api_base_url,
        "current_doc_id": app.state.current_doc_id,
        "current_table_id": app.state.current_table_id,
        "current_page_id": app.state.current_page_id,
        "history_depth": len(app.state.history),
        "future_depth": len(app.state.future),
    }

    if app.backend is not None and app.state.current_doc_id:
        try:
            document = app.backend.get_document(app.state.current_doc_id)
            payload["current_doc"] = {"id": document.get("id"), "name": document.get("name")}
        except CodaApiError as exc:
            payload["current_doc_error"] = str(exc)

        if app.state.current_page_id:
            try:
                pages_payload = app.backend.list_all_pages(app.state.current_doc_id)
                page_lookup = build_page_lookup(pages_payload.get("items", []))
                current_page = page_lookup.get(app.state.current_page_id)
                if current_page is not None:
                    payload["current_page"] = page_summary(current_page, page_lookup)
            except CodaApiError as exc:
                payload["current_page_error"] = str(exc)

    if app.backend is not None and app.state.current_doc_id and app.state.current_table_id:
        try:
            table = app.backend.get_table(app.state.current_doc_id, app.state.current_table_id)
            payload["current_table"] = {"id": table.get("id"), "name": table.get("name")}
        except CodaApiError as exc:
            payload["current_table_error"] = str(exc)

    lines = [
        f"Session: {payload['session_path']}",
        f"API base URL: {payload['api_base_url']}",
        f"Current doc: {(payload.get('current_doc') or {}).get('name') or payload['current_doc_id'] or '-'}",
        f"Current table: {(payload.get('current_table') or {}).get('name') or payload['current_table_id'] or '-'}",
        f"Current page: {(payload.get('current_page') or {}).get('path') or payload['current_page_id'] or '-'}",
        f"History depth: {payload['history_depth']}",
        f"Future depth: {payload['future_depth']}",
    ]
    emit(app, payload, "\n".join(lines))


@session.command("last")
@json_option
@click.pass_obj
def session_last(app: AppContext) -> None:
    emit(app, {"last_result": app.state.last_result})


@session.command("clear")
@json_option
@click.pass_obj
def session_clear(app: AppContext) -> None:
    set_selection(app, doc_id=None, table_id=None, page_id=None)
    emit(app, {"current_doc_id": None, "current_table_id": None, "current_page_id": None}, "Session selection cleared.")


@session.command("undo")
@json_option
@click.pass_obj
def session_undo(app: AppContext) -> None:
    if not app.store.undo(app.state):
        raise click.ClickException("There is no session state to undo.")
    emit(app, app.state.snapshot(), "Session selection restored to the previous state.")


@session.command("redo")
@json_option
@click.pass_obj
def session_redo(app: AppContext) -> None:
    if not app.store.redo(app.state):
        raise click.ClickException("There is no session state to redo.")
    emit(app, app.state.snapshot(), "Session selection restored to the next state.")
