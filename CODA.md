# Coda CLI-Anything Harness

Target software: `coda-mcp`

Source path: `/Users/dishants/projects/coda-cli`

This harness translates the repository's Coda MCP capability set into a stateful operator CLI with:

- document, page, table, row, and link commands
- higher-level workflows for schema inspection, page content copy, and field-based row writes
- REPL mode when no subcommand is provided
- machine-readable `--json` output
- a local session store for current doc, table, and page selection
- local undo and redo for session context changes

Backend choice:

- The harness uses the same Coda REST API surface exposed by `coda-mcp`.
- Request shapes were derived from `src/server.ts` and the generated OpenAPI client types in `src/client/types.gen.ts`.
- This keeps the CLI aligned with the repo without re-inventing operations ad hoc.

Notable behavior:

- Remote page and row mutations are not undoable because the Coda API does not expose a general undo endpoint.
- Undo and redo only apply to local session selection state.
- The CLI accepts both `CODA_API_KEY` and `API_KEY` to match common Coda and MCP setups.
