# Coda CLI

Stateful CLI for Coda docs, pages, tables, and rows.

## Install

Recommended:

```bash
pipx install --force git+https://github.com/dishant0406/coda-cli.git
```

Alternative:

```bash
python3 -m pip install --upgrade git+https://github.com/dishant0406/coda-cli.git
```

## Command

After install, run:

```bash
coda-cli --help
```

## Environment

- `CODA_API_KEY` or `API_KEY`
- `CODA_API_BASE_URL` for overrides or testing
- `CODA_SESSION_PATH` for a custom session file
- `CODA_API_TIMEOUT` to opt into a client-side timeout in seconds. By default the CLI does not enforce a request timeout.
- `NODE_TLS_REJECT_UNAUTHORIZED=0` is honored for self-signed HTTPS endpoints and is the default in this CLI. Set it to `1` to enforce TLS verification.

## Examples

```bash
coda-cli docs list --json
coda-cli docs use --doc-id doc-xyz
coda-cli pages list --query sdk --long
coda-cli pages find "GrowwBot SDK" --mode exact
coda-cli pages get --path "Web Team/GR-1/GrowwBot SDK"
coda-cli pages export --path "Web Team/GR-1/GrowwBot SDK" --output growwbot-sdk.md
coda-cli tables schema
coda-cli rows update-fields i-row123 --field 'Status="Done"' --field 'Points=3'
coda-cli pages copy-content source-page target-page --mode append
```
