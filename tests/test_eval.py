import datetime

from slq.eval import evaluate
from slq.query import parse
from slq.schema import Record


def make_record(**kwargs) -> Record:
    return Record(**kwargs)


def test_eval_regex_content():
    r = make_record(content="the count is 5")
    assert evaluate(r, parse("/count/"))


def test_eval_regex_kind():
    r = make_record(kind="user")
    assert evaluate(r, parse(":k/user/"))
    assert not evaluate(r, parse(":k/agent/"))


def test_eval_and():
    r = make_record(kind="user", content="count")
    assert evaluate(r, parse(":k/user/ /count/"))


def test_eval_or():
    r = make_record(kind="agent")
    assert evaluate(r, parse(":k/user/ or :k/agent/"))


def test_eval_not():
    r = make_record(kind="user")
    assert evaluate(r, parse("! :k/session/"))
    assert not evaluate(r, parse("! :k/user/"))


def test_eval_timestamp():
    r = make_record(timestamp="2026-08-29T12:00:00Z")
    assert evaluate(r, parse(":time/2026-08-29/"))


def test_eval_session_only_fields():
    r = make_record(kind="session", record_count=3)
    assert evaluate(r, parse(":record_count/3/"))


def test_eval_sets_hint():
    r = make_record(content="the count is 5")
    ast = parse("/count/")
    assert evaluate(r, ast)
    assert ast.hint == 4
    assert r.meta["hint"]["content"] == 4


def test_eval_hint_not_set_when_negated():
    r = make_record(content="the total is 5")
    ast = parse("! /count/")
    assert evaluate(r, ast)
    assert "hint" not in r.meta


def test_eval_hint_earliest_for_and():
    r = make_record(content="one two three two one")
    ast = parse("/one/ /two/")
    assert evaluate(r, ast)
    # The earliest match across both regexes is "one" at offset 0.
    assert r.meta["hint"]["content"] == 0


def test_eval_display_only_does_not_overwrite_hint():
    r = make_record(kind="user", content="the lint is here")
    ast = parse(":k/user/:content/lint/:tool:content")
    assert evaluate(r, ast)
    # The display-only :content term must not reset the content hint to 0.
    assert r.meta["hint"]["content"] == 4
