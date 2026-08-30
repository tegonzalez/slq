---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-design]; otherwise, do not modify."
---

# SLQ Architecture Design

## Purpose

Define the architecture that lets a single `Record` schema, a single query language, and a lazy cursor support any session-log source.

## Terminology

| Term           | Meaning                                                                                                     |
| -------------  | ----------------------------------------------------------------------------------------------------------- |
| `Record`       | Common dataclass produced by every source and consumed by every output                                      |
| `DataSource`   | Protocol for a source of `Record`s; codex, claude, and devin are initial implementations                    |
| `FBR`          | Field-bounded regex query language                                                                          |
| `QueryAST`     | Parsed, validated FBR expression                                                                            |
| `QueryRequest` | Encapsulated query parameters passed to a source, including the AST and time bounds                         |
| `SQLBuilder`   | AST-to-SQL translator for database-backed sources                                                           |
| `Cursor`       | Lazy stream of `Record`s produced by evaluating a query                                                     |
| `pushdown`     | Source skipping files, rows, or session materialization the AST proves cannot match                         |
| `present`      | Reusable DTO and TTY text-rendering library (candidate for promotion)                                       |
| `overlay`      | Resultset transformation such as stats or projection                                                        |

## Design Goals

- Preserve one semantic owner for every rule and decision.
- Make the query engine and formatters source-agnostic.
- Put source-specific backend layout behind the `DataSource` protocol.
- Keep the cursor lazy and one-pass.
- Let stats and projection be overlays, not output modes.

## Module Inventory

### `SLQM-1` Record and Schema

| Field          | Value                                                                                                                        |
| -------------- | ----------------------------------------------------------------------------                                                 |
| Product role   | Define the single superset schema, field validation, and record subtypes                                                     |
| Responsibility | Own `Record` dataclass, `SourceRecord`, `SessionRecord`, `FieldRecord`, field aliases, type formatting, and query validation |
| Owned seams    | `SLQS-1`, `SLQS-2`                                                                                                           |
| Decisions      | `SLQD-1`, `SLQD-2`                                                                                                           |

### `SLQM-2` Query Engine

| Field          | Value                                                                                       |
| -------------- | -----------------------------------------------------------------                           |
| Product role   | Parse FBR, validate against schema, evaluate AST over Records, and report output projection |
| Responsibility | Own lexer, parser, AST nodes, `eval(record)`, and `extract_output_fields`                   |
| Owned seams    | `SLQS-2`, `SLQS-3`                                                                          |
| Decisions      | `SLQD-3`, `SLQD-4`                                                                          |

### `SLQM-3` Data Sources

| Field          | Value                                                         |
| -------------- | ----------------------------------------------------------    |
| Product role   | Read local session logs and emit `Record`s                    |
| Responsibility | Own source-specific backend discovery, filtering, and mapping |
| Owned seams    | `SLQS-4`, `SLQS-5`                                            |
| Decisions      | `SLQD-5`, `SLQD-6`                                            |

### `SLQM-4` Cursor and Output

| Field          | Value                                                                        |
| -------------- | -----------------------------------------------------------------------      |
| Product role   | Provide lazy `Cursor`, projection, limit, stats overlay, and output dispatch |
| Responsibility | Own `Cursor`, stats overlay, and dispatch to `output.render_records`         |
| Owned seams    | `SLQS-3`, `SLQS-6`                                                           |
| Decisions      | `SLQD-7`                                                                     |

### `SLQM-5` Presentation

| Field          | Value                                                                                                          |
| -------------- | -----------------------------------------------------------------------                                        |
| Product role   | Provide reusable DTOs and TTY-aware text rendering                                                             |
| Responsibility | Own `present.dto`, `present.term`, and `present.render`; format `Record` lists into `plain`, `json`, or `text` |
| Owned seams    | `SLQS-6`, `SLQS-7`                                                                                             |
| Decisions      | `SLQD-8`, `SLQD-9`, `SLQD-10`                                                                                  |

### `SLQM-6` Resource Manager

| Field          | Value                                                                                                                                           |
| -------------- | -----------------------------------------------------------------------                                                                         |
| Product role   | Centralize file lifetimes, line offsets, parsed-object caching, and a shared workqueue for file-backed sources                                  |
| Responsibility | Open each JSONL once, maintain byte offsets per line, detect file changes, seek the cursor, and fan out file-level work through the `WorkQueue` |
| Owned seams    | `SLQS-4`, `SLQS-9`                                                                                                                              |
| Decisions      | `SLQD-11`, `SLQD-12`, `SLQD-14`                                                                                                                 |

### `SLQM-7` WorkQueue

