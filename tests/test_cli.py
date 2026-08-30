import io
from pathlib import Path

import pytest

import slq.cli as cli
from slq.sources.claude import ClaudeSource
from slq.sources.codex import CodexSource


BASE = Path(__file__).parent / "fixtures"


@pytest.fixture
def cli_sources():
    return [
        CodexSource([BASE / "codex" / "sessions"]),
        ClaudeSource([BASE / "claude" / "projects"], sessions_dir=BASE / "claude" / "sessions"),
    ]


def test_list_sessions(cli_sources):
    out = io.StringIO()
    err = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main([":k/session/"], out=out, err=err)
    assert rc == 0
    text = out.getvalue()
    assert "session" in text


def test_query_not(cli_sources):
    out = io.StringIO()
    err = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["not :k/session/"], out=out, err=err)
    assert rc == 0
    text = out.getvalue()
    assert "user" in text
    assert "session" not in text or text.count("session") == 0


def test_query_bang(cli_sources):
    out = io.StringIO()
    err = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["! :k/session/"], out=out, err=err)
    assert rc == 0
    assert "user" in out.getvalue()


def test_query_parens(cli_sources):
    out = io.StringIO()
    err = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["(:k/user/ or :k/agent/) /count/"], out=out, err=err)
    assert rc == 0
    text = out.getvalue()
    assert "count" in text.lower()


def test_count_query(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main(["/count/"], out=out)
    text = out.getvalue()
    assert "the count is 5" in text or "count is 7" in text


def test_count_query_limit(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main(["/count/", "-n", "1"], out=out)
    lines = [l for l in out.getvalue().splitlines() if l.strip()]
    assert len(lines) == 1


def test_stats(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main([":k/session/", "--stats"], out=out)
    text = out.getvalue()
    assert "total=" in text
    assert "by_kind" in text


def test_json_format(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main([":tool/codex/", ":kind/user/", "-f", "json"], out=out)
    text = out.getvalue()
    assert '"kind"' in text
    assert '"tool"' in text


def test_text_format(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main([":tool/codex/", ":kind/user/", "-f", "text"], out=out)
    text = out.getvalue()
    assert "tool" in text
    assert "kind" in text


def test_projected_fields(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main([":k/session/", "-F", "tool,session_id,record_count"], out=out)
    text = out.getvalue()
    parts = text.split("\t")
    assert parts[0] == "codex" or parts[0] == "claude"
    assert "record_count" not in text or "2" in text


def test_context(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main(["/hello/", "-C", "1"], out=out)
    text = out.getvalue()
    assert ">>" in text


def test_time_filter(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    cli.main([":k/session/", "--since", "2026-08-29"], out=out)
    assert out.getvalue()


def test_ls(cli_sources):
    out = io.StringIO()
    err = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["ls"], out=out, err=err)
    assert rc == 0
    text = out.getvalue()
    assert "codex" in text
    assert "claude" in text


def test_ls_codex(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["ls", "codex"], out=out)
    assert rc == 0
    text = out.getvalue()
    assert "2026-08-29 12:01:00" in text
    assert "aaaaaaaa" in text


def test_ls_claude(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["ls", "claude"], out=out)
    assert rc == 0
    text = out.getvalue()
    assert "2026-08-29 12:00:00" in text
    assert "bbbbbbbb" in text


def test_ls_fields(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["ls", "fields"], out=out)
    assert rc == 0
    text = out.getvalue()
    assert "tool\ttext" in text
    assert "timestamp\tdatetime" in text
    assert "content\ttext" in text
    assert "(" not in text


def test_ls_bare_includes_fieldspec(cli_sources):
    out = io.StringIO()
    cli.SOURCES = cli_sources
    rc = cli.main(["ls"], out=out)
    assert rc == 0
    text = out.getvalue()
    assert "codex" in text
    assert "claude" in text
    assert "tool" in text
    assert "timestamp" in text
