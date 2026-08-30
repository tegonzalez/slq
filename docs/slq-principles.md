---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-eng-principles]; otherwise, do not modify."
---

# SLQ Engineering Principles

## Purpose

Capture durable, source-independent engineering principles that guide the design of `slq`. These are generalized decision criteria; the specific mechanisms, rejected alternatives, and source-specific mappings live in [slq-design.md](slq-design.md).

## Domain

The `slq` session-log query tool and any similar tool that unifies multiple record-oriented sources behind one query surface.

## Terminology

- **Cursor**: a lazy one-pass iterator over `Record` DTOs.
- **Overlay**: a transform that consumes a cursor and produces a new cursor without changing the underlying source or query.
- **Record superset**: one shared schema that every source maps to, extended only through a `meta`/`raw` escape hatch.
- **Source-owned mapping**: each source is responsible for translating its native format into the shared record surface.

## Principles

### SLQP-1 Lazy one-pass cursors

- **Principle**: Query results are materialized as a lazy one-pass iterator of DTOs.
- **Applicability**: All `slq` query and listing commands.
- **Rationale**: Avoids materializing the full result set; keeps overlays such as projection, context, and stats generic and composable.
- **Counterpressure**: TTY table alignment and pre-calculated column widths may require consuming the cursor early. Opt-out flags such as `-w`/`--width` and `-s`/`--stream` make this visible rather than hidden.
- **Application guidance**: Use the `Cursor` type for every command output. Formatters and overlays consume the cursor once. Do not store cursor iteration state inside `Record` or `DataSource`.

### SLQP-2 Overlays, not output modes

- **Principle**: Transforms such as stats, projection, and context are overlays that consume and yield records, not separate output modes.
- **Applicability**: Any result transformation that does not change the source query semantics.
- **Rationale**: Keeps the output layer thin and reusable; the same formatter can serve queries, listings, and stats without source-specific branches.
- **Counterpressure**: Some overlays (e.g. stats) change the result kind. The overlay must declare the new record kind and not mutate the source cursor.
- **Application guidance**: Implement `-F/--fields`, `-C/--context`, and `--stats` as cursor consumers in the output layer, not as CLI output modes. See `SLQD-6`, `SLQD-7`, and `SLQC-010`.

### SLQP-3 One shared record surface across sources

- **Principle**: All sources emit one `Record` DTO with a common field set and a `meta`/`raw` extension point.
- **Applicability**: Every `DataSource` adapter and every output formatter.
- **Rationale**: One schema lets the query language, evaluator, and output be source-agnostic. New sources do not require CLI or query-language changes.
- **Counterpressure**: A source may have tool-specific metadata that does not fit the shared schema. Use `meta` and `raw` for escape-hatch data only.
- **Application guidance**: Map each source's session and message fields into `Record` fields. Add new query fields to the shared schema before exposing them as FBR aliases. See `SLQD-1`, `SLQG-002`, and `SLQG-008`.

### SLQP-4 Source-owned discovery and mapping

- **Principle**: Each source owns how it discovers files, maps native fields, and decides whether it can answer a query.
- **Applicability**: `DataSource` implementations and the `ResourceManager` contract.
- **Rationale**: Pushdown, file discovery, and format parsing are source-specific. Centralizing them in the source keeps the query engine generic and lets the source exploit its own structure.
- **Counterpressure**: File-lifetime and caching concerns cross source boundaries. The `ResourceManager` centralizes open-file caching and offset tracking so sources remain stateless.
- **Application guidance**: Implement `can_answer`, `records`, `list`, and `sessions` per source. Use the `ResourceManager` for file access rather than calling `Path.open` directly. See `SLQG-011`, `SLQC-011`, and `SLQD-4`.

### SLQP-5 Short identifiers are source-distinguishable

- **Principle**: A source's `Record.short_hash` value must be visually and structurally distinguishable from other sources so that mixed results remain unambiguous.
- **Applicability**: Every `DataSource` that produces a `short_hash` for display or selection.
- **Rationale**: A unified query surface may list records from several sources in one output. If two sources can produce the same short string, users cannot tell which source a record belongs to and selection by `short_hash` becomes ambiguous.
- **Counterpressure**: Longer identifiers consume more display width. The output layer must not force a single fixed width so each source can choose a length appropriate to its native ID format.
- **Application guidance**: Pick a length and alphabet that are unlikely to collide with other active sources. For example, an 8-character hexadecimal prefix is appropriate for UUID-based sources, while a 12-16 character hyphen-bounded slug is appropriate for human-readable session identifiers. Keep `short_hash` short, but not at the cost of cross-source uniqueness. See `SLQA-007`, `SLQG-001`, and `SLQG-007`.

## Examples

- `slq :kind/session/` returns a lazy cursor of session `Record`s. Adding `-s` consumes that cursor with the stats overlay, which yields a single `kind='stats'` record.
- `slq ls codex` asks the codex source to list its session files; the `ResourceManager` opens each JSONL once and reads only metadata.
- `slq ls devin` shows 12-16 character session slugs, while `slq ls codex` shows 8-character UUID prefixes, making cross-source listings easy to scan.

## References

- [Authority index](slq-index.md) for the durable owner of engineering principles.
- [Architecture design](slq-design.md) for concrete mechanisms, seams, and design decisions.
- [Constraints](slq-constraints.md) for forbidden patterns and their replacements.
- [Guidelines](slq-guidelines.md) for positive implementation guidance.
- [Test plan](slq-test-plan.md) for verification and acceptance.
- [Product specification](slq-spec.md) for the public CLI and FBR grammar.