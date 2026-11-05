from pathlib import Path

import pytest

from slq.eval import evaluate
from slq.query import parse
from slq.sources.claude import ClaudeSource
from slq.sources.codex import CodexSource


BASE = Path(__file__).parent / "fixtures"


def test_codex_records():
    source = CodexSource()
    env = {"paths": [BASE / "codex" / "sessions"]}
    ast = parse(":k/user/")
    records = [r for r in source.records(ast, env) if evaluate(r, ast)]
    assert len(records) == 1
    assert records[0].kind == "user"
    assert "hello count" in records[0].content


def test_codex_session_row():
    source = CodexSource()
    env = {"paths": [BASE / "codex" / "sessions"]}
    ast = parse(":k/session/")
    records = list(source.records(ast, env))
    sessions = [r for r in records if r.kind == "session"]
    assert len(sessions) == 1
    assert sessions[0].record_count == 2
    assert "hello count" in sessions[0].content
    assert "the count is 5" in sessions[0].content


def test_codex_session_only_when_query_permits():
    source = CodexSource()
    env = {"paths": [BASE / "codex" / "sessions"]}
    ast = parse(":k/user/")
    records = list(source.records(ast, env))
    assert all(r.kind != "session" for r in records)


def test_codex_session_id_pushdown():
    source = CodexSource()
    env = {"paths": [BASE / "codex" / "sessions"]}
    ast = parse(":session_id/nomatch/")
    records = list(source.records(ast, env))
    assert records == []


def test_claude_records():
    source = ClaudeSource()
    env = {
        "paths": [BASE / "claude" / "projects"],
        "sessions_dir": BASE / "claude" / "sessions",
    }
    ast = parse(":k/user/")
    records = [r for r in source.records(ast, env) if evaluate(r, ast)]
    assert len(records) == 1
    assert records[0].kind == "user"
    assert records[0].project == "testproj"
    assert records[0].cwd == "/home/dev/projects/test"


def test_claude_session_row():
    source = ClaudeSource()
    env = {
        "paths": [BASE / "claude" / "projects"],
        "sessions_dir": BASE / "claude" / "sessions",
    }
    ast = parse(":k/session/")
    records = list(source.records(ast, env))
    sessions = [r for r in records if r.kind == "session"]
    assert len(sessions) == 1
    assert sessions[0].record_count == 2
    assert sessions[0].cwd == "/home/dev/projects/test"


def test_claude_project_pushdown():
    source = ClaudeSource()
    env = {
        "paths": [BASE / "claude" / "projects"],
        "sessions_dir": BASE / "claude" / "sessions",
    }
    ast = parse(":proj/other/")
    records = list(source.records(ast, env))
    assert records == []


def test_claude_sessions_sorted():
    source = ClaudeSource()
    env = {
        "paths": [BASE / "claude" / "projects"],
        "sessions_dir": BASE / "claude" / "sessions",
    }
    sessions = list(source.sessions(env))
    assert len(sessions) == 1
    assert sessions[0].timestamp is not None


def test_claude_session_cwd_and_model_fallback_without_sidecar(tmp_path: Path) -> None:
    inst_root = tmp_path / "instances" / "personal"
    proj_dir = inst_root / "projects" / "myproj"
    proj_dir.mkdir(parents=True)
    session_file = proj_dir / "sess-fallback.jsonl"
    session_file.write_text(
        '{"type": "last-prompt", "lastPrompt": "hi"}\n'
        '{"type": "user", "cwd": "/work/personal-app", "timestamp": "2026-08-29T12:00:00Z", '
        '"message": {"role": "user", "model": "claude-opus-4-7", "content": "hello"}}\n'
    )

    source = ClaudeSource([inst_root / "projects"])

    ls_sessions = list(source.sessions())
    assert len(ls_sessions) == 1
    assert ls_sessions[0].session_id == "sess-fallback"
    assert ls_sessions[0].profile == "personal"
    assert ls_sessions[0].cwd == "/work/personal-app"
    assert ls_sessions[0].model == "claude-opus-4-7"

    query_sessions = [r for r in source.records(parse(":kind/session/")) if r.kind == "session"]
    assert len(query_sessions) == 1
    assert query_sessions[0].session_id == "sess-fallback"
    assert query_sessions[0].profile == "personal"
    assert query_sessions[0].cwd == "/work/personal-app"
    assert query_sessions[0].model == "claude-opus-4-7"