| Field          | Value                                                                                                                                                                                                          |
| -------------- | -----------------------------------------------------------------------                                                                                                                                        |
| Product role   | Provide a process-wide, dynamically-sized, job-stealing thread pool for file-level work                                                                                                                        |
| Responsibility | Start one worker; spawn additional workers only when a queued task waits longer than a configurable quantum (default 10 ms) and no worker becomes idle, up to `nproc - 1`. Return results in submission order. |
| Owned seams    | `SLQS-9`                                                                                                                                                                                                       |
| Decisions      | `SLQD-14`                                                                                                                                                                                                      |

## Architecture

The CLI dispatches to a `query` or `ls` subcommand; a bare `slq` with no arguments prints usage. A query tokenizes an FBR string into a `QueryAST`, validates it against the `Record` schema, wraps it in a `QueryRequest` with time bounds and environment data, and hands the request to each `DataSource`. File-backed sources ask the `ResourceManager` for a `FileResource`, which opens the file once and keeps byte offsets for every JSONL line; database-backed sources manage their own connection and translate the AST into source-specific queries. Sources extract constraints, scan only candidate rows, and yield `Record`s. The query engine filters those records into a lazy `Cursor` of `Record`s.

The FBR parser resolves a field spec against the canonical `Record` field names using unambiguous prefix matching. A field name with no regex is a display-only term: it selects an output column without filtering. The CLI derives the default output projection from the AST (filter fields if no display-only terms, otherwise only the selected display fields); `-F/--fields` overrides this.

The `ls` command uses `DataSource.list()` and `DataSource.sessions()` to return source or session `Record`s without a query; `ls` reads only metadata, not full event content. A bare `ls` lists sources through `DataSource.list()` and then appends a `FieldRecord` for each canonical `Record` field, so users can discover both source names and queryable fields. `slq ls fields` emits only the `FieldRecord` field spec. File-backed `DataSource.sessions()` partitions the file list into chunks, submits them to the `WorkQueue` managed by the `ResourceManager`, collects the session `Record`s, and sorts them by `timestamp` ascending before yielding. Database-backed `DataSource.sessions()` issues its own metadata query and yields the resulting `Record`s in a stable order.

`Record` is a base dataclass. `SourceRecord`, `SessionRecord`, and `FieldRecord` are subclasses that set a polymorphic `default_fields` for their respective listing contexts. Each field is declared with `record_field(..., format="...")`; `record_value()` dispatches to a single renderer per field type (`datetime`, `hash`, `short-hash`, `path`, `text`, `number`). This gives consistent rendering of human-readable timestamps, hashes, and short hashes across all output formats.

`output.render_records` and the `present` library format the resulting `Record` stream as `plain`, `json`, or `text`. `plain` is tab-separated when the output is not a TTY and is a TTY-aware aligned table (without headers) when it is. On a TTY `plain` is streamed by default: records are emitted as they are produced and column widths may increase as wider records arrive. `-w`/`--width` opts out of streaming and pre-calculates column widths from the full result set; `-s`/`--stream` opts into streaming.

## Source-Specific Mapping

All sources implement `DataSource.can_answer(ast)`, `DataSource.records(ast, env)`, `DataSource.list(env)`, and `DataSource.sessions(env)`. File-backed sources use the shared `ResourceManager` to open each JSONL once and avoid re-reading unchanged files; database-backed sources manage their own connection and use source-specific pushdown to avoid fetching rows the AST proves cannot match. `list()` returns source-level `Record`s (tool and default paths). `sessions()` returns one `Record` per session with session-level metadata such as `record_count`, `duration`, and `model`.

### Codex

- Default search path: `~/.codex/sessions/YYYY/MM/DD/rollout-<session-id>.jsonl`.
- Session index, if present at `~/.codex/session_index.jsonl`, maps `session_id` and `updated_at` to the rollout file.
- JSONL records typically contain `role`, `content`, `id`, and `created_at`. Map:
  - `tool` = `codex`
  - `session_id` = session id from filename or index
  - `record_id` = `id` if present, else a generated id
  - `timestamp` = `created_at`
  - `kind` = `role` normalized to `user`, `agent`, `thinking`, `tool_call`, `tool_output`, `meta`, or `other`
  - `role` = original `role`
  - `rec_type` = `type` if present, else `role`
  - `content` = string `content`, or concatenated `text` entries from a list content block
  - `model` = top-level `model` or `metadata.model`
- Session row: `kind='session'`, `record_id=session_id`, `content` = concatenated event content (or summary when the query cannot match `kind=session`), `record_count` and `duration` from first/last event. For `sessions()` listings, fall back to the file `mtime` as `timestamp` if no event timestamp is found.

