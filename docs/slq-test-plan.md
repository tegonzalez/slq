---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-test-plan]; otherwise, do not modify."
---

# SLQ Test Plan

## Purpose

Define how `slq` is verified before acceptance.

## Strategy

| Level          | Scope                                                                                      | Owner              | Fixtures                                            |
| -------------- | -------------------------------------------------------                                    | ------------------ | --------------------------------------              |
| unit           | `Record`, schema, FBR lexer/parser, AST eval                                               | `slq` test suite   | `tests/fixtures/` JSONL snippets                    |
| source-adapter | codex, claude, and devin mapping to `Record`                                               | source tests       | sample `rollout-*.jsonl`, `*.jsonl`, and SQLite DBs |
| source-list    | source admission, availability, listing, and sessions                                      | source tests       | sample source and session fixtures                  |
| platform       | `logical_cwd()`, `same_path()`, `compatible_python(root)`, and `exec_or_run()`             | `slq` test suite   | temporary interpreters, symlink pairs, PWD values   |
| integration    | end-to-end `slq` against real `~/.codex`, `~/.claude`, and the Devin CLI sessions database | CI or local        | user's own logs, optional                           |
| doc-graph      | `dg lint` on governed docs                                                                 | doc-graph protocol | `docs/` and `.planning/`                            |

## Unit Tests

### FBR Parser

- Parse all legal FBR forms with and without spaces.
- Reject unknown fields and invalid regexes.
- Resolve unambiguous canonical field prefixes (`:time/.../` → `timestamp`, `:to/.../` → `tool`) and reject ambiguous ones (`:re/.../`) with possible matches.
- Parse display-only terms (`:kind:role`) with empty regex; they do not filter.
- Derive the default output projection from the AST (display-only terms override filter fields).
- Verify operator precedence (`!`/`not` > `&`/adjacency > `|`/`or`/`,`).

### Schema and Validation

- Resolve canonical field names exactly.
- Resolve unambiguous canonical field prefixes.
- Reject queries against unknown or ambiguous fields.
- Format `datetime` and `int` fields to string for regex matching.

### Evaluator

- Evaluate each AST node against a synthetic `Record`.
- Test `AND`, `OR`, `NOT`, and field-specific regex.

### Output and Presentation

- Render `Record` lists to `plain`, `json`, and `text` with and without field projection.
- Verify `present.term.format_table` handles atomic cells, wrapping, and narrow TTY widths.
- Verify `present.term.stream_table` widens columns as rows arrive and wraps long tokens.
- Verify `-w`/`--width` pre-calculates column widths and globally aligns `plain` TTY output, and `-s`/`--stream` streams output.
- Verify `content` truncation starts at the first match offset when the query provides one.

### Resource Manager and WorkQueue

- A `FileResource` builds line counts without storing offsets and only builds offsets on indexed access.
- `FileResource.first_object` streams from the start of the file without building offsets.
- `FileResource` detects file changes and invalidates cached counts, offsets, objects, and records.
- Multiple sources share the same `FileResource` from the global `ResourceManager`.
- `WorkQueue` starts with one worker, spawns up to `max(1, nproc - 1)` based on a 10 ms quantum, and honors `SLQ_WORKERS`.
- `WorkQueue` does not spawn a new thread when an existing worker becomes idle within the quantum.
- `ResourceManager.map()` returns results in submission order and is used by `DataSource.sessions()`.
- `SQLBuilder` translates FBR ASTs into parameterized `WHERE` clauses for SQLite, including `AND`, `OR`, `NOT`, regex, `kind`, `timestamp`, and `session_id` constraints.
- `QueryRequest` carries the AST, `since`/`until` bounds, and source environment to every `DataSource.records()` call.

### Platform and Discovery

- `logical_cwd()` returns `PWD` when it is absolute and names the process working directory; otherwise it returns the process working directory.
- `same_path()` treats two paths to one filesystem object, including a symlink and its target, as equal.
- `compatible_python(root)` accepts the project interpreter when it is the running interpreter or reports the running process ABI, and falls back for a missing, unreadable, non-runnable, or foreign candidate.
- A candidate that merely shares the running interpreter's binary magic is not accepted without executing the ABI probe.
- `exec_or_run(argv)` runs a child process through the reserved platform seam.
- Candidate roots remain declared when absent, while `admitted_paths()` retains only existing source-shaped stores.
- Admitted paths collapse a symlink and its target to one filesystem object.
- `available()` and `can_answer()` are false when no path is admitted.

## Source Adapter Tests

- `codex` source emits `Record`s for a sample rollout file and builds a session row when requested.
- `claude` source emits `Record`s for a sample project session file and builds a session row.
- `devin` source emits `Record`s for a sample SQLite sessions database and builds a session row.
- `devin` queries every admitted database rather than selecting the first existing candidate.
- `devin` `short_hash` is 12-16 characters and distinguishable from codex/claude 8-character UUID prefixes.
- `codex` and `claude` `sessions()` return `SessionRecord`s with `default_fields = ("timestamp", "short_hash")`.
- `DataSource.list()` returns one `SourceRecord` per admitted path with `default_fields = ("tool", "path")`.
- An unavailable source is absent from `slq ls`; `slq ls <source>` warns and exits 0, while an unknown source exits 2.
- `slq ls fields` returns `FieldRecord`s with `default_fields = ("field_name", "field_type")`; canonical field names are shown without aliases.
- Bare `slq ls` lists sources and then the `FieldRecord` field spec.
- `DataSource.sessions()` returns `SessionRecord`s sorted by `timestamp` ascending; un-dated records appear first.
- `sessions()` falls back to the session file `mtime` as `timestamp` when no metadata or record timestamp is available.
- Both skip files the AST proves cannot match.

## Integration Tests

- Run `slq` against a temporary copy of real logs.
- Verify `slq ls` and `slq ls <source>` list sources and sessions.
- Verify output for `plain`, `json`, and `text` and for `-s`.
- Verify `-C` context shows the right snippets.

## Acceptance Criteria

- `uv run pytest -x` passes on Linux and macOS with a host-owned virtual environment.
- `dg lint` passes for every `docs/*.md` and `.planning/*.md`.
- `slq` can list sources (`slq ls`) and session files (`ls <source>`); bare `slq` prints usage.
- `slq` can list sessions, filter by date, and grep across codex, claude, and devin logs.
- `slq ls codex` deduplicates a symlinked root and `slq ls` prints only admitted paths.
- `slq` supports `plain`, `json`, and `text` output.
- `plain` output aligns columns on a TTY and is tab-separated when piped.
- `Record` subclasses provide polymorphic `default_fields`; `record_field` metadata drives `FIELD_RENDERERS`.
- `WorkQueue` defaults to `nproc - 1` workers and can be overridden with `SLQ_WORKERS`.
- `slq ls codex` and `slq ls claude` complete quickly without loading full file contents.
- `slq ls devin` and devin queries run SQL pushdown and do not fetch every row.