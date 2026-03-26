# Coda CLI Reference

## Install

Recommended:

```bash
pipx install git+https://github.com/dishant0406/coda-cli.git
```

Alternative:

```bash
python3 -m pip install git+https://github.com/dishant0406/coda-cli.git
```

## Environment

- `CODA_API_KEY` or `API_KEY`: required for live API calls
- `CODA_API_BASE_URL`: override base URL for proxies, test doubles, or non-default deployments
- `CODA_SESSION_PATH`: override where the local session file is stored
- `NODE_TLS_REJECT_UNAUTHORIZED=0`: default behavior for self-signed HTTPS compatibility

## Command Groups

### Docs

- `coda-cli docs list [--query TEXT] [--json]`
- `coda-cli docs use <doc-id>`

### Pages

- `coda-cli pages list [--doc-id <doc-id>] [--json]`
- `coda-cli pages use <page-id> [--doc-id <doc-id>]`
- `coda-cli pages create <name> [--doc-id <doc-id>] [--content TEXT|--file PATH] [--parent-page-id <page-id>]`
- `coda-cli pages get <page-id-or-name> [--doc-id <doc-id>]`
- `coda-cli pages peek <page-id-or-name> [--doc-id <doc-id>] [--lines N]`
- `coda-cli pages update-content <page-id-or-name> [--doc-id <doc-id>] [--mode append|prepend|replace] [--element-id <id>] [--content TEXT|--file PATH]`
- `coda-cli pages duplicate <page-id-or-name> <new-name> [--doc-id <doc-id>]`
- `coda-cli pages rename <page-id-or-name> <new-name> [--doc-id <doc-id>]`
- `coda-cli pages copy-content <source-page> <target-page> [--doc-id <doc-id>] [--target-doc-id <doc-id>] [--mode append|prepend|replace] [--target-element-id <id>]`

### Tables

- `coda-cli tables list [--doc-id <doc-id>] [--table-type table|view] [--json]`
- `coda-cli tables use <table-id> [--doc-id <doc-id>]`
- `coda-cli tables columns [table-id-or-name] [--doc-id <doc-id>] [--visible-only]`
- `coda-cli tables schema [table-id-or-name] [--doc-id <doc-id>] [--visible-only] [--updated-layouts] [--json]`

### Rows

- `coda-cli rows list [--table-id <table>] [--doc-id <doc-id>] [--query TEXT] [--sort-by createdAt|natural|updatedAt] [--value-format simple|simpleWithArrays|rich] [--json]`
- `coda-cli rows get <row-id-or-name> [--table-id <table>] [--doc-id <doc-id>]`
- `coda-cli rows update <row-id-or-name> [--table-id <table>] [--doc-id <doc-id>] [--cells JSON|--cells-file PATH]`
- `coda-cli rows update-fields <row-id-or-name> [--table-id <table>] [--doc-id <doc-id>] --field 'Column=<json-value>'...`
- `coda-cli rows upsert [--table-id <table>] [--doc-id <doc-id>] --rows JSON|--rows-file PATH [--key-columns JSON|--key-columns-file PATH]`
- `coda-cli rows upsert-one [--table-id <table>] [--doc-id <doc-id>] --field 'Column=<json-value>'... [--key-column <name>]...`
- `coda-cli rows delete <row-id-or-name> [--table-id <table>] [--doc-id <doc-id>]`
- `coda-cli rows delete-many [--table-id <table>] [--doc-id <doc-id>] --row-ids JSON|--row-ids-file PATH`
- `coda-cli rows push-button <row-id-or-name> <column-id-or-name> [--table-id <table>] [--doc-id <doc-id>]`

### Links

- `coda-cli links resolve <url> [--degrade-gracefully]`

### Session

- `coda-cli session show`
- `coda-cli session last`
- `coda-cli session clear`
- `coda-cli session undo`
- `coda-cli session redo`

## Practical Guidance

- Use `docs use` and `tables use` early when doing multiple related operations.
- Use `--json` when chaining commands or when another tool will parse the result.
- Use explicit ids instead of names when duplicate names are possible.
- Use `pages peek` before `pages update-content` when editing large pages.
- Use `tables schema` before `rows update-fields` to confirm valid column names and expected types.
- Use `--file` or `--rows-file` for large payloads to avoid fragile shell quoting.

## Troubleshooting

### `command not found: coda-cli`

- `pipx ensurepath`, then restart the shell.
- If installed with `pip --user`, ensure the user scripts directory is on `PATH`.

### Self-signed certificate failures

- Keep `NODE_TLS_REJECT_UNAUTHORIZED=0`.
- Only set it to `1` if the target environment has a valid CA chain and strict verification is desired.

### Missing auth

- Export `CODA_API_KEY` before running commands.
- If the environment already uses `API_KEY`, the CLI accepts that too.

### Ambiguous object names

- Prefer ids over names for docs, pages, tables, columns, and rows.
- If unsure, list or inspect first, then reuse the returned ids.
