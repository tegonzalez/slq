import shutil
import sqlite3
from pathlib import Path

from slq.query import parse
from slq.sources.claude import ClaudeSource
from slq.sources.codex import CodexSource
from slq.sources.devin import DevinSource


BASE = Path(__file__).parent / "fixtures" / "codex" / "sessions"


def _make_db(path: Path, session_id: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            working_directory TEXT,
            backend_type TEXT,
            model TEXT,
            agent_mode TEXT,
            created_at TEXT,
            last_activity_at TEXT,
            title TEXT,
            workspace_dirs TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE message_nodes (
            row_id INTEGER PRIMARY KEY,
            session_id TEXT,
            node_id INTEGER,
            parent_node_id INTEGER,
            chat_message TEXT,
            created_at INTEGER
        )
        """
    )
    import json

    conn.execute(
        "INSERT INTO sessions (id, working_directory, backend_type, model, agent_mode, created_at, last_activity_at, title, workspace_dirs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, "/tmp", "backend", "m", "mode", "1787351499", "1787351499", session_id, json.dumps([])),
    )
    conn.execute(
        "INSERT INTO message_nodes (session_id, node_id, parent_node_id, chat_message, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            session_id,
            0,
            None,
            json.dumps({"role": "user", "content": "hello", "metadata": {"created_at": "2026-08-21T22:31:40.000000000Z"}}),
            1787351499,
        ),
    )
    conn.commit()
    conn.close()


def test_codex_admits_only_jsonl_directories() -> None:
    with_jsonl = BASE
    without_jsonl = Path(__file__).parent / "fixtures" / "claude" / "sessions"
    source = CodexSource([with_jsonl, without_jsonl])
    assert source.default_paths == [with_jsonl, without_jsonl]
    assert source.admitted_paths() == [with_jsonl]


def test_codex_dedupes_symlinked_root(tmp_path: Path) -> None:
    target = tmp_path / "sessions"
    target.mkdir()
    shutil.copytree(BASE, target, dirs_exist_ok=True)
    link = tmp_path / "alias"
    link.symlink_to(target)

    source = CodexSource([target, link])
    sessions = list(source.sessions())
    assert len(sessions) == 1


def test_codex_multiroot_returns_sessions_from_each_root(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_a.mkdir()
    (root_a / "2026" / "08" / "29").mkdir(parents=True)
    (root_a / "2026" / "08" / "29" / "aaaaaaaa-1111-2222-3333-444444444444.jsonl").write_text(
        '{"role": "user", "content": "hello a", "created_at": "2026-08-29T12:00:00.000Z"}\n'
    )

    root_b = tmp_path / "b"
    root_b.mkdir()
    (root_b / "2026" / "08" / "29").mkdir(parents=True)
    (root_b / "2026" / "08" / "29" / "bbbbbbbb-1111-2222-3333-444444444444.jsonl").write_text(
        '{"role": "user", "content": "hello b", "created_at": "2026-08-29T12:01:00.000Z"}\n'
    )

    source = CodexSource([root_a, root_b])
    sessions = list(source.sessions())
    assert len(sessions) == 2
    assert {s.session_id for s in sessions} == {
        "aaaaaaaa-1111-2222-3333-444444444444",
        "bbbbbbbb-1111-2222-3333-444444444444",
    }


def test_devin_queries_multiple_databases(tmp_path: Path) -> None:
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    _make_db(db_a, "session-a")
    _make_db(db_b, "session-b")

    source = DevinSource(paths=[db_a, db_b])
    ast = parse(":kind/user/")
    records = [r for r in source.records(ast) if r.kind == "user"]
    assert len(records) == 2
    assert {r.session_id for r in records} == {"session-a", "session-b"}


def test_claude_uses_admitted_paths(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "proj").mkdir()
    (projects / "proj" / "session.jsonl").write_text(
        '{"message": {"role": "user", "content": "hi", "timestamp": "2026-08-29T12:00:00Z"}}\n'
    )
    sessions = tmp_path / "sessions"
    sessions.mkdir()

    source = ClaudeSource([projects], sessions_dir=sessions)
    records = list(source.records(parse(":kind/user/")))
    assert len(records) == 1
    assert records[0].project == "proj"
