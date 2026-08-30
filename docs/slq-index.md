---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-index]; otherwise, do not modify."
---

# SLQ Authority Index

## Purpose

Route readers and implementing agents to the durable owners of `slq` outcomes, behavior, architecture, constraints, artifact lifecycle, and mechanical command boundaries.

## Authority Basis

| Authority ID | Priority                                                                                                       | Class                   | Surface                                     | Scope                                                                                          | Dimensions                                                   | Disposition                            | Closure               | Expansion                                                   |
| ------------ | -----------------------------------------------------------------------------------------------------------    | ----------------------- | ------------------------------------------  | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------- | -------------------   | ----------------------------------------------------------- |
| SLQA-001     | `alignment=highest(SLQ-G1); goal-priority=highest(SLQ-G1); outcome-tradeoffs=highest(SLQ-G1)`                  | `dc-doc-goals`          | [Project goals](slq-goals.md)               | Product outcomes, priorities, tradeoffs, and success criteria                                  | alignment; goal-priority; outcome-tradeoffs                  | noncompeting · priority source         | `SLQA-001`            | new durable outcome or priority relation                    |
| SLQA-002     | `behavior=highest(SLQ-G1); public-contracts=highest(SLQ-G1); diagnostics=high(SLQ-G3)`                         | `dc-doc-spec`           | [Product specification](slq-spec.md)        | CLI surface (query and `ls`), FBR grammar, output formats, and diagnostics                     | behavior; public-contracts; diagnostics                      | noncompeting · behavioral owner        | `SLQA-002`            | new consumer-visible behavior or public surface             |
| SLQA-003     | `architecture=highest(SLQ-G1); mechanisms=highest(SLQ-G2); seams=highest(SLQ-G4); rationale=high(SLQ-G5)`      | `dc-doc-design`         | [Architecture design](slq-design.md)        | Modules, seams, data sources, cursor, query engine, presentation, and rationale                | architecture; mechanisms; seams; rationale                   | noncompeting · mechanism owner         | `SLQA-002 → SLQA-003` | new mechanism, seam, module, or load-bearing decision       |
| SLQA-004     | `negative-guidance=highest(SLQ-G1); failure-detection=highest(SLQ-G3); replacement-boundaries=highest(SLQ-G1)` | `dc-doc-constraints`    | [Constraints](slq-constraints.md)           | Reusable forbidden query/source/output patterns, detection signals, and replacements           | negative-guidance; failure-detection; replacement-boundaries | noncompeting · negative-guidance owner | `SLQA-004`            | new reusable failure pattern with detection and replacement |
| SLQA-005     | `positive-guidance=highest(SLQ-G6); behavior=high(SLQ-G1); extensibility=high(SLQ-G5)`                         | `dc-doc-guidelines`     | [Guidelines](slq-guidelines.md)             | Positive patterns for adding sources, fields, output formatters, and CLI subcommands           | positive-guidance; behavior; extensibility                   | noncompeting · positive-guidance owner | `SLQA-005`            | new recommended pattern or source contribution              |
| SLQA-006     | `verification=highest(SLQ-G3); coverage=high(SLQ-G7); quality=high(SLQ-G8)`                                    | `dc-doc-test-plan`      | [Test plan](slq-test-plan.md)               | Verification strategy, fixture sources, and acceptance criteria                                | verification; coverage; quality                              | noncompeting · verification owner      | `SLQA-002 → SLQA-006` | new verification surface or acceptance criterion            |
| SLQA-007     | `rationale=highest(SLQ-G5); principles=high(SLQ-G6)`                                                           | `dc-doc-eng-principles` | [Engineering principles](slq-principles.md) | Source-independent design criteria, rationale, and tradeoffs                                   | rationale; principles; tradeoffs                             | noncompeting · rationale owner         | `SLQA-003 → SLQA-007` | new generalized engineering principle                       |

`Priority` is a dimension-indexed profile derived from durable goal priorities. Class, surface, path, recency, table position, prose confidence, implementation behavior, test output, and requester-supplied integers contribute no value.

A missing owner gates only an authority question routed by this index; a nearby or historical document is not a substitute.

## Query Routes

| Question                             | Kind    | Ordered owners                              | Output                                                    | Missing-input behavior            |
| ------------------------------------ | ------- | ------------------------------------------- | --------------------------------------------------------- | --------------------------------- |
| What must `slq` achieve?             | direct  | project goals                               | Desired outcome, priority, success criteria               | Report missing goals owner        |
| What is the CLI surface?             | direct  | product specification                       | FBR grammar, subcommands, output formats, exit codes      | Report missing spec owner         |
| How is a query executed?             | derived | product specification → architecture design | Pipeline from FBR to Record cursor                        | Gate on first missing owner       |
| What source adapters exist?          | derived | architecture design → guidelines            | DataSource protocol and source conventions                | Gate on first missing owner       |
| What patterns are prohibited?        | direct  | constraints                                 | Forbidden pattern, detection, replacement                 | Report no negative-guidance owner |
| How is a new source added?           | derived | guidelines → design → spec                  | Extension contract and public-surface changes             | Gate on first missing owner       |
| What is verified?                    | direct  | test plan                                   | Strategy, fixtures, acceptance                            | Report missing verification owner |
| What engineering principles apply?   | direct  | engineering principles                      | Generalized criteria, rationale, tradeoffs                | Report missing principles owner   |
| What sources/sessions exist?         | derived | product specification → architecture design | `ls`, `DataSource.list`, `DataSource.sessions`            | Gate on first missing owner       |
| What output renderers exist?         | derived | architecture design → product specification | `present`, `output.render_records`                        | Gate on first missing owner       |
| How are files opened and cached?     | derived | architecture design → guidelines            | `ResourceManager`, `FileResource`, on-demand reads        | Gate on first missing owner       |
| How is listing parallelized?         | derived | architecture design → guidelines            | `WorkQueue`, chunk mapping, `SLQ_WORKERS`                 | Gate on first missing owner       |
| How are record fields rendered?      | derived | architecture design → guidelines            | `record_field`, `FIELD_RENDERERS`, `Record` subclasses    | Gate on first missing owner       |
| How are session listings sorted?     | derived | architecture design → guidelines            | `_session_sort_key`, `_file_mtime`, `DataSource.sessions` | Gate on first missing owner       |
| What record fields can I query?      | derived | product specification → architecture design | `slq ls fields`, `FieldRecord`, `Record.record_fields`    | Gate on first missing owner       |
| How are field prefixes resolved?     | derived | product specification → architecture design | `resolve_field_prefix`, `VALID_FIELD_NAMES`               | Gate on first missing owner       |
| How is the output projection chosen? | derived | product specification → architecture design | `extract_output_fields`, display-only `:<field>` terms    | Gate on first missing owner       |
| How are platform paths compared?     | derived | architecture design → guidelines            | `logical_cwd`, `same_path`, `compatible_python`           | Gate on first missing owner       |

## Durable Boundary

The authority basis consists of the listed members and the artifacts they route to. `dc-doc-plan` instances under `.planning/`, progress notes, and transient fixtures are temporal. Files outside frontmatter-selected membership receive no authority, lifecycle, retention, or deletion result from this index.

## Consumer Questions

This index is complete for alignment, behavior, architecture, source extension, prohibited patterns, verification, and engineering principles. Active work, implementation order, and current progress have no durable owner here.