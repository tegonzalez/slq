import json
import re
import sys
from typing import Iterable, Iterator, List, Optional, TextIO

from .present.term import format_table, stdout_is_tty, stream_table
from .schema import Record, record_value


def _default_fields(record: Optional[Record]) -> List[str]:
    if record is None:
        return list(Record.default_fields)
    return list(record.default_fields)


def _with_first(
    records: Iterable[Record], first: Optional[Record]
) -> Iterator[Record]:
    if first is not None:
        yield first
    yield from records


def render_records(
    records: Iterable[Record],
    fmt: str,
    fields: Optional[List[str]] = None,
    out: TextIO = sys.stdout,
    *,
    precompute_widths: bool = False,
) -> None:
    it = iter(records)
    first = next(it, None)
    if fields is None:
        fields = _default_fields(first)

    records_iter: Iterable[Record] = _with_first(it, first)

    if fmt == "json":
        _json_records(records_iter, fields, out)
    elif fmt == "text":
        _text_records(list(records_iter), fields, out)
    elif fmt == "plain":
        _plain_records(records_iter, fields, out, precompute_widths=precompute_widths)
    else:
        raise ValueError(f"unknown format: {fmt!r}")


def _plain_records(
    records: Iterable[Record],
    fields: List[str],
    out: TextIO,
    *,
    precompute_widths: bool = False,
) -> None:
    """Plain output: tab-separated when piped, aligned table on a TTY."""
    if stdout_is_tty(out):
        if precompute_widths:
            _text_records(list(records), fields, out, include_header=False, show_header=False)
        else:
            _stream_text_records(records, fields, out)
        return

    for record in records:
        prefix = ""
        ctx = record.meta.get("context")
        if ctx == "match":
            prefix = ">> "
        elif ctx == "context":
            prefix = "   "
        if prefix:
            out.write(prefix)
        _write_plain_line(record, fields, out)


# Strip ANSI/terminal escape sequences (CSI, OSC, DCS, one-char escapes).
# This protects TTYs from cursor, color, or mode changes embedded in record
# content (e.g. pasted terminal output captured by a source).
_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]|"  # CSI
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)|"  # OSC
    r"[P^_][^\x1b]*(?:\x1b\\)?|"  # DCS/SOS/PM/APC
    r"[@-Z\\^_]"  # one-char escape sequences
    r")"
)

# Remaining terminal-unsafe control characters after line breaks and tabs have
# been normalized (tab and newline are handled explicitly below).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _render_value(value: str, field: str, hint: Optional[int] = None) -> str:
    """Sanitize a field value for terminal or tab-separated display.

    ANSI/terminal escape sequences are removed, tabs and line breaks are
    replaced with displayable markers, and remaining control characters are
    stripped so one record always occupies exactly one output line. Newlines
    are rendered as ``[lf]`` so wrapped content remains visually explicit.
    """
    if field == "content" and hint is not None:
        value = _truncate_around(value, hint)
    value = _ANSI_RE.sub("", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\t", " ")
    value = value.replace("\n", "[lf]")
    value = _CONTROL_RE.sub("", value)
    if field == "content" and hint is None:
        value = _truncate(value)
    return value


def _write_plain_line(record: Record, fields: List[str], out: TextIO) -> None:
    parts: List[str] = []
    hints = record.meta.get("hint", {})
    for f in fields:
        value = record_value(record, f)
        if not value:
            value = "-"
        value = _render_value(value, f, hints.get(f))
        parts.append(value)
    out.write("\t".join(parts) + "\n")
    out.flush()


def _json_records(
    records: Iterable[Record],
    fields: List[str],
    out: TextIO,
) -> None:
    for record in records:
        obj = _record_dict(record, fields)
        if record.meta.get("context"):
            obj["context"] = record.meta["context"]
        out.write(json.dumps(obj, default=_json_default, sort_keys=True) + "\n")
        out.flush()


def _stream_text_records(
    records: Iterable[Record],
    fields: List[str],
    out: TextIO,
) -> None:
    """Render a plain table one record at a time, widening columns as needed."""

    def rows() -> Iterator[List[str]]:
        for record in records:
            row: List[str] = []
            hints = record.meta.get("hint", {})
            for f in fields:
                value = record_value(record, f)
                if not value:
                    value = "-"
                value = _render_value(value, f, hints.get(f))
                row.append(value)
            ctx = record.meta.get("context")
            if ctx:
                marker = ">> " if ctx == "match" else "   "
                row[0] = marker + row[0]
            yield row

    for line in stream_table(fields, rows(), max_col=36):
        out.write(line + "\n")
        out.flush()


def _text_records(
    records: List[Record],
    fields: List[str],
    out: TextIO,
    *,
    include_header: bool = True,
    show_header: bool = True,
) -> None:
    rows: List[List[str]] = []
    has_context = False
    for record in records:
        ctx = record.meta.get("context")
        if ctx:
            has_context = True
        row = []
        hints = record.meta.get("hint", {})
        for f in fields:
            value = record_value(record, f)
            if not value:
                value = "-"
            value = _render_value(value, f, hints.get(f))
            row.append(value)
        rows.append(row)

    headers = list(fields)
    if has_context:
        headers.insert(0, "context")
        for i, record in enumerate(records):
            ctx = record.meta.get("context")
            rows[i].insert(0, ctx or "")

    if not rows:
        return
    if not include_header:
        out.write(format_table(headers, rows, show_header=False) + "\n")
    else:
        out.write(format_table(headers, rows, show_header=show_header) + "\n")
    out.flush()


def _record_dict(record: Record, fields: List[str]) -> dict:
    return {f: _json_default(record_value(record, f)) for f in fields}


def _json_default(value: object) -> object:
    return str(value)


def _truncate(text: str, width: int = 240) -> str:
    if len(text) <= width:
        return text
    return text[:width] + " ... [truncated]"


def _truncate_around(text: str, hint: int, width: int = 240) -> str:
    if len(text) <= width:
        return text
    # Anchor the truncated cell at the match so the matched text is at
    # position 0, then take the full width so the cell is not truncated
    # before the requested number of characters.
    snippet = text[hint:hint + width]
    if hint + width < len(text):
        snippet = snippet + " ... [truncated]"
    return snippet
