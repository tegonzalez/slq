"""DTO node tree for command output.

Every command builds a tree: a ``Report`` root with typed children.
``present.render`` walks that tree to produce text; ``to_json`` walks it to
produce JSON. This module is intentionally generic so it can be promoted to a
reusable presentation library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

OK = "ok"
WARN = "warn"
FAIL = "fail"
Status = Optional[str]

CELL = "cell"
BLOCK = "block"


@dataclass
class Field:
    """One key/value fact inside a Fields node."""

    key: str
    value: Any
    level: int = 0
    layout: str = CELL
    status: Status = None


@dataclass
class Fields:
    title: Optional[str] = None
    entries: List[Field] = field(default_factory=list)
    kind: str = field(default="fields", init=False, repr=False)


@dataclass
class Table:
    title: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    level: int = 0
    status: Status = None
    kind: str = field(default="table", init=False, repr=False)


@dataclass
class Items:
    title: Optional[str] = None
    items: List[Any] = field(default_factory=list)
    level: int = 0
    status: Status = None
    kind: str = field(default="items", init=False, repr=False)


Child = Union[Fields, Table, Items]


@dataclass
class Report:
    """Root node. ``status`` is OK or FAIL."""

    status: str
    headline: str
    children: List[Child] = field(default_factory=list)


def to_json(report: Report) -> Dict[str, Any]:
    """Serialize a report to a JSON-friendly dict."""

    def _child(node: Child) -> Dict[str, Any]:
        if isinstance(node, Fields):
            return {
                "kind": node.kind,
                "title": node.title,
                "fields": [
                    {"key": f.key, "value": f.value, "layout": f.layout, "status": f.status}
                    for f in node.entries
                ],
            }
        if isinstance(node, Table):
            return {
                "kind": node.kind,
                "title": node.title,
                "status": node.status,
                "columns": list(node.columns),
                "rows": [list(r) for r in node.rows],
            }
        if isinstance(node, Items):
            return {
                "kind": node.kind,
                "title": node.title,
                "status": node.status,
                "items": list(node.items),
            }
        raise TypeError(f"unknown child: {node!r}")

    return {
        "status": report.status,
        "headline": report.headline,
        "children": [_child(c) for c in report.children],
    }


def exit_code_for(status: str) -> int:
    return 0 if status == OK else 1
