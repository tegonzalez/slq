---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-spec]; otherwise, do not modify."
---

# SLQ Product Specification

## Purpose

Specify the consumer-visible behavior of the `slq` command, the FBR query language, and the `Record` schema.

## Public Surface

### CLI

| Surface    | Syntax                                 | Default     | Notes                                                    |
| ---------- | -------------------------------------- | ----------- | -------------------------------------------------------- |
| query      | `slq query [flags] <fbr-expr>`         | —           | all positional arguments joined into one expression      |
|            | `slq <fbr-expr>`                       | —           | shortcut because FBR expressions start with `:` or `/`   |
| help       | `slq`                                  | —           | print usage and exit                                     |
| list       | `slq ls`                               | all sources | list data sources and the record fieldspec               |
|            | `slq ls [source]`                      | all sources | list source sessions                                     |
|            | `slq ls fields`                        | —           | list the record fields (field name and format)           |
| context    | `-C N`, `--context N`                  | disabled    | grep-style output with N lines of context around matches |
| stats      | `--stats`                              | disabled    | consume cursor and emit `kind='stats'` records           |
| width      | `-w`, `--width`                        | `ls`        | pre-calculate column widths and align `plain` TTY output |
| stream     | `-s`, `--stream`                       | `query`     | stream `plain` TTY output without pre-calculating widths |
| format     | `-f {plain,json,text}`                 | `plain`     | global output format for every command                   |
| fields     | `-F FIELDS`, `--fields FIELDS`         | default set | comma-separated display projection                       |
| time range | `--since`, `--until`                   | —           | filter by `timestamp`                                    |
| limit      | `-n N`, `--limit N`                    | no limit    | stop after N records                                     |

### FBR Grammar

```text
expr      := or_expr
or_expr   := and_expr (('|' | 'or' | ',') and_expr)*
and_expr  := not_expr (('&' | 'and' | ws)? not_expr)*
not_expr  := ('!' | 'not')? primary
primary   := fbr | global | '(' expr ')'
fbr       := ':' field? delim regex delim
global    := delim regex delim
field     := [A-Za-z_][A-Za-z0-9_]*
delim     := any non-whitespace, non-alphanumeric, non-underscore char
             except: ! & | ( ) , :
regex     := any non-empty string not containing the chosen delim
ws        := one or more whitespace characters
```

`!` and `not` are NOT; `|` and `,` are OR; `&` and adjacency are AND. Precedence: `!`/`not` > `&`/adjacency > `|`/`or`/`,`.

A `field` is a canonical `Record` field name or an unambiguous prefix. If a prefix matches more than one field, the parser reports an error listing the possible matches. A field name with no regex (e.g. `:kind`) is a display-only term: it selects that column for output without filtering.

### Record Fields

Every source and every output record uses:

- `tool`, `session_id`, `record_id`, `parent_id`, `short_hash` (computed)
- `timestamp`, `end_timestamp`
- `kind`, `role`, `rec_type`, `subtype`
- `content`, `path`, `cwd`, `project`, `model`
- `record_count`, `duration` (session rows)
- `meta`, `raw`

### Default Output

Plain output selects columns from the query by default. If the query contains only filter terms, those fields are displayed. If the query contains display-only terms (`:<field>` with no regex), the output shows exactly those selected fields, in order. `-F/--fields` overrides this auto-projection.

`content` is truncated to 240 characters, with ` ... [truncated]` appended. When the query matches a `content` value, the truncated output starts at the first match offset so the matched text is at position 0 and remains visible. Embedded newlines are rendered as `[lf]` and ANSI/terminal escape sequences are stripped so one record always occupies one output line and cannot corrupt a TTY. `timestamp` is rendered as a human-readable `YYYY-MM-DD HH:MM:SS` string.

When `plain` output is written to a TTY, it is rendered as an aligned, headerless table. For `slq ls` and `slq ls <source>` the table is pre-calculated so every row is aligned globally. For `query` output the table is streamed by default: each record is emitted as it is produced, and column widths may increase (but never decrease) as wider records arrive. Long content that would exceed a column is wrapped, with very long tokens broken at the column boundary. `-w`/`--width` opts out of streaming and pre-calculates column widths from the full result set; `-s`/`--stream` opts into streaming even for `ls`. When it is piped or redirected, it is tab-separated.

`slq ls` (source listing) defaults to the fields `tool` and `path`. `slq ls <source>` defaults to the fields `timestamp` and `short_hash`, giving a compact, human-readable session index. The `short_hash` is a source-specific short identifier computed on demand; codex and claude use the first eight characters of the session UUID, while devin uses a 12-16 character hyphen-bounded slug.

### Field Discovery

`slq ls fields` lists every canonical `Record` field as `field_name` and `field_type` (the renderer/format used by `record_value`). `slq ls` (bare `ls`) lists the configured data sources and then the field spec, so users can see both the source names and the field names available for FBR queries.

## Behavior

### Default Query Semantics

A query evaluates to a lazy `Cursor` of `Record`s. By default both event and session records are materialized unless the AST proves a row type cannot match. For event-only searches the user adds `! :kind/session/` or selects event kinds explicitly.

A field name with no regex (`:<field>`) is a display-only term. It selects the field for output but does not constrain records. If a query contains any display-only terms, the output shows exactly those fields; otherwise it shows the fields used by the filter terms.

### Source Availability and Discovery

`slq` supports Linux and macOS. Windows is not supported.

A source declares candidate discovery roots without testing the host. A candidate root becomes an admitted path when it exists, satisfies the source's admission predicate, and is distinct from its other roots by filesystem identity. A source is available when it has at least one admitted path.

`slq ls` emits one row per admitted path. An unavailable source contributes no rows. `slq ls <source>` on a known but unavailable source warns on stderr, emits no rows, and exits 0; an unknown source exits 2. Queries skip unavailable sources without a diagnostic.

### Platform Primitives

`src/slq/platform.py` exposes the POSIX process and path primitives used by the package:

- `logical_cwd()` returns the working directory, preserving the absolute `PWD` spelling when it names the process working directory.
- `same_path(a, b)` returns true when two paths name the same filesystem object, including a symlink and its target.
- `compatible_python(root)` returns `<root>/.venv/bin/python` only when it is the running interpreter or can execute and report the same machine, byte order, word size, Python version, and implementation; otherwise it returns `sys.executable`.
- `exec_or_run(argv)` currently runs `argv` as a child process. It is reserved for a future interactive process-replacement path.

`uv sync` installs the project into a host-owned virtual environment. `uv run slq` and `uv tool install` invoke `slq.cli:main` through the generated console script.

### Source Pushdown

A `DataSource` may skip files or rows based on `tool`, `session`, `date`, `path`, `cwd`, `project`, `kind`, and `content` constraints. File-based sources read files through the `ResourceManager`, which opens each file once and provides a seekable cursor and line-offset cache. Database-backed sources translate applicable AST filters into source-specific queries; for example, the devin source builds a parameterized SQLite `WHERE` clause so regex, kind, timestamp, and session filters run in the database.

### Parallel Listing

File-based `DataSource.sessions()` partitions the sorted file list and runs each chunk through the `WorkQueue`, a process-wide scheduler. The queue starts with one worker. If a queued chunk waits longer than the default quantum (10 ms) without an idle worker, a new worker is spawned, up to `nproc - 1`. The default worker cap can be overridden with the `SLQ_WORKERS` environment variable. Database-backed sources use their own metadata queries and do not need the `WorkQueue`.

### Output

- `plain`: default fields or selected fields. On a TTY it is an aligned, headerless table; when piped or redirected it is tab-separated. `content` is truncated to a reasonable width and `timestamp` is rendered in `YYYY-MM-DD HH:MM:SS` form.
- `json`: JSON objects for each record, optionally field-projected.
- `text`: TTY-aware aligned table rendering with headers using the `present` text-format library.

### Stats Overlay

`-s`/`--stats` consumes the cursor and yields a summary `Record` with `kind='stats'` and `meta.total`, `meta.by_tool`, `meta.by_kind`, `meta.by_day`. The summary is itself a record and can be output in any format.

### Diagnostics

- Unknown field: error listing valid field names and aliases.
- Invalid regex: error with the failing pattern.
- Empty regex: error; use `/.*/` to match all values.
- Unavailable source: `slq ls <source>` warns with the unmatched candidate roots and exits 0.
- Unknown source: error naming the source; exit 2.

## Precision and Gaps

- `record_count` and `duration` are available only on `kind=session` records.
- Multi-GB single session files are read once per process through the `ResourceManager`, which maintains line byte-offsets for seeking and an in-memory cache of parsed objects. Full content is still parsed for queries, but `ls` reads only metadata.
- Database-backed sources (such as devin) open one connection per query and push applicable filters down to the database. A custom SQLite `REGEXP` UDF supports FBR regex terms.
- Discovery is owned by `DataSource.default_paths` and the source's admission predicate; there are no per-source path flags.
- Date matching is regex against the rendered `YYYY-MM-DD HH:MM:SS` timestamp string; no numeric comparison operators exist yet.