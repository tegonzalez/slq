---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-readme]; otherwise, do not modify."
---

# slq

`slq` is a small command-line tool for querying session logs from Codex, Claude, Cursor, and Devin with one language and one `Record` schema. It runs on Linux and macOS.

## Features

| Feature                          | What it gives you                                                                            |
| -------------------------------- | --------------------------------------------------------------                               |
| Single query surface             | Query Codex, Claude, Cursor, and Devin logs with the same FBR expression                     |
| Field-bounded regex (FBR)        | `:k/session/`, `:d/2026-08-29/`, `/count/`, `!`, `and`, `or`                                 |
| Source pushdown                  | Skip files the query proves cannot match                                                     |
| Lazy cursor                      | Stream records one pass; limit, time range, and stats overlays                               |
| Context output                   | Grep-style `-C N` context around matching records                                            |
| Multiple formats                 | `plain`, `json`, and `text` (TTY-aware table) output                                         |
| Source listing                   | `slq ls`, `slq ls codex`, `slq ls cursor`; only stores that exist are listed                 |
| POSIX portability                | One code path on Linux and macOS; per-host stores are candidate roots, not host tests        |
| Parallel listing                 | `WorkQueue` starts 1 worker and spawns more only when chunks exceed 10 ms, up to `nproc - 1` |
| Polymorphic fields               | `Record` subclasses choose default fields; `record_field` metadata dispatches renderers      |
| TTY-aware plain output           | `plain` aligns columns on a TTY and stays tab-separated when piped                           |
| On-demand file access            | `ResourceManager` opens each JSONL once with offsets and caching                             |

## Install

`slq` requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

### Run from source

Create a host-owned virtual environment (do not share `.venv` across Linux and macOS):

```bash
uv sync
uv run slq --help
```

### Run the test suite

```bash
uv run pytest
```

### Install as a uv tool

```bash
uv tool install .
```

This builds `slq` and creates the `slq` executable in uv's tool bin directory. Normally that is `~/.local/bin`; if your environment sets `XDG_DATA_HOME`, it will be `$XDG_DATA_HOME/../bin`. Make sure that directory is on your `PATH`.

### Install to a chosen bin directory

```bash
UV_TOOL_BIN_DIR=~/bin uv tool install .
```

### Uninstall

```bash
uv tool uninstall slq
```

## Quickstart

```bash
# List configured data sources and the record fieldspec
slq ls

# List the queryable record fields and their types
slq ls fields

# List codex session files (timestamp and short hash)
slq ls codex

# List Cursor conversations from the local Cursor SQLite store
slq ls cursor

# List all sessions from every available source (use `-n N` for large histories)
slq :kind/session/

# User messages containing "count"
slq :kind/user/ /count/

# Sessions from a specific date
slq :kind/session/ :time/2026-08-29/

# Stats for codex sessions
slq :tool/codex/ :kind/session/ --stats

# TTY-aware table output (only kind and role columns)
slq ':time/2026-08-29/:kind:role' -f text -n 5
```

## Usage

FBR expressions combine field-bounded regexes with `&`, `|`, `and`, `or`, `,`, `!`, and `not`:

```bash
# AND by adjacency or &
slq :kind/user/ /count/
slq :kind/user/ '&' /count/

# OR with | , or or
slq :kind/user/ or :kind/agent/

# NOT with ! or not
slq ! :kind/session/ /count/
slq not :kind/session/ /count/

# Parentheses
slq '(:kind/user/ or :kind/agent/) /count/'

# Filter and select only the columns you want
slq ':time/2026-08-29/:kind:role'
```

## Commands

`slq` uses subcommands. Because FBR expressions start with `:`, `/`, `(`, `!`, or `not`, the `query` subcommand is optional.

```bash
slq query :k/user/ /count/   # explicit
slq :k/user/ /count/         # implicit
```

| Command           | Arguments                 | Purpose                                                    |
| ----------------- | ------------------------- | ----------------------------------------------------       |
| `query <fbr>`     | FBR expression            | Run a query                                                |
| `ls`              |                           | List admitted data sources, paths, and record fields       |
| `ls <source>`     | source name               | List that source's sessions (timestamp, short hash)        |
| `ls fields`       |                           | List canonical record fields (name and type)               |

### Global/query flags

| Flag            | Purpose                                              |
| --------------- | ---------------------------------------------------- |
| `-f FORMAT`     | Output format: `plain` (default), `json`, or `text`  |
| `-F FIELDS`     | Comma-separated display projection                   |
| `-C N`          | Grep-style context: show `N` records around matches  |
| `--stats`       | Emit a `kind='stats'` summary record                 |
| `--since DATE`  | Filter records at or after this timestamp            |
| `--until DATE`  | Filter records at or before this timestamp           |
| `-n N`          | Stop after `N` records                               |
| `-w, --width`   | Pre-calculate TTY column widths and align output     |
| `-s, --stream`  | Stream TTY output without pre-calculating widths     |

The full CLI surface, FBR grammar, and `Record` schema are in `docs/slq-spec.md`.

## Documentation

- [Authority Index](docs/slq-index.md)
- [Goals](docs/slq-goals.md)
- [Design](docs/slq-design.md)
- [Specification](docs/slq-spec.md)
- [Constraints](docs/slq-constraints.md)
- [Guidelines](docs/slq-guidelines.md)
- [Test Plan](docs/slq-test-plan.md)

## Plan

The active work plan is in [.planning/slq-session-log-query-plan.md](.planning/slq-session-log-query-plan.md).