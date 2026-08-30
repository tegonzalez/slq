import io
import subprocess
import sys
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
    assert "the count is 5" in text
    assert "count is 7" in text


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
    assert "codex" in text
    assert "claude" in text
    assert "2" in text


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


def test_invalid_since_returns_user_error_without_exception(cli_sources):
    original = cli.SOURCES
    cli.SOURCES = cli_sources
    try:
        out = io.StringIO()
        err = io.StringIO()
        rc = cli.main([":kind/user/", "--since", "not-a-time"], out=out, err=err)
    finally:
        cli.SOURCES = original
    assert rc == 2
    assert "invalid timestamp" in err.getvalue()
    assert "not-a-time" in err.getvalue()


def test_closed_stdout_pipe_exits_without_broken_pipe_error():
    child_code = """
import slq.cli as cli
from slq.schema import Record


class Source:
    name = "pipe"

    def can_answer(self, ast):
        return True

    def records(self, ast, env=None):
        for _ in range(10_000):
            yield Record(tool="pipe", kind="user", content="x" * 100)


cli.SOURCES = [Source()]
raise SystemExit(cli.main(["/x/"]))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    process.stdout.close()
    assert process.stderr is not None
    stderr = process.stderr.read()
    return_code = process.wait()
    assert return_code == 0
    assert "BrokenPipeError" not in stderr
