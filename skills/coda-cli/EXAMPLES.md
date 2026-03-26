# Coda CLI Examples

## Select a document and inspect tables

```bash
coda-cli docs list --json
coda-cli docs use doc-abc123
coda-cli tables list --json
coda-cli tables schema
```

## Read and update a page from markdown

```bash
coda-cli pages peek Project-Plan --lines 20
coda-cli pages update-content Project-Plan --mode replace --file ./plan.md
```

## Copy one page into another

```bash
coda-cli pages copy-content SourcePage TargetPage --mode append
```

## Update a row with simple fields

```bash
coda-cli tables use grid-xyz
coda-cli rows update-fields i-row123 \
  --field 'Status="Done"' \
  --field 'Points=3'
```

## Upsert one row by key column

```bash
coda-cli rows upsert-one \
  --table-id grid-xyz \
  --key-column Name \
  --field 'Name="Alice"' \
  --field 'Status="Open"' \
  --field 'Priority=2'
```

## Bulk row upsert from a file

```bash
coda-cli rows upsert \
  --table-id grid-xyz \
  --rows-file ./rows.json \
  --key-columns '["Name"]'
```

## Resolve a browser link

```bash
coda-cli links resolve 'https://coda.io/d/_d123/...'
```

## Work with session state

```bash
coda-cli session show
coda-cli docs use doc-abc123
coda-cli tables use grid-xyz
coda-cli session undo
coda-cli session redo
```

## Strict TLS only when needed

```bash
NODE_TLS_REJECT_UNAUTHORIZED=1 coda-cli docs list --json
```
