---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-guidelines]; otherwise, do not modify."
---

# SLQ Guidelines

## Purpose

Give authors positive guidance for adding sources, fields, and output formatters to `slq`.

## Guidelines

### `SLQG-001` Use Dataclasses for `Record` and AST

Define `Record` as a Python dataclass and AST nodes as dataclasses. This gives type hints, defaults, and validation from the schema. Avoid dictionaries or untyped JSON for core structures.

### `SLQG-002` Implement New Sources via `DataSource`

A new chat tool is one class implementing `DataSource`. Provide `name`, `default_paths`, `can_answer(ast)`, `records(ast, env)`, `list(env)`, and `sessions(env)`. Map the tool's session and message shapes to the `Record` schema. Use `meta` and `raw` only for tool-specific extras. Non-file sources receive a `QueryRequest` with the AST, time bounds, and environment; use a source-specific pushdown layer such as `SQLBuilder` to translate constraints into the native backend.

### `SLQG-003` Keep Formatters Pure

Output formatters take an iterable of `Record` DTOs and a field list; they return text or JSON. They do not open files, evaluate queries, or maintain state. This makes them testable and lets stats overlays and `ls` reuse `output.render_records`.

### `SLQG-004` Write Tests with Controlled Fixtures

Unit tests for the parser, evaluator, and sources use small fixtures checked into `tests/fixtures/` (JSONL for file-backed sources, SQLite databases for database-backed sources), not the user's live logs. Integration tests may read real paths only when explicitly configured.

### `SLQG-005` Run `dg lint` on Governed Docs

Before committing any doc under `docs/`, run the doc-graph lint and resolve mechanical findings. This preserves the authority basis and query routes.

### `SLQG-006` Update the Spec Before the Design

When the public CLI or FBR grammar changes, amend [Specification](slq-spec.md) before changing the design or implementation. Consumer-visible behavior is the durable authority.

### `SLQG-007` Keep Session `content` Lazy

Session rows are expensive. Build the concatenated `content` only when the query may match `kind=session`; otherwise build a summary or omit the session record.

### `SLQG-008` Extend the Schema Before the Query

New query fields are new `Record` fields first. Add them to the schema, sources, and validation before exposing them in FBR aliases. This keeps the query language a thin projection of the schema.

### `SLQG-009` Add Output Formats via `present`

New output formats live in `output.render_records` and use the `present` DTO and `present.term` table utilities. Do not write format-specific `Record` shapes or ad-hoc table logic. This keeps the output layer source-agnostic and lets `present` move to its own package.

### `SLQG-010` Expose Source Listings through the CLI

A source listing is a subcommand, not a flag. Implement `DataSource.list()` for source paths and `DataSource.sessions()` for session files; the `ls` command dispatches to these methods. This keeps the CLI surface stable when new sources are added.

### `SLQG-011` Read Files Through the Resource Manager

A file-backed `DataSource` opens each JSONL through `slq.resources.get_resource(path)`. It does not call `Path.open` directly or buffer every file. It reads the metadata and records it needs, and it lets the `ResourceManager` track file lifetimes, offsets, and dirtiness. This centralizes caching and keeps the AST-driven, on-demand read contract. Database-backed sources manage their own connection and use source-specific pushdown.

### `SLQG-012` Parallelize Listing Through the WorkQueue

When a file-backed `DataSource.sessions()` must scan many files, partition the sorted file list into one chunk per potential `WorkQueue` worker and map a chunk function over `ResourceManager.map()`. The queue starts one worker and spawns more only when a chunk waits longer than the quantum. This overlaps slow file open/parse, stays single-threaded for fast work, keeps output sorted, and respects `SLQG-007` by reading only metadata for listings. Database-backed sources use their own metadata queries.

### `SLQG-013` Sort Session Listings by Timestamp

`DataSource.sessions()` must return `SessionRecord`s in a stable, user-predictable order. Collect the records, sort by `timestamp` ascending (un-dated records first), and then yield. For file-backed sources, if no metadata or event timestamp is available, fall back to the session file `mtime` as a stable sort key and as the displayed `timestamp` for `ls`. Database-backed sources use a stable column from their metadata query. This makes `slq ls <source> | tail` and `slq ls <source> | head` meaningful.

### `SLQG-014` Expose Field Discovery Through `ls`

Every canonical `Record` field is discoverable from the CLI. `slq ls fields` emits a `FieldRecord` for each canonical field with `field_name` and `field_type`. Bare `slq ls` lists sources and then the field spec. This keeps the schema self-documenting and lets users compose FBR queries without reading source code.

### `SLQG-015` Accept Unambiguous Field Prefixes

The FBR parser resolves a field spec against the canonical `Record` field names by unambiguous prefix. Ambiguous prefixes produce an error that lists the matching names. This lets users type `:time/2026/` for `timestamp` and `:to/codex/` for `tool` while protecting against `:re/.../` matching `record_count`, `record_id`, and `rec_type`.

### `SLQG-016` Display-Only Field Terms Select Output

A field name with no regex (`:<field>`) is a display-only term. It selects a column for output without filtering. If a query contains any display-only terms, the output projection is exactly those terms; otherwise the constrained fields become the output. This lets a query both filter and select columns in one expression.

### `SLQG-017` Declare Fields with `record_field`

Every `Record` field is declared with `record_field(..., format="...")` and, when computed, `computed=True`. Subclasses override `default_fields`. Renderers live in `FIELD_RENDERERS` and `record_value()` dispatches by field format. This keeps timestamp, hash, and short-hash formatting consistent across `plain`, `json`, and `text`.

### `SLQG-018` Push Constraints into the Source Backend

When a source has a native query layer (SQLite, an index, or another structured backend), translate the `QueryRequest` into the native language and push `tool`, `session_id`, `timestamp`, `kind`, and `content` constraints down to it. Keep the translation localized to the source and test it with deterministic fixtures. This preserves the `DataSource` protocol while avoiding unnecessary data transfer.

### `SLQG-020` Keep Process and Path Primitives in `platform`

Keep POSIX process and path primitives in `src/slq/platform.py` as `logical_cwd()`, `same_path(a, b)`, `compatible_python(root)`, and `exec_or_run(argv)`. Call these primitives from commands and sources instead of inspecting the host at each use site. This keeps host-sensitive behavior in one readable module.

## Validation

- Every guideline names an action and the benefit.
- Guidelines are paired with [Constraints](slq-constraints.md); together they state what to do and what to avoid.
- No guideline duplicates a constraint or a spec surface.