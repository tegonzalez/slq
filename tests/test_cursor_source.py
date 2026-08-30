import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import slq.cli as cli
from slq.eval import evaluate
from slq.query import parse
from slq.schema import record_value
from slq.sources.cursor import CursorSource
from slq.sources.registry import DEFAULT_SOURCES


SESSION_ID = "11111111-2222-3333-4444-555555555555"
SESSION_ID_2 = "22222222-3333-4444-5555-666666666666"
USER_BUBBLE_ID = "ffffffff-1111-2222-3333-444444444444"
AGENT_BUBBLE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


FIXTURES = Path(__file__).parent / "fixtures"


def test_default_sources_include_cursor() -> None:
    names = [source.name for source in DEFAULT_SOURCES]
    assert names.count("cursor") == 1
    assert names == ["codex", "claude", "cursor", "devin"]


def _make_bubble(bubble_id: str, kind: int, text: str, created_at) -> dict:
    return {
        "bubbleId": bubble_id,
        "type": kind,
        "text": text,
        "createdAt": created_at,
    }


def _make_header(session_id: str, created_at: int, name: str) -> dict:
    return {
        "composerId": session_id,
        "createdAt": created_at,
        "lastUpdatedAt": created_at + 2000,
        "name": name,
        "unifiedMode": "agent",
        "workspaceIdentifier": {"uri": {"fsPath": "/workspace/project"}},
    }


@pytest.fixture
def cursor_db(tmp_path: Path) -> Path:
    path = tmp_path / "state.vscdb"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE composerHeaders ("
        "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
        "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER, "
        "recency INTEGER, checkpointAt INTEGER, value TEXT, "
        "subagentTypeName TEXT)"
    )
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE, value BLOB)")

    header = _make_header(SESSION_ID, 1788062400000, "Cursor fixture conversation")
    conn.execute(
        "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, 0, 0, 1, 0, ?, '')",
        (SESSION_ID, "workspace-1", header["createdAt"], header["lastUpdatedAt"], json.dumps(header)),
    )

    bubbles = (
        (f"bubbleId:{SESSION_ID}:{USER_BUBBLE_ID}", _make_bubble(USER_BUBBLE_ID, 1, "cursor fixture request", "2026-08-30T04:00:00.000Z")),
        (f"bubbleId:{SESSION_ID}:{AGENT_BUBBLE_ID}", _make_bubble(AGENT_BUBBLE_ID, 2, "cursor fixture response", 1788062402000)),
    )
    conn.executemany(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        [(key, json.dumps(value)) for key, value in bubbles],
    )
    conn.commit()
    conn.close()
    return path


def test_cursor_sessions_map_header_metadata(cursor_db: Path) -> None:
    source = CursorSource([cursor_db])
    records = list(source.sessions())
    assert len(records) == 1
    assert records[0].tool == "cursor"
    assert records[0].session_id == SESSION_ID
    assert records[0].cwd == "/workspace/project"
    assert records[0].record_count == 2
    assert records[0].content == "Cursor fixture conversation"


def test_cursor_records_map_user_and_agent_bubbles(cursor_db: Path) -> None:
    source = CursorSource([cursor_db])
    ast = parse(":tool/cursor/")
    records = [record for record in source.records(ast) if evaluate(record, ast)]
    messages = [record for record in records if record.kind != "session"]
    assert [record.kind for record in messages] == ["user", "agent"]
    assert [record.role for record in messages] == ["user", "assistant"]
    assert [record.content for record in messages] == [
        "cursor fixture request",
        "cursor fixture response",
    ]
    assert all(record.session_id == SESSION_ID for record in messages)


def test_cursor_records_push_down_kind_and_content(cursor_db: Path) -> None:
    source = CursorSource([cursor_db])
    ast = parse(":kind/user/ /request/")
    records = list(source.records(ast))
    assert len(records) == 1
    assert records[0].record_id == USER_BUBBLE_ID


def test_cursor_events_use_one_joined_statement(cursor_db: Path) -> None:
    statements: list[str] = []

    class TracedCursorSource(CursorSource):
        async def _init_db(self, db):
            await super()._init_db(db)
            await db.set_trace_callback(statements.append)
            return db

    source = TracedCursorSource([cursor_db])
    records = list(source.records(parse(":kind/user/")))
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]

    assert [record.record_id for record in records] == [USER_BUBBLE_ID]
    assert len(selects) == 1
    assert "LEFT JOIN composerHeaders" in selects[0]


def test_cursor_records_both_createdat_shapes_and_since(cursor_db: Path) -> None:
    # One bubble uses an ISO createdAt, the other epoch-milliseconds.
    source = CursorSource([cursor_db])
    ast = parse(":tool/cursor/")

    def _check(since_text: str, expected: list) -> None:
        import datetime as dt
        since = dt.datetime.fromisoformat(since_text.replace("Z", "+00:00"))
        records = [r for r in source.records(ast, {"since": since}) if r.kind != "session"]
        assert [r.content for r in records] == expected

    _check("2026-08-30T04:00:00Z", ["cursor fixture request", "cursor fixture response"])
    _check("2026-08-30T04:00:01Z", ["cursor fixture response"])
    _check("2026-08-30T04:00:03Z", [])