### Claude

- Default search path: `~/.claude/projects/<project>/<session-id>.jsonl`.
- Session metadata at `~/.claude/sessions/<session-id>.json` gives `startedAt` and `cwd`.
- JSONL records contain `type` (e.g. `user_message`, `assistant_message`, `thinking`), `message`/`content`, and a timestamp. Map:
  - `tool` = `claude`
  - `session_id` = session id from filename
  - `record_id` = `message.id` if present
  - `timestamp` = record timestamp
  - `kind` = `type` normalized to `user`, `agent`, `thinking`, `tool_call`, `tool_output`, `meta`, or `other`
  - `role` = `message.role` or `user`/`assistant` inferred from `type`
  - `rec_type` = original `type`
  - `content` = `message.content` or `content`
  - `cwd` = session metadata `cwd`
  - `project` = `<project>` directory name
  - `model` = `message.model` if present
- Session row: built similarly; use metadata `startedAt` as `timestamp`; otherwise fall back to the first record timestamp. For `sessions()` listings, also fall back to the file `mtime` as `timestamp` if no earlier timestamp is available.

### Devin

- Default source path: `~/.local-rw/share/devin/cli/sessions.db` (fallback to `~/.devin/sessions.db` or a user-supplied path via `env["paths"]`).
- One SQLite database holds `message_nodes` rows keyed by `session_id` and `node_id`. Each `chat_message` blob is a JSON object.
- The source builds a `QueryRequest` from the FBR AST, `since`/`until` bounds, and source environment. `SQLBuilder` translates the AST into a parameterized SQLite `WHERE` clause; `kind`, `content` regex, `timestamp`, and `session_id` filters run in the database.
- Map:
  - `tool` = `devin`
  - `session_id` = `message_nodes.session_id`
  - `record_id` = `session_id || '-' || node_id`
  - `timestamp` = `chat_message.metadata.created_at` converted to `datetime`
  - `kind` = `role` normalized to `user`, `agent`, `tool_call`, `tool_output`, `meta`, or `other`
  - `role` = original `role`
  - `rec_type` = `finish_reason` for assistant messages, tool-result kind for tool messages, or telemetry source otherwise
  - `content` = `chat_message.content` or serialized tool-call/tool-result metadata
  - `model` = `chat_message.metadata.generation_model` or session `model`
  - `cwd` = session `working_directory`
  - `project` = first session `workspace_dirs` entry
- Session row: `kind='session'`, `record_id=session_id`, `content` = concatenated event content (or summary when the query excludes `kind=session`), `record_count` and `duration` from first/last event and the `message_nodes` row count.
- The short hash is computed from the session slug, hyphen-bounded, and 12-16 characters long so it is visually distinct from the 8-character codex/claude UUID prefixes.

Inspect the actual files under `~/.codex`, `~/.claude`, and `~/.local-rw/share/devin/cli/` to confirm field names; the structure may vary by tool version.

### Seam Inventory

| ID     | Name              | Owner        | Direction | Contract                                     |
| -----  | ----------------- | ------------ | --------- | -------------------------------              |
| SLQS-1 | schema/query      | query engine | → schema  | field types and aliases                      |
| SLQS-2 | eval/record       | query        | → cursor  | Record matching predicate                    |
| SLQS-3 | cursor/output     | output       | → cursor  | one-pass lazy Record stream                  |
| SLQS-4 | source/filesystem | source       | → OS      | file paths and mtime                         |
| SLQS-5 | source/record     | source       | → query   | Record emission and pushdown                 |
| SLQS-6 | cli/cursor        | CLI          | → cursor  | subcommand, flag binding, and display fields |
| SLQS-7 | output/present    | output       | → present | `plain`, `json`, `text` formatting           |
| SLQS-8 | source/list       | source       | → cli     | `DataSource.list` and `DataSource.sessions`  |
| SLQS-9 | source/resource   | resource     | → OS      | byte offsets, fd lifetime, dirty detection   |

## Design Decisions

### `SLQD-1` Single `Record` Superset

| Field             | Value                                                                                              |
| ----------------- | -------------------------------------------------------------------------------------------------- |
| Decision          | All sources emit one `Record` dataclass with a common field set and a `meta`/`raw` extension point |
| Rationale         | One schema lets the query language, eval, and output be source-agnostic                            |
| Alternatives      | per-tool record types; source-specific CLI flags                                                   |
| Rejection reason  | per-tool types duplicate query and output logic and break the single surface                       |
| Affected surfaces | `Record`, schema, FBR, eval, output, sources                                                       |
| Status            | current                                                                                            |

### `SLQD-2` Lazy Cursor

| Field            | Value                                                                         |
| ---------------- | ----------------------------------------------------------------------------- |
| Decision         | Query results are a lazy `Iterator[Record]`; output and stats consume it once |
| Rationale        | Avoids materializing all matching records; keeps stats a generic overlay      |
| Alternatives     | eager list; database                                                          |
| Rejection reason | eager list limits scale; database adds dependency                             |
| Status           | current                                                                       |

### `SLQD-3` FBR Field-Bounded Regex

| Field            | Value                                                                                                                                    |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Decision         | Queries are delimited regexes prefixed by an optional field alias; the operators `&`, `or`, `!`, and `not`, plus adjacency, compose them |
| Rationale        | Regex is composable and the delimiter lets users choose boundary characters                                                              |
| Alternatives     | SQL-like grammar; natural language                                                                                                       |
| Rejection reason | SQL adds parsing and types; natural language is nondeterministic                                                                         |
| Status           | current                                                                                                                                  |

### `SLQD-4` Source Pushdown

| Field            | Value                                                                                                             |
| ---------------- | ----------------------------------------------------------------------------------------------------------        |
| Decision         | Each `DataSource` inspects the AST and skips files, rows, or session-row materialization it can prove unnecessary |
| Rationale        | Avoids reading every log file or fetching every database row for every query                                      |
| Alternatives     | central index; scan all files                                                                                     |
| Rejection reason | central index needs maintenance; scanning all is too slow                                                         |
| Status           | current                                                                                                           |

### `SLQD-5` Session Rows as Aggregates

| Field            | Value                                                                        |
| ---------------- | ---------------------------------------------------------------------------- |
| Decision         | A `kind=session` record is a synthetic aggregate built from one session file |
| Rationale        | Keeps the query surface a single table; session list is `:k/session/`        |
| Alternatives     | separate `list` output mode; session as a dimension                          |
| Rejection reason | separate modes break the single-table model and the cursor overlay model     |
| Status           | current                                                                      |

### `SLQD-6` Stats as Overlay

| Field            | Value                                                                         |
| ---------------- | ----------------------------------------------------------------------------- |
| Decision         | `-s`/`--stats` consumes the cursor and yields new `Record`s of `kind='stats'` |
| Rationale        | Stats is not a special output mode; it is a generic cursor consumer           |
| Alternatives     | dedicated stats command; built-in counters                                    |
| Rejection reason | dedicated commands fragment the CLI; built-in counters are not reusable       |
| Status           | current                                                                       |

### `SLQD-7` Field Projection

| Field            | Value                                                                                               |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| Decision         | `-F/--fields` selects a subset of `Record` fields for display; the query still filters full records |
| Rationale        | Projection is a display concern, not a query concern                                                |
| Alternatives     | query syntax for projection; format-specific fields                                                 |
| Rejection reason | mixing projection into FBR complicates the grammar                                                  |
| Status           | current                                                                                             |

### `SLQD-8` Pure Output Formatters

| Field            | Value                                                                                      |
| ---------------- | ---------------------------------------------------------------------------------------    |
| Decision         | Output formatters receive an iterable of `Record` DTOs and fields, then emit text          |
| Rationale        | DTOs decouple the CLI from rendering; the `present` library can be reused or upstreamed    |
| Alternatives     | formatters that query sources themselves; format-specific Record shapes                    |
| Rejection reason | formatters that query sources duplicate the engine; shape-specific Records fragment output |
| Status           | current                                                                                    |

### `SLQD-9` CLI Subcommands

| Field            | Value                                                                                                            |
| ---------------- | --------------------------------------------------------------------------------------                           |
| Decision         | The CLI exposes `query` and `ls` subcommands; `query` is implicit when the first argument starts with `:` or `/` |
| Rationale        | Keeps the FBR surface a single expression while letting `ls` take a source argument                              |
| Alternatives     | every command as a top-level flag (`--sources`); separate `slq-ls` tool                                          |
| Rejection reason | `--sources` is not a query and does not scale; a separate tool splits the CLI                                    |
| Status           | current                                                                                                          |

### `SLQD-10` Presentation Library

| Field            | Value                                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------                     |
| Decision         | `slq/present/` provides generic DTOs and TTY table rendering, extracted from the doc-graph `present` layer |
| Rationale        | A standalone `present` module can later be promoted to a shared library                                    |
| Alternatives     | inline table logic in `output.py`; depend on an external `present` package                                 |
| Rejection reason | inline logic is not reusable; an external package is not yet available                                     |
| Status           | current                                                                                                    |

### `SLQD-13` Polymorphic Record Fields and Default Field Sets

| Field             | Value                                                                                                                                                                                                                              |
| ----------------  | ----------------------------------------------------------------------------------------------------------                                                                                                                         |
| Decision          | `Record` is a base dataclass; `SourceRecord` and `SessionRecord` are subclasses that set `default_fields`. Each field is declared with `record_field(format="...")` and `record_value()` dispatches to a single renderer per type. |
| Rationale         | Lets `ls` and `query` pick a different default projection without format-specific logic; keeps timestamp, hash, and short-hash rendering consistent.                                                                               |
| Alternatives      | hardcoded field lists in `cli.py`; format-specific record classes; per-format renderers                                                                                                                                            |
| Rejection reason  | hardcoded lists force CLI edits for new sources; format-specific records fragment the schema; per-format renderers duplicate formatting logic                                                                                      |
| Affected surfaces | `schema.py`, `output.py`, `cli.py`, `sources`                                                                                                                                                                                      |
| Status            | current                                                                                                                                                                                                                            |

### `SLQD-14` WorkQueue for Parallel Listing

| Field             | Value                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------  | ----------------------------------------------------------------------------------------------------------                                                                                                                                                                                                                                                                                                                 |
| Decision          | `ResourceManager` owns a process-wide `WorkQueue` with a scheduler. The queue starts one worker. A dedicated scheduler thread assigns tasks to idle workers; if the oldest queued task has waited longer than the ``quantum`` (default 10 ms) and no worker becomes idle, a new worker is spawned up to ``nproc - 1``. ``DataSource.sessions()`` partitions the sorted file list into chunks and maps them over the queue. |
| Rationale         | Overlaps file open/parse for thousands of session files when chunks exceed the quantum, but stays single-threaded for fast/small listings. Results remain in sorted order and the cursor stays lazy.                                                                                                                                                                                                                       |
| Alternatives      | ``asyncio`` everywhere; ``multiprocessing``; fixed-size ``ThreadPoolExecutor``; fully sequential listing                                                                                                                                                                                                                                                                                                                   |
| Rejection reason  | full ``asyncio`` is overkill for local disk; ``multiprocessing`` loses shared ``ResourceManager`` cache and has high startup cost; a fixed-size pool spawns all threads even for fast work; sequential listing is slower at scale                                                                                                                                                                                          |
| Affected surfaces | `workqueue.py`, `resources.py`, `sources/codex.py`, `sources/claude.py`                                                                                                                                                                                                                                                                                                                                                    |
| Status            | current                                                                                                                                                                                                                                                                                                                                                                                                                    |

### `SLQD-15` TTY-Aware `plain` Output

| Field             | Value                                                                                                                                               |
| ----------------  | ----------------------------------------------------------------------------------------------------------                                          |
| Decision          | `plain` output is tab-separated when the output is not a TTY; on a TTY it is an aligned, headerless table built with `present.term.format_table`.   |
| Rationale         | Piped output remains machine-readable (tab-separated); TTY output is human-readable and columnar without requiring a separate `--format text` flag. |
| Alternatives      | keep `plain` always tab-separated; make `text` the default on TTY                                                                                   |
| Rejection reason  | tab-separated columns do not align on a TTY; changing the default format based on environment is surprising unless the format name remains `plain`  |
| Affected surfaces | `output.py`, `present/term.py`                                                                                                                      |
| Status            | current                                                                                                                                             |

### `SLQD-11` On-Demand File Access

| Field            | Value                                                                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------                                                     |
| Decision         | File-backed sources read JSONL files through a `ResourceManager` that opens each file once and provides line offsets and a seekable cursor |
| Rationale        | Prevents repeated full-file reads, keeps data in memory only when needed, and centralizes change detection                                 |
| Alternatives     | per-source file reading; general pre-loader that materializes all sessions                                                                 |
| Rejection reason | per-source duplication; a pre-loader is too slow and memory-heavy for large logs                                                           |
| Status           | current                                                                                                                                    |

### `SLQD-12` Listing Reads Metadata Only

| Field            | Value                                                                                                                            |
| ---------------- | --------------------------------------------------------------------------------------                                           |
| Decision         | `DataSource.sessions()` for `ls` parses only session metadata (first/last timestamp, session_meta, line count), not full content |
| Rationale        | Keeps `slq ls <source>` fast and avoids loading large session bodies into memory                                                 |
| Alternatives     | reuse the full-event reader; build session `content` for listings                                                                |
| Rejection reason | full-event reading is too slow for discovery; listing does not need message bodies                                               |
| Status           | current                                                                                                                          |