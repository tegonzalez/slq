import datetime

import pytest

from slq.schema import (
    Record,
    SourceRecord,
    SessionRecord,
    UnknownFieldError,
    record_value,
    resolve_field,
    resolve_field_prefix,
)


def test_record_defaults():
    r = Record(tool="codex")
    assert r.tool == "codex"
    assert r.content == ""


def test_timestamp_parsing():
    r = Record(timestamp="2026-08-29T12:00:00Z")
    assert r.timestamp is not None
    assert r.timestamp.tzinfo is not None


def test_resolve_field_exact():
    assert resolve_field("kind") == "kind"
    assert resolve_field("session_id") == "session_id"
    assert resolve_field("timestamp") == "timestamp"


def test_resolve_field_prefix():
    assert resolve_field_prefix("k") == "kind"
    assert resolve_field_prefix("ki") == "kind"
    assert resolve_field_prefix("se") == "session_id"
    assert resolve_field_prefix("time") == "timestamp"
    assert resolve_field_prefix("to") == "tool"


def test_resolve_field_unknown():
    with pytest.raises(UnknownFieldError) as exc:
        resolve_field("xyz")
    assert "unknown field" in str(exc.value).lower()
    assert "kind" in str(exc.value)


def test_record_count_and_duration_as_strings():
    r = Record(record_count="10", duration="5.5")
    assert r.record_count == 10
    assert r.duration == 5.5


def test_short_hash_computed():
    r = Record(session_id="aaaaaaaa-1111-2222-3333-444444444444")
    assert r.short_hash == "aaaaaaaa"


def test_record_value_renderers():
    r = Record(
        session_id="aaaaaaaa-1111-2222-3333-444444444444",
        timestamp=datetime.datetime(2026, 8, 29, 12, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert record_value(r, "short_hash") == "aaaaaaaa"
    assert record_value(r, "timestamp") == "2026-08-29 12:00:00"
    assert record_value(r, "session_id") == "aaaaaaaa-1111-2222-3333-444444444444"


def test_record_field_reflection():
    names = {f.name for f in Record.record_fields()}
    assert "short_hash" in names
    assert "timestamp" in names


def test_source_record_default_fields():
    r = SourceRecord(tool="codex", path="/home/dev/.codex")
    assert r.default_fields == ("tool", "path")


def test_session_record_default_fields():
    r = SessionRecord(session_id="aaaaaaaa-1111-2222-3333-444444444444")
    assert r.default_fields == ("timestamp", "short_hash")
    assert record_value(r, "short_hash") == "aaaaaaaa"
