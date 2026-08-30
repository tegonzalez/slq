---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-constraints]; otherwise, do not modify."
---

# SLQ Constraints

## Purpose

Give authors durable negative guidance for preserving `slq`'s single-table, single-query-line, and source-agnostic design.

## Constraints

### `SLQC-001` Minus as NOT

Using `-` as a NOT operator collides with CLI option parsing and with using `-` as a regex delimiter. Detect any grammar or documentation that accepts `-` before a primary. Use `!` inside quotes or `not` for shell-safe negation.

### `SLQC-002` Asterisk as Field Alias

Using `*` as an alias for "all fields" is a shell glob and will be expanded by the shell before `slq` sees it. Detect field alias tables containing `*`. Use `all` or a bare delimited global term for all-field search.

### `SLQC-003` Source File Layout in CLI

Exposing source-specific paths or file-naming conventions as CLI flags makes adding a source a CLI change. Detect flags like `--codex-dir` or `--claude-dir`. Use the `DataSource` protocol and `default_paths`; let the source own discovery.

### `SLQC-004` Session Rows in Default Event Queries

Materializing session rows for every event query is expensive and surprising. Detect code that concatenates session text when the query cannot match `kind=session`. Build session `content` lazily and only when the AST permits `kind=session` or session-only fields.

### `SLQC-005` Stats as Output Mode

Implementing stats as a dedicated output mode (`-o stats`, hardcoded counters) prevents it from being a reusable overlay. Detect formatters or CLI options that compute stats internally. Implement `stats` as a `Cursor` consumer that yields `kind='stats'` records.

### `SLQC-006` Secret Exposure

Writing code that logs API keys, tokens, or raw session content to stdout or files exposes secrets. Detect printing of `raw`, `meta`, or `content` outside output formatters. Route all output through formatters; never log credentials.

### `SLQC-007` Option-Like Expressions Without Guard

A query starting with `-` or containing `|`, `&`, `!`, `(`, `)`, or `*` unquoted may be interpreted by the shell or by `argparse`. Detect tests or examples with unquoted shell-sensitive characters. Document the use of single quotes and the `--` separator.

### `SLQC-008` Mutable Cursor State

Storing cursor iteration state inside `Record` or `DataSource` makes output and overlays nondeterministic. Detect shared mutable state between query, cursor, and formatter. Keep the cursor as a pure generator and formatters stateless.

### `SLQC-009` Hardcoded Source Names in CLI

Hardcoding source names like `codex` or `claude` in command definitions or help text forces a CLI edit for every new source. Detect `argparse` choices or help strings that list source names. Discover sources from the `SOURCES` registry and accept source names as arguments.

### `SLQC-010` Format-Specific Record Shapes

Defining separate record dataclasses for `plain`, `json`, or `text` output fragments the output layer. Detect new dataclasses or output functions that do not consume the shared `Record`. Route all command output through `Record` DTOs and `output.render_records`.

### `SLQC-011` Eager General Loaders

Pre-loading or pre-parsing all source files before the AST proves they are needed is too slow and too memory-hungry for large log directories. Detect code that opens every file in a source directory unconditionally, buffers every parsed object, or materializes session `content` when the query cannot match `kind=session`. For file-backed sources, route all file access through the `ResourceManager` and read only candidate files and candidate records. For database-backed sources, push constraints to the native query layer and fetch only candidate rows. Lazy `Cursor` and per-record filtering decide what is actually emitted.

### `SLQC-012` Hardcoded Default Field Lists

Hardcoding output field lists for a command or source in the CLI or source code forces an edit when the `Record` schema or a source's natural projection changes. Detect `fields = [...]` literals in `cli.py` or `DataSource` methods. Use `Record.default_fields` or subclass `SourceRecord`/`SessionRecord` defaults; let the record type own its default projection.

### `SLQC-013` Format-Local Rendering

Duplicating rendering logic for timestamps, hashes, or short hashes inside each output formatter fragments formatting and produces inconsistent output. Detect string formatting of `timestamp`, `session_id`, or `record_id` outside `record_value()` or `FIELD_RENDERERS`. Declare every field with `record_field(format="...")` and dispatch through the single renderer registry.

### `SLQC-014` Pre-Spawning All WorkQueue Workers

Starting all `WorkQueue` workers at initialization wastes threads for fast or small listings. Detect a `WorkQueue` constructor that creates `nproc - 1` threads before any work is submitted. Start with one worker and spawn additional workers only when a queued task waits longer than the configured quantum and no idle worker is available.

### `SLQC-015` Host Branching in Commands and Sources

Branching on `sys.platform`, `os.name`, or `platform.system()` inside command or source modules turns every supported host into a separate code path. Detect host tests or interpreter and path-identity logic outside `src/slq/platform.py`. Keep those primitives in `platform.py` and call them unconditionally from their consumers.

### `SLQC-016` Single-Root Source Discovery

Selecting the first existing root or indexing `paths[0]` silently drops sessions from other stores and can list a symlinked store twice. Detect first-existing-only probes, unconditional one-element candidate lists, and direct first-element indexing in source readers. Return every candidate root, admit and deduplicate it through `DataSource.admitted_paths()`, and iterate the complete result.

## Validation

- Every entry names a failure pattern, why it fails, a detection signal, and replacement guidance.
- No entry merely negates a positive rule owned elsewhere.
- The guidance addresses authors and does not weaken a boundary for consumer convenience.
- Duplicative Inquiry catalogs, bootstrap discovery coupling, parallel registries, and recursive or internal-operation selection each have distinct detection and replacement guidance. (These are inherited from the doc-graph constraints doc.)