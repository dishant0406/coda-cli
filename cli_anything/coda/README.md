# CLI-Anything Coda

`cli-anything-coda` is a stateful operator CLI for Coda built from the `coda-mcp` repository's API and tool surface.

## Features

- REPL by default when run without a subcommand
- `--json` output for automation
- local session state for current document, table, and page
- local undo and redo for session context changes
- file-based and inline JSON inputs for row mutations

## Install

```bash
python3 -m pip install -e .
```

## Environment

- `CODA_API_KEY` or `API_KEY`: required for remote operations
- `CODA_API_BASE_URL`: optional override, useful for tests
- `CODA_SESSION_PATH`: optional session file override

## Examples

```bash
cli-anything-coda docs list
cli-anything-coda docs use doc-xyz
cli-anything-coda pages list
cli-anything-coda pages create "Weekly Notes" --content "# Agenda"
cli-anything-coda pages copy-content source-page target-page --mode append
cli-anything-coda tables use grid-abc
cli-anything-coda tables schema
cli-anything-coda rows list grid-abc --query '"Status":"Open"' --json
cli-anything-coda rows update grid-abc i-row123 --cells '[{"column":"Status","value":"Done"}]'
cli-anything-coda rows update-fields i-row123 --field 'Status="Done"' --field 'Points=3'
cli-anything-coda rows upsert-one --field 'Name="Alice"' --field 'Status="Open"' --key-column Name
cli-anything-coda
```
