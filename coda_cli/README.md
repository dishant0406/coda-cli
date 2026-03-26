# Coda CLI

`coda-cli` is a stateful operator CLI for Coda built from the `coda-mcp` repository's API and tool surface.

## Features

- REPL by default when run without a subcommand
- `--json` output for automation
- local session state for current document, table, and page
- local undo and redo for session context changes
- file-based and inline JSON inputs for row mutations

## Install

```bash
python3 -m pip install git+https://github.com/dishant0406/coda-cli.git
```

## Environment

- `CODA_API_KEY` or `API_KEY`: required for remote operations
- `CODA_API_BASE_URL`: optional override, useful for tests
- `CODA_SESSION_PATH`: optional session file override
- `NODE_TLS_REJECT_UNAUTHORIZED=0`: default behavior for self-signed HTTPS compatibility. Set to `1` to enforce certificate verification.

## Examples

```bash
coda-cli docs list
coda-cli docs use doc-xyz
coda-cli pages list
coda-cli pages create "Weekly Notes" --content "# Agenda"
coda-cli pages copy-content source-page target-page --mode append
coda-cli tables use grid-abc
coda-cli tables schema
coda-cli rows list grid-abc --query '"Status":"Open"' --json
coda-cli rows update grid-abc i-row123 --cells '[{"column":"Status","value":"Done"}]'
coda-cli rows update-fields i-row123 --field 'Status="Done"' --field 'Points=3'
coda-cli rows upsert-one --field 'Name="Alice"' --field 'Status="Open"' --key-column Name
coda-cli
```
