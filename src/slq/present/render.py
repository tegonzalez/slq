"""Render a ``Report`` DTO tree to text or JSON."""

from __future__ import annotations

import json
from typing import TextIO

from .dto import Child, Fields, Items, Report, Table, to_json
from .term import format_kv, format_list, format_table


def render_text(report: Report, out: TextIO, verbosity: int = 0) -> None:
    """Render ``report`` as aligned human text."""
    if report.headline:
        out.write(report.headline + "\n")
    for child in report.children:
        _render_child(child, out)


def _render_child(child: Child, out: TextIO) -> None:
    if isinstance(child, Fields):
        pairs = [(f.key, f.value) for f in child.entries]
        if child.title:
            out.write(child.title + "\n")
        out.write(format_kv(pairs) + "\n")
    elif isinstance(child, Table):
        if child.title:
            out.write(child.title + "\n")
        out.write(format_table(child.columns, child.rows) + "\n")
    elif isinstance(child, Items):
        if child.title:
            out.write(child.title + "\n")
        out.write(format_list(child.items) + "\n")


def render_json(report: Report, out: TextIO) -> None:
    json.dump(to_json(report), out, default=str, sort_keys=True)
    out.write("\n")
