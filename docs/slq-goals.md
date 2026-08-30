---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-goals]; otherwise, do not modify."
---

# SLQ Goals

## Purpose

Define the durable outcomes that make `slq` a trustworthy session-log query tool.

## Goals

| ID     | Priority | Desired outcome            | Success criterion                                                                                                                                                     |
| -----  | -------- | -------------------------- | --------------------------------------------------------------------------------------------------------------                                                        |
| SLQ-G1 | highest  | Unified session log query  | A single `slq` command and `Record` schema query any supported source without source-specific CLIs                                                                    |
| SLQ-G2 | highest  | Source-pushdown efficiency | Sources skip files and sessions the query proves cannot match                                                                                                         |
| SLQ-G3 | highest  | Mechanical correctness     | FBR parser, Record schema, and source adapters have deterministic unit tests                                                                                          |
| SLQ-G4 | high     | Single-line FBR            | Users can write `:k/session/:d/2026/` and `!:k/session/(:date/2026/, :desc/topic/)` without relearning grammar                                                        |
| SLQ-G5 | high     | Source extensibility       | A new source is a new `DataSource` class with no CLI changes                                                                                                          |
| SLQ-G6 | medium   | Doc-graph governance       | `slq` project docs are governed, lintable, and durable                                                                                                                |
| SLQ-G7 | medium   | Human-readable output      | Plain, JSON, and text (TTY-aware table) outputs are deterministic and field-selectable                                                                                |
| SLQ-G8 | high     | Resource efficiency        | Sources open each backend once (one JSONL through the `ResourceManager`, one SQLite connection), share source-agnostic resources, and read only metadata for listings |
| SLQ-G9 | high     | POSIX host portability     | `slq` and its test suite run unmodified on Linux and macOS; host-specific stores are declared as candidate roots rather than selected with host branches              |

## Goal Relationships

`SLQ-G1`, `SLQ-G2`, and `SLQ-G3` are foundations: one surface, fast execution, and tested correctness. `SLQ-G4` and `SLQ-G5` make that surface usable and extensible. `SLQ-G6` keeps the project governable. `SLQ-G7` distinguishes display from query semantics. `SLQ-G8` keeps the tool usable on large log directories by centralizing file access and reading only what is needed. `SLQ-G9` keeps the unified surface unchanged across supported hosts and extends source discovery without host-specific command paths.

## Success Criteria

- `slq` runs against every admitted local Codex, Claude, Cursor, and Devin store with no source-specific flags.
- A source with no admitted path is absent from `slq ls` and is skipped by queries instead of failing.
- `slq ls codex` lists sessions from `~/.codex/sessions` and lists a symlinked root once.
- A query with `:s/5df37bef/` opens only the matching session file.
- A query with `:s/shining-brass/` against the devin database applies regex, kind, timestamp, and session filters in SQLite.
- The FBR grammar parses with `&`, `|`, `!`, `not`, and optional spaces.
- The `Record` schema contains every selectable field and all sources map to it.
- `slq ls` and `slq ls <source>` list sources and session files as `Record` DTOs.
- `slq ls codex` completes in under one second for thousands of session files using the `WorkQueue`.
- `Record` fields render consistently for `datetime`, `hash`, and `short-hash` across output formats.
- `plain` output is tab-separated when piped and columnar when displayed on a TTY.
- A new source can be added by implementing `DataSource` and registering it.
- `dg lint` passes on every governed `slq` doc.
- `uv run pytest -x` passes on Linux and macOS with a host-owned virtual environment.
- Output formatters are pure consumers of a `Record` cursor and support `plain`, `json`, and `text`.

## Priorities And Tradeoffs

The priority scale is `highest > high > medium`. Unified query surface outranks source-specific shortcuts. Source pushdown outranks exhaustive matching because session logs can be large. Field-bounded regex outranks natural language because determinism is required. Durable governance outranks ad-hoc notes because the project must remain maintainable. Context conservation outranks a shorter prompt: a user must explicitly choose sessions or exclude them rather than the tool hiding dimensionality. Declared candidate roots outrank host detection because discovery must remain readable from `default_paths`. Reporting a source as unavailable outranks reporting it as empty because absence of a store and absence of matches are different answers.