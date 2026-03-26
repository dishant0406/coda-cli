---
name: coda-cli
description: Operates the coda-cli tool to inspect and mutate Coda documents, pages, tables, rows, links, and local session state from the terminal. Use when the user wants Coda automation, page or table edits, row upserts, schema inspection, document selection, link resolution, or troubleshooting around coda-cli install/auth/TLS behavior.
---

# Coda CLI

## Quick Start

Use `coda-cli` for all terminal-based Coda work.

Minimal flow:

```bash
coda-cli docs list --json
coda-cli docs use <doc-id>
coda-cli tables schema
coda-cli rows list --table-id <table-id> --json
```

Required environment:

- `CODA_API_KEY` or `API_KEY`
- Optional `CODA_API_BASE_URL`
- Optional `CODA_SESSION_PATH`

TLS note:

- The CLI defaults `NODE_TLS_REJECT_UNAUTHORIZED=0` for self-signed HTTPS compatibility.
- Set `NODE_TLS_REJECT_UNAUTHORIZED=1` only when strict certificate verification is required.

## Workflows

### Inspect

1. List docs with `coda-cli docs list --json`.
2. Select a doc with `coda-cli docs use <doc-id>`.
3. Inspect tables with `coda-cli tables list --json` or `coda-cli tables schema`.
4. Inspect pages with `coda-cli pages list --json` and `coda-cli pages peek <page>`.

### Page Edits

1. Select the target doc first.
2. Read before editing with `pages get` or `pages peek`.
3. Use `pages create`, `pages update-content`, `pages rename`, `pages duplicate`, or `pages copy-content`.
4. Prefer `--file` for large markdown bodies.

### Row/Table Edits

1. Inspect schema with `tables schema`.
2. Use `rows list` or `rows get` before mutation when keys are uncertain.
3. Prefer `rows update-fields` and `rows upsert-one` for simple writes.
4. Use `rows update`, `rows upsert`, `rows delete`, `rows delete-many`, and `rows push-button` for advanced cases.

### Session-Aware Usage

1. Use `docs use`, `tables use`, and `pages use` to reduce repeated ids.
2. Check active context with `coda-cli session show`.
3. Use `session undo` and `session redo` only for local context changes, not remote Coda mutations.

## Operating Rules

- Prefer `--json` when output will be parsed or reused.
- Prefer explicit ids over names when ambiguity is possible.
- Prefer `tables schema` before row updates to confirm columns and types.
- Prefer field-style row commands over raw JSON when the edit is straightforward.
- If the user mentions self-signed certs or private HTTPS, keep the default TLS behavior.

## References

- Command cookbook: See [REFERENCE.md](REFERENCE.md)
- End-to-end examples: See [EXAMPLES.md](EXAMPLES.md)
