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


def test_claude_default_roots_discovers_ccs_instances_and_dedupes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    default_projects = home / ".claude" / "projects"
    default_projects.mkdir(parents=True)

    ccs_dir = tmp_path / "ccs"
    fh_projects = ccs_dir / "instances" / "forhumanity" / "projects"
    personal_projects = ccs_dir / "instances" / "personal" / "projects"
    hidden_projects = ccs_dir / "instances" / ".claude" / "projects"
    fh_projects.mkdir(parents=True)
    personal_projects.mkdir(parents=True)
    hidden_projects.mkdir(parents=True)

    # SymlinkCLAUDE_CONFIG_DIR to forhumanity to verify inode deduplication
    cfg_link = tmp_path / "active-instance"
    cfg_link.symlink_to(ccs_dir / "instances" / "forhumanity")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg_link))
    monkeypatch.setenv("CCS_DIR", str(ccs_dir))

    source = ClaudeSource()
    admitted = source.admitted_paths()
    assert len(admitted) == 3
    profiles = [r.profile for r in source.list()]
    assert profiles == ["forhumanity", "default", "personal"]


def test_claude_default_roots_fall_back_to_home_ccs_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    (home / ".ccs" / "instances" / "work" / "projects").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CCS_DIR", raising=False)

    profiles = [r.profile for r in ClaudeSource().list()]
    assert profiles == ["default", "work"]


def test_claude_per_instance_sessions_sidecar_and_profile_pushdown(tmp_path: Path) -> None:
    default_root = tmp_path / ".claude"
    (default_root / "projects" / "p1").mkdir(parents=True)
    (default_root / "sessions").mkdir(parents=True)
    (default_root / "projects" / "p1" / "s1.jsonl").write_text(
        '{"message": {"role": "user", "content": "from default", "timestamp": "2026-08-29T12:00:00Z"}}\n'
    )
    (default_root / "sessions" / "101.json").write_text(
        '{"sessionId": "s1", "cwd": "/work/default", "startedAt": 1788004800000}\n'
    )

    fh_root = tmp_path / "instances" / "forhumanity"
    (fh_root / "projects" / "p2").mkdir(parents=True)
    (fh_root / "sessions").mkdir(parents=True)
    (fh_root / "projects" / "p2" / "s2.jsonl").write_text(
        '{"message": {"role": "user", "content": "from fh", "timestamp": "2026-08-29T13:00:00Z"}}\n'
    )
    (fh_root / "sessions" / "202.json").write_text(
        '{"sessionId": "s2", "cwd": "/work/fh", "startedAt": 1788008400000}\n'
    )

    source = ClaudeSource([default_root / "projects", fh_root / "projects"])

    all_sessions = {s.session_id: s for s in source.sessions()}
    assert set(all_sessions.keys()) == {"s1", "s2"}
    assert all_sessions["s1"].profile == "default"
    assert all_sessions["s1"].cwd == "/work/default"
    assert all_sessions["s2"].profile == "forhumanity"
    assert all_sessions["s2"].cwd == "/work/fh"

    # Root-level pushdown on :profile/forhumanity/ skips default root completely
    fh_records = list(source.records(parse(":profile/forhumanity/ :kind/user/")))
    assert len(fh_records) == 1
    assert fh_records[0].session_id == "s2"
    assert fh_records[0].profile == "forhumanity"
    assert fh_records[0].cwd == "/work/fh"
