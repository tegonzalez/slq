from pathlib import Path

import pytest

from slq.resources import FileResource, clear_resources, get_resource


BASE = Path(__file__).with_name("fixtures")


def test_file_resource_count_no_offsets():
    path = BASE / "codex" / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    res = FileResource(path)
    assert res.count() == 3
    assert not res._offsets


def test_file_resource_first_object_streams():
    path = BASE / "codex" / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    res = FileResource(path)
    idx, obj = res.first_object(lambda o: isinstance(o, dict) and o.get("type") != "session_meta")
    assert idx == 1
    assert obj["type"] == "response_item"
    assert not res._offsets


def test_file_resource_object_builds_offsets():
    path = BASE / "codex" / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    res = FileResource(path)
    obj = res.object(0)
    assert obj["type"] == "session_meta"
    assert len(res._offsets) == 3
    assert len(res._objects) == 3


def test_file_resource_records_caches():
    path = BASE / "codex" / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    res = FileResource(path)

    def mapper(idx, obj):
        return obj["type"] if isinstance(obj, dict) else None

    records = res.records(mapper)
    assert records == ["session_meta", "response_item", "response_item"]
    assert res._records is records
    assert res.records(mapper) is records


def test_file_resource_iter_records_does_not_build_offsets():
    path = BASE / "codex" / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    res = FileResource(path)

    def mapper(idx, obj):
        return obj["type"] if isinstance(obj, dict) else None

    records = list(res.iter_records(mapper))
    assert records == ["session_meta", "response_item", "response_item"]
    assert not res._offsets


def test_resource_manager_shares_resources():
    clear_resources()
    path = BASE / "codex" / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    r1 = get_resource(path)
    r2 = get_resource(path)
    assert r1 is r2
    clear_resources()
