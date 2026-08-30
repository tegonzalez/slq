"""TTY-aware terminal helpers (stdlib only; macOS and Linux).

Adapted from the doc-graph present layer for table rendering. This module is
intended as a candidate for promotion to a reusable presentation library.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
import unicodedata
from typing import Iterable, List, Optional, Sequence, TextIO, Tuple, Union

Cell = Union[str, int, float, None]


def stdout_is_tty(stream: Optional[TextIO] = None) -> bool:
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def columns(fallback: int = 80, stream: Optional[TextIO] = None) -> int:
    """Return usable terminal width.

    Prefers the stream's TTY size, then COLUMNS, then ``fallback``.
    Clamped to a readable minimum so tables do not collapse.
    """
    stream = stream or sys.stdout
    env = os.environ.get("COLUMNS")
    if env and env.isdigit():
        width = int(env)
    else:
        try:
            width = shutil.get_terminal_size(fallback=(fallback, 24)).columns
        except Exception:
            width = fallback
    if not stdout_is_tty(stream) and not (env and env.isdigit()):
        width = fallback
    return max(40, width)


def _cell(value: Cell) -> str:
    if value is None:
        return ""
    return str(value)


def _display_width(text: str) -> int:
    """Return the number of terminal columns the string occupies.

    Wide East Asian characters count as 2 columns, combining/format/control
    characters as 0, and everything else as 1.
    """
    width = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Mc", "Me", "Cf") or cat == "Cc" or ch in "\n\r\t":
            continue
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def _wrap_text(text: str, width: int, indent: str = "") -> List[str]:
    """Wrap ``text`` to ``width`` display columns, breaking long words.

    Unlike ``textwrap.wrap``, this respects display width and will split a
    single word when it is wider than ``width``. The ``[lf]`` marker produced
    by the output layer is treated as a token so it is never split in half.
    """
    import re

    if width < 1:
        width = 1
    # Split on whitespace while treating ``[lf]`` as a protected token.
    parts = re.split(r"(\[lf\])", text)
    words: List[str] = []
    for part in parts:
        if part == "[lf]":
            words.append(part)
        else:
            words.extend(part.split())
    if not words:
        return [indent] if indent else [""]

    lines: List[str] = []
    current = ""
    current_w = 0

    def flush() -> None:
        nonlocal current, current_w
        if current:
            lines.append(indent + current)
            current = ""
            current_w = 0

    for word in words:
        word_w = _display_width(word)
        if word_w > width:
            flush()
            piece = ""
            piece_w = 0
            for ch in word:
                chw = _display_width(ch)
                cat = unicodedata.category(ch)
                # Keep combining marks with the preceding base character.
                if piece and piece_w + chw > width and cat not in ("Mn", "Mc", "Me"):
                    lines.append(indent + piece)
                    piece = ch
                    piece_w = chw
                else:
                    piece += ch
                    piece_w += chw
            current = piece
            current_w = piece_w
            continue

        if current and current_w + 1 + word_w <= width:
            current += " " + word
            current_w += 1 + word_w
        else:
            flush()
            current = word
            current_w = word_w

    flush()
    return lines if lines else [indent] if indent else [""]


def wrap_text(text: str, width: int, indent: str = "") -> List[str]:
    if width < 8:
        width = 8
    body = _wrap_text(text, width)
    return [indent + line for line in body]


def _is_atomic(cell: str) -> bool:
    """A cell with no internal whitespace on its first line."""
    first_line = cell.split("\n", 1)[0]
    return bool(first_line) and not any(ch.isspace() for ch in first_line)


def _compute_fixed(
    natural: List[int],
    atomic_floor: List[int],
    width: int,
    max_col: int,
) -> List[int]:
    """Return a concrete column-width allocation for the given natural widths."""
    fixed = list(natural)
    cols = len(fixed)
    if cols == 1:
        last_natural = fixed[0]
        cap = max(width, atomic_floor[0])
        fixed[0] = cap if last_natural > cap else last_natural
    else:
        for i in range(cols - 1):
            cap = max(max_col, atomic_floor[i])
            fixed[i] = min(fixed[i], cap)
        gutter = 2 * (cols - 1)
        remaining = max(12, width - sum(fixed[:-1]) - gutter)
        last_natural = fixed[-1]
        fixed[-1] = remaining if last_natural > remaining else last_natural
    return fixed


def _pad(cell: str, col_w: int) -> List[str]:
    """Return ``cell`` as a list of wrapped or padded lines of width ``col_w``."""
    if _display_width(cell) > col_w:
        return _wrap_text(cell, col_w)
    return [cell + (" " * (col_w - _display_width(cell)))]


def _render_row(cells: Sequence[str], fixed: Sequence[int], cols: int) -> List[str]:
    """Render one row of cells using the given column widths."""
    parts = [_pad(cells[i], fixed[i]) for i in range(cols)]
    height = max(len(p) for p in parts)
    lines = []
    for r in range(height):
        chunks = []
        for i, part in enumerate(parts):
            chunk = part[r] if r < len(part) else " " * fixed[i]
            if i < cols - 1:
                pad_w = fixed[i] - _display_width(chunk)
                if pad_w > 0:
                    chunk = chunk + (" " * pad_w)
            chunks.append(chunk)
        lines.append("  ".join(chunks).rstrip())
    return lines


def format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Cell]],
    width: Optional[int] = None,
    *,
    max_col: int = 36,
    show_header: bool = True,
) -> str:
    """Align columns to content width; wrap overflow (no ellipsis)."""
    width = width if width is not None else columns()
    if not headers:
        return ""

    cols = len(headers)
    str_rows = [[_cell(c) for c in row] for row in rows]
    for row in str_rows:
        if len(row) < cols:
            row.extend([""] * (cols - len(row)))
        elif len(row) > cols:
            del row[cols:]

    natural = [_display_width(h) for h in headers]
    atomic_floor = [_display_width(h) if _is_atomic(h) else 0 for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            first_line = cell.split("\n")[0]
            natural[i] = max(natural[i], _display_width(first_line))
            if _is_atomic(cell):
                atomic_floor[i] = max(atomic_floor[i], _display_width(first_line))

    fixed = _compute_fixed(natural, atomic_floor, width, max_col)

    out: List[str] = []
    if show_header:
        out.extend(_render_row(list(headers), fixed, cols))
        rule = "  ".join("-" * fixed[i] for i in range(cols))
        out.append(rule[:width].rstrip())
    for row in str_rows:
        out.extend(_render_row(row, fixed, cols))
    return "\n".join(out)


def stream_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[Cell]],
    width: Optional[int] = None,
    *,
    max_col: int = 36,
) -> Iterator[str]:
    """Yield table rows one at a time, widening columns as new rows arrive.

    Columns are never shrunk once a row has been emitted, so previously printed
    rows keep their alignment. Long content is wrapped to the current column
    width, with unbreakable tokens split when necessary.
    """
    width = width if width is not None else columns()
    if not headers:
        return

    cols = len(headers)
    natural = [_display_width(h) for h in headers]
    atomic_floor = [_display_width(h) if _is_atomic(h) else 0 for h in headers]
    fixed = list(natural)

    for row in rows:
        cells = [_cell(c) for c in row]
        if len(cells) < cols:
            cells.extend([""] * (cols - len(cells)))
        elif len(cells) > cols:
            cells = cells[:cols]

        for i, cell in enumerate(cells):
            first_line = cell.split("\n")[0]
            cell_w = _display_width(first_line)
            if cell_w > natural[i]:
                natural[i] = cell_w
            if _is_atomic(cell):
                if cell_w > atomic_floor[i]:
                    atomic_floor[i] = cell_w

        new_fixed = _compute_fixed(natural, atomic_floor, width, max_col)
        # Never shrink a column once we have printed rows with it.
        for i in range(cols):
            if new_fixed[i] > fixed[i]:
                fixed[i] = new_fixed[i]

        yield from _render_row(cells, fixed, cols)


def format_kv(pairs: Iterable[Tuple[str, Cell]], width: Optional[int] = None) -> str:
    items = [(k, _cell(v)) for k, v in pairs]
    if not items:
        return ""
    width = width if width is not None else columns()
    key_w = min(28, max(_display_width(k) for k, _ in items))
    lines: List[str] = []
    for key, value in items:
        prefix = f"{(key + ':').ljust(key_w + 1)} "
        avail = max(12, width - _display_width(prefix))
        wrapped = wrap_text(value, avail)
        if not wrapped:
            lines.append(prefix.rstrip())
            continue
        lines.append(prefix + wrapped[0])
        indent = " " * _display_width(prefix)
        for cont in wrapped[1:]:
            lines.append(indent + cont)
    return "\n".join(lines)


def format_list(items: Sequence[Cell], width: Optional[int] = None, bullet: str = "- ") -> str:
    width = width if width is not None else columns()
    lines: List[str] = []
    indent = " " * _display_width(bullet)
    for item in items:
        text = _cell(item)
        wrapped = wrap_text(text, max(12, width - _display_width(bullet)))
        if not wrapped:
            lines.append(bullet.rstrip())
            continue
        lines.append(bullet + wrapped[0])
        for cont in wrapped[1:]:
            lines.append(indent + cont)
    return "\n".join(lines)


def format_section(title: str, body: str) -> str:
    body = body.rstrip()
    if not body:
        return title
    return f"{title}\n{body}"
