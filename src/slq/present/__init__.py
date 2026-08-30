"""TTY-aware text presentation helpers and DTOs.

Intended as a candidate for promotion to a reusable library.
"""

from .dto import Field, Fields, Items, Report, Table
from .render import render_json, render_text
from .term import columns, format_kv, format_list, format_table, format_section, stdout_is_tty, wrap_text

__all__ = [
    "columns",
    "format_kv",
    "format_list",
    "format_section",
    "format_table",
    "Field",
    "Fields",
    "Items",
    "render_json",
    "render_text",
    "Report",
    "stdout_is_tty",
    "Table",
    "wrap_text",
]
