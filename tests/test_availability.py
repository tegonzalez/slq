import io
from pathlib import Path

import slq.cli as cli
from slq.query import parse
from slq.sources.claude import ClaudeSource
from slq.sources.codex import CodexSource
from slq.sources.devin import DevinSource


BASE = Path(__file__).parent / "fixtures"
MISSING = BASE / "missing"


def test_admitted_paths_returns_existing_roots():
    source = CodexSource([BASE / "codex" / "sessions"])
    assert source.admitted_paths() == [BASE / "codex" / "sessions"]


def test_default_paths_keep_missing_declared_roots():
    present = BASE / "codex" / "sessions"
    source = CodexSource([present, MISSING])
    assert source.default_paths == [present, MISSING]
    assert source.admitted_paths() == [present]


def test_admitted_paths_skips_missing_roots():
    source = CodexSource([MISSING])
    assert source.admitted_paths() == []


def test_admitted_paths_dedupes_same_path(tmp_path: Path) -> None:
    target = tmp_path / "sessions"
    target.mkdir()
    (target / "a.jsonl").write_text("{}")
    link = tmp_path / "codex"
    link.symlink_to(target)
    source = CodexSource([target, link])
    assert len(source.admitted_paths()) == 1


def test_available_only_when_admitted():
    source = CodexSource([BASE / "codex" / "sessions"])
    assert source.available() is True

    source = CodexSource([MISSING])
    assert source.available() is False


def test_can_answer_gated_by_availability():
    source = CodexSource([BASE / "codex" / "sessions"])
    ast = parse(":tool/codex/")
    assert source.can_answer(ast) is True

    source = CodexSource([MISSING])
    assert source.can_answer(ast) is False


def test_list_emits_one_record_per_admitted_path():
    source = CodexSource([BASE / "codex" / "sessions"])
    records = list(source.list())
    assert len(records) == 1
    assert records[0].tool == "codex"
    assert str(BASE / "codex" / "sessions") in records[0].path


def test_list_is_empty_when_no_paths_admitted():
    source = CodexSource([MISSING])
    assert list(source.list()) == []


def test_ls_unknown_source_exits_2():
    original = cli.SOURCES
    cli.SOURCES = [CodexSource([BASE / "codex" / "sessions"])]
    try:
        out = io.StringIO()
        err = io.StringIO()
        rc = cli.main(["ls", "nosuch"], out=out, err=err)
    finally:
        cli.SOURCES = original
    assert rc == 2
    assert "unknown" in err.getvalue()


def test_ls_unavailable_source_warns_and_exits_0():
    original = cli.SOURCES
    cli.SOURCES = [CodexSource([MISSING])]
    try:
        out = io.StringIO()
        err = io.StringIO()
        rc = cli.main(["ls", "codex"], out=out, err=err)
    finally:
        cli.SOURCES = original
    assert rc == 0
    assert "not available" in err.getvalue()
    assert "codex" in err.getvalue()


def test_env_paths_override_default_paths():
    source = CodexSource()
    env = {"paths": [BASE / "codex" / "sessions"]}
    assert source.admitted_paths(env) == [BASE / "codex" / "sessions"]


def test_claude_source_adopts_base_predicate():
    source = ClaudeSource(
        [BASE / "claude" / "projects"],
        sessions_dir=BASE / "claude" / "sessions",
    )
    assert source.available() is True

    source = ClaudeSource([MISSING])
    assert source.available() is False


def test_devin_source_adopts_base_predicate() -> None:
    source = DevinSource(paths=[MISSING / "sessions.db"])
    assert source.available() is False