def test_cursor_normalizes_offset_timestamp_for_sql_and_python(cursor_db: Path) -> None:
    offset_bubble_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    bubble = _make_bubble(
        offset_bubble_id,
        1,
        "offset timestamp",
        "2026-08-30T04:00:00-07:00",
    )
    conn = sqlite3.connect(cursor_db)
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        (f"bubbleId:{SESSION_ID}:{offset_bubble_id}", json.dumps(bubble)),
    )
    conn.commit()
    conn.close()

    source = CursorSource([cursor_db])
    records = list(source.records(parse(":kind/user/ :timestamp/^2026-08-30 11:00:00$/")))

    assert [record.record_id for record in records] == [offset_bubble_id]
    assert record_value(records[0], "timestamp") == "2026-08-30 11:00:00"


def test_cursor_event_stream_propagates_database_errors(tmp_path: Path) -> None:
    # Unit seam: this proves iterator delivery, not CLI diagnostic wording or
    # whether a schema-invalid state.vscdb should be admitted.
    invalid_store = tmp_path / "state.vscdb"
    sqlite3.connect(invalid_store).close()
    child_code = """
from pathlib import Path
from slq.query import parse
from slq.sources.cursor import CursorSource
import sys

list(CursorSource([Path(sys.argv[1])]).records(parse(":kind/user/")))
"""

    process = subprocess.run(
        [sys.executable, "-c", child_code, str(invalid_store)],
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert process.returncode != 0
    assert "OperationalError" in process.stderr
    assert "Exception in thread" not in process.stderr


def _make_multi_composer_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE composerHeaders ("
        "composerId TEXT PRIMARY KEY, workspaceId TEXT, createdAt INTEGER, "
        "lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER, "
        "recency INTEGER, checkpointAt INTEGER, value TEXT, "
        "subagentTypeName TEXT)"
    )
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE, value BLOB)")
    for i, sid in enumerate([SESSION_ID, SESSION_ID_2]):
        header = _make_header(sid, 1788062400000 + i * 10000, f"Session {i}")
        conn.execute(
            "INSERT INTO composerHeaders VALUES (?, ?, ?, ?, 0, 0, 1, 0, ?, '')",
            (sid, f"workspace-{i}", header["createdAt"], header["lastUpdatedAt"], json.dumps(header)),
        )
        bubble = _make_bubble(f"bubble-{i}", 1, f"text {i}", 1788062400000 + i * 10000 + 1000)
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            (f"bubbleId:{sid}:{bubble['bubbleId']}", json.dumps(bubble)),
        )
    conn.commit()
    conn.close()


def test_cursor_multi_root_queries_all_stores(tmp_path: Path) -> None:
    db_a = tmp_path / "a" / "state.vscdb"
    db_a.parent.mkdir()
    _make_multi_composer_db(db_a)
    db_b = tmp_path / "b" / "state.vscdb"
    db_b.parent.mkdir()
    _make_multi_composer_db(db_b)

    source = CursorSource([db_a.parent, db_b.parent])
    ast = parse(":kind/user/")
    records = [r for r in source.records(ast, env={}) if r.kind == "user"]
    assert len(records) == 4
    assert {r.session_id for r in records} == {SESSION_ID, SESSION_ID_2}


def test_cursor_unavailable_when_store_missing() -> None:
    source = CursorSource([FIXTURES / "missing" / "state.vscdb"])
    assert source.available() is False
    assert list(source.list()) == []


def test_cursor_does_not_admit_directory_without_store() -> None:
    source = CursorSource([FIXTURES / "codex" / "sessions"])
    assert source.default_paths == [FIXTURES / "codex" / "sessions"]
    assert source.admitted_paths() == []
    assert source.available() is False


def test_cursor_admits_directory_with_state_vscdb(tmp_path: Path) -> None:
    store = tmp_path / "Cursor"
    store.mkdir()
    db = store / "state.vscdb"
    _make_multi_composer_db(db)
    source = CursorSource([store])
    assert source.available() is True
    assert source.admitted_paths() == [db]


def test_cursor_cli_lists_and_queries_source(cursor_db: Path) -> None:
    original_sources = cli.SOURCES
    cli.SOURCES = [CursorSource([cursor_db])]
    try:
        listed = io.StringIO()
        queried = io.StringIO()
        list_rc = cli.main(["ls", "cursor"], out=listed)
        query_rc = cli.main([":tool/cursor/", "/request/"], out=queried)
    finally:
        cli.SOURCES = original_sources

    assert list_rc == 0
    assert "11111111" in listed.getvalue()
    assert query_rc == 0
    assert "cursor fixture request" in queried.getvalue()
