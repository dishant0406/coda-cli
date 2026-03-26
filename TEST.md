# Test Plan

## Scope

Validate that the harness is installable, stateful, and aligned with the `coda-mcp` feature surface.

## Unit coverage

File: `cli_anything/coda/tests/test_core.py`

- session store round-trip
- local undo and redo behavior
- HTTP request shaping for mutation endpoints
- page export polling flow for markdown content retrieval
- field-based row command parsing
- combined table schema workflow

## End-to-end coverage

File: `cli_anything/coda/tests/test_full_e2e.py`

- `docs list` JSON output
- session selection with `docs use`
- `tables list` using the stored document context
- `tables schema` combining table info and columns
- `pages get` export flow through a local fake Coda API server

## Validation commands

From `agent-harness/`:

```bash
python3 -m pip install -e .
python3 -m unittest discover -s cli_anything/coda/tests -p 'test_*.py'
cli-anything-coda --json docs list --query example
```

## Required environment

- `CODA_API_KEY` or `API_KEY`
- Optional `CODA_API_BASE_URL` for tests against a stub server
- Optional `CODA_SESSION_PATH` to control where session state is written
