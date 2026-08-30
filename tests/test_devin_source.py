import datetime
import json
import sqlite3
from pathlib import Path

import pytest

from slq.eval import evaluate
from slq.query import parse
from slq.schema import Record
from slq.sources.devin import DevinSource


def _make_db(path: Path) -> None:
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

    conn.execute(
        """
        INSERT INTO sessions
        (id, working_directory, backend_type, model, agent_mode, created_at, last_activity_at, title, workspace_dirs)
        VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-session",
            "/home/dev/projects/test",
            "windsurf",
            "swe-1-7",
            "bypass",
            "1787351499",
            "1787352796",
            "Test Session",
            json.dumps(["/home/dev/projects/test"]),
        ),
    )

    messages = [
        (
            0,
            None,
            {
                "message_id": "msg-system",
                "role": "system",
                "content": "system info",
                "metadata": {
                    "created_at": "2026-08-21T22:31:39.000000000Z",
                    "telemetry": {"source": "system", "operation": "unknown"},
                },
            },
        ),
        (
            1,
            0,
            {
                "message_id": "msg-user",
                "role": "user",
                "content": "hello world",
                "metadata": {
                    "created_at": "2026-08-21T22:31:40.000000000Z",
                    "telemetry": {"source": "user", "operation": "unknown"},
                },
            },
        ),
        (
            2,
            1,
            {
                "message_id": "msg-agent",
                "role": "assistant",
                "content": "hi there",
                "metadata": {
                    "created_at": "2026-08-21T22:31:41.000000000Z",
                    "finish_reason": "stop",
                    "generation_model": "swe-1-7",
                    "metrics": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_time_ms": 1234,
                    },
                    "telemetry": {"source": "assistant", "operation": "inference"},
                },
            },
        ),
        (
            3,
            2,
            {
                "message_id": "msg-tool-call",
                "role": "assistant",
                "content": "",
                "metadata": {
                    "created_at": "2026-08-21T22:31:42.000000000Z",
                    "finish_reason": "tool_calls",
                    "extensions": {
                        "chisel/tool_call_content": {
                            "functions.read:0": {
                                "toolCallId": "functions.read:0",
                                "kind": "read",
                                "rawInput": {"file_path": "/tmp/foo"},
                            }
                        }
                    },
                    "telemetry": {"source": "assistant", "operation": "inference"},
                },
            },
        ),
        (
            4,
            3,
            {
                "message_id": "msg-tool-output",
                "role": "tool",
                "content": "file contents here",
                "metadata": {
                    "created_at": "2026-08-21T22:31:43.000000000Z",
                    "extensions": {
                        "chisel/tool_result_meta": {"kind": "read", "success": True},
                        "chisel/tool_call_timing": {"duration_ms": 42},
                    },
                    "telemetry": {"source": "tool_result", "operation": "tool"},
                },
            },
        ),
    ]

    for node_id, parent_id, chat in messages:
        conn.execute(
            "INSERT INTO message_nodes (session_id, node_id, parent_node_id, chat_message, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                "test-session",
                node_id,
                parent_id,
                json.dumps(chat),
                1787351499,
            ),
        )

    conn.commit()
    conn.close()


@pytest.fixture
def devin_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "sessions.db"
    _make_db(db_path)
    return db_path


def test_devin_sessions(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    sessions = list(source.sessions())
    assert len(sessions) == 1
    assert sessions[0].kind == "session"
    assert sessions[0].session_id == "test-session"
    assert sessions[0].record_count == 4  # all except system
    assert sessions[0].content == "Test Session"
    assert sessions[0].model == "swe-1-7"


def test_devin_records_user(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse(":kind/user/")
    records = list(source.records(ast))
    assert len(records) == 1
    rec = records[0]
    assert rec.kind == "user"
    assert rec.role == "user"
    assert rec.content == "hello world"
    assert rec.session_id == "test-session"


def test_devin_records_agent(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse(":kind/agent/")
    records = list(source.records(ast))
    assert len(records) == 1
    assert records[0].kind == "agent"
    assert records[0].content == "hi there"
    assert records[0].model == "swe-1-7"
    assert records[0].duration == 1.234


def test_devin_records_tool_call(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse(":kind/tool_call/")
    records = list(source.records(ast))
    assert len(records) == 1
    assert records[0].kind == "tool_call"
    assert 'functions.read:0' in records[0].content
    assert records[0].rec_type == "tool_calls"


def test_devin_records_tool_output(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse(":kind/tool_output/")
    records = list(source.records(ast))
    assert len(records) == 1
    assert records[0].kind == "tool_output"
    assert records[0].content == "file contents here"
    assert records[0].duration == 0.042


def test_devin_records_session(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse(":kind/session/")
    records = list(source.records(ast))
    # events + one session record
    assert any(r.kind == "session" for r in records)
    session = [r for r in records if r.kind == "session"][0]
    assert session.record_count == 4
    assert session.content == "Test Session"


def test_devin_records_content_filter(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse("/file contents/")
    records = [r for r in source.records(ast) if evaluate(r, ast)]
    assert len(records) == 1
    assert records[0].kind == "tool_output"


def test_devin_records_timestamp_filter(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    ast = parse(":time/2026-08-21 22:31:42/")
    records = [r for r in source.records(ast) if evaluate(r, ast) and r.kind == "tool_call"]
    assert len(records) == 1
    assert records[0].record_id == "test-session-3"


@pytest.mark.parametrize(
    "session_id,expected",
    [
        ("test-session", "test-session"),
        ("grass-alibi", "grass-alibi"),
        ("shining-brass", "shining-brass"),
        ("olivine-streetcar", "olivine-streetca"),
        ("skillful-bellflower", "skillful-bellflo"),
        ("evergreen-sawfish", "evergreen-sawfis"),
    ],
)
def test_devin_short_hash(session_id: str, expected: str) -> None:
    assert DevinSource._short_hash(session_id) == expected
    assert 8 < len(expected) <= 16


def test_devin_short_hash_is_unique_across_fixture(devin_db: Path) -> None:
    source = DevinSource(paths=[devin_db])
    sessions = list(source.sessions())
    assert len({s.short_hash for s in sessions}) == len(sessions)
