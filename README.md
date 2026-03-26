# Coda CLI

Stateful CLI for Coda docs, pages, tables, and rows.

## Install

Recommended:

```bash
pipx install git+https://github.com/dishant0406/coda-cli.git
```

Alternative:

```bash
python3 -m pip install git+https://github.com/dishant0406/coda-cli.git
```

## Command

After install, run:

```bash
coda-cli --help
```

The legacy alias is also kept:

```bash
cli-anything-coda --help
```

## Environment

- `CODA_API_KEY` or `API_KEY`
- `CODA_API_BASE_URL` for overrides or testing
- `CODA_SESSION_PATH` for a custom session file

## Examples

```bash
coda-cli docs list
coda-cli docs use doc-xyz
coda-cli tables schema
coda-cli rows update-fields i-row123 --field 'Status="Done"' --field 'Points=3'
coda-cli pages copy-content source-page target-page --mode append
```
