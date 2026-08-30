import io

from slq.output import render_records
from slq.present.term import _display_width, stream_table
from slq.schema import Record, SessionRecord


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_plain_tty_is_aligned_table():
    records = [
        SessionRecord(session_id="aaaaaaaa-1111-2222-3333-444444444444"),
        SessionRecord(session_id="bbbbbbbb-2222-3333-4444-555555555555"),
    ]
    out = TTY()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    assert "aaaaaaaa" in text
    assert "bbbbbbbb" in text
    # table has at least one space between columns
    assert "  " in text


def test_plain_piped_is_tab_separated():
    records = [
        SessionRecord(session_id="aaaaaaaa-1111-2222-3333-444444444444"),
    ]
    out = io.StringIO()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    assert "\t" in text


def test_newlines_replaced_with_lf_marker():
    records = [
        Record(content="line one\nline two\r\nline three"),
    ]
    out = TTY()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    assert "[lf]" in text
    assert "line one[lf]line two[lf]line three" in text
    assert "\nline" not in text


def test_tabs_replaced_with_space():
    records = [Record(content="col1\tcol2")]
    out = TTY()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    assert "\t" not in text
    assert "col1 col2" in text


def test_ansi_escape_sequences_stripped():
    records = [Record(content="\x1b[31mred\x1b[0m \x1b]0;title\x07\x1b[?25l")]
    out = TTY()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    assert "\x1b" not in text
    assert "red" in text
    assert "title" not in text
    assert "[25l" not in text


def test_long_unbreakable_content_does_not_overflow():
    records = [Record(content="a" * 200)]
    out = TTY()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    for line in text.split("\n"):
        assert _display_width(line) <= 80


def test_wide_characters_respect_display_width():
    records = [Record(content="一" * 60)]
    out = TTY()
    render_records(records, "plain", out=out)
    text = out.getvalue()
    # Each full-width character occupies two display columns; the TTY table
    # should wrap so no output line exceeds the terminal width.
    assert text.count("一") == 60
    for line in text.split("\n"):
        assert _display_width(line) <= 80


def test_stream_table_widens_columns_per_row():
    lines = list(stream_table(["f1", "f2"], [["a", "x"], ["bbbb", "y"]], width=40))
    assert len(lines) == 2
    assert lines[0].startswith("a ")
    assert lines[1].startswith("bbbb")
    for line in lines:
        assert _display_width(line) <= 40


def test_stream_table_wraps_long_unbreakable_tokens():
    lines = list(stream_table(["f1", "f2"], [["a", "x" * 100]], width=40))
    assert len(lines) >= 3
    for line in lines:
        assert _display_width(line) <= 40


def test_precompute_widths_preserves_global_alignment():
    # With precompute_widths, all rows are collected first and aligned globally.
    records = [
        Record(tool="a", content="x"),
        Record(tool="bbbb", content="y"),
    ]
    out = TTY()
    render_records(records, "plain", out=out, precompute_widths=True)
    text = out.getvalue()
    for line in text.split("\n"):
        assert _display_width(line) <= 80
    # The first row should be padded to the wider "bbbb" column.
    assert "a   " in text or "a    " in text


def test_truncate_around_match_hint():
    content = "x" * 250 + "needle" + "y" * 250
    record = Record(content=content, meta={"hint": {"content": 250}})
    out = io.StringIO()
    render_records([record], "plain", out=out)
    text = out.getvalue()
    assert "needle" in text
    # The content cell starts with the match and ends with the truncation marker.
    cell = text.strip().rsplit("\t", 1)[-1]
    assert cell.startswith("needle")
    assert cell.endswith("... [truncated]")


def test_plain_content_truncated_without_hint():
    record = Record(content="x" * 300)
    out = io.StringIO()
    render_records([record], "plain", out=out)
    text = out.getvalue()
    assert "... [truncated]" in text
