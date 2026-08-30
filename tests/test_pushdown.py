import datetime

import pytest

from slq.eval import evaluate
from slq.pushdown import SQLBuilder, SQLColumn, QueryRequest
from slq.query import parse
from slq.schema import Record


def _builder() -> SQLBuilder:
    return SQLBuilder(
        {
            "tool": SQLColumn("'slq'"),
            "kind": SQLColumn(
                "CASE WHEN role = 'user' THEN 'user' WHEN role = 'assistant' THEN 'agent' ELSE 'other' END"
            ),
            "content": SQLColumn("COALESCE(body, '')"),
            "timestamp": SQLColumn(
                "strftime('%Y-%m-%d %H:%M:%S', COALESCE(ts, '1970-01-01 00:00:00'))"
            ),
        }
    )


def test_empty_ast_returns_one_equal_one():
    builder = _builder()
    where, params = builder.build(None)
    assert where == "1=1"
    assert params == []


def test_simple_regex():
    builder = _builder()
    ast = parse(":content/hello/")
    where, params = builder.build(ast)
    assert where == "(COALESCE(body, '') REGEXP ?)"
    assert params == ["hello"]


def test_and():
    builder = _builder()
    ast = parse(":content/hello/:kind/user/")
    where, params = builder.build(ast)
    assert "REGEXP" in where
    assert "AND" in where
    assert params == ["hello", "user"]


def test_or():
    builder = _builder()
    ast = parse(":content/hello/|:content/world/")
    where, params = builder.build(ast)
    assert "OR" in where
    assert params == ["hello", "world"]


def test_not():
    builder = _builder()
    ast = parse("! :content/hello/")
    where, params = builder.build(ast)
    assert where == "(NOT (COALESCE(body, '') REGEXP ?))"
    assert params == ["hello"]


def test_unmapped_field_emits_one_equal_one():
    builder = _builder()
    ast = parse(":model/gpt/")
    where, params = builder.build(ast)
    assert where == "1=1"
    assert params == []


def test_not_unmapped_is_safe():
    """NOT of an unmapped field must not filter everything."""
    builder = _builder()
    ast = parse("! :model/gpt/")
    where, params = builder.build(ast)
    assert where == "1=1"
    assert params == []


def test_or_with_unmapped_is_safe():
    """OR with an unmapped branch must not filter by the mapped branch alone."""
    builder = _builder()
    ast = parse(":content/hello/|:model/gpt/")
    where, params = builder.build(ast)
    assert where == "1=1"
    assert params == []


def test_and_with_unmapped_uses_mapped():
    """AND with an unmapped branch can still push the mapped branch."""
    builder = _builder()
    ast = parse(":content/hello/:model/gpt/")
    where, params = builder.build(ast)
    assert "COALESCE(body, '') REGEXP ?" in where
    assert "AND" not in where or ":model" not in where
    assert params == ["hello"]


def test_since_until_appended():
    builder = _builder()
    ast = parse(":content/hello/")
    since = datetime.datetime(2026, 8, 21, tzinfo=datetime.timezone.utc)
    until = datetime.datetime(2026, 8, 22, tzinfo=datetime.timezone.utc)
    where, params = builder.build(ast, since=since, until=until)
    assert "COALESCE(body, '') REGEXP ?" in where
    assert ">= ?" in where
    assert "<= ?" in where
    assert params[0] == "hello"
    assert params[1] == "2026-08-21 00:00:00"
    assert params[2] == "2026-08-22 00:00:00"


def test_query_request_defaults():
    req = QueryRequest()
    assert req.ast is None
    assert req.env is None
    assert req.since is None
    assert req.until is None
    assert req.limit is None
