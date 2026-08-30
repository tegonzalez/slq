import pytest

from slq.eval import evaluate
from slq.query import And, Not, Or, ParseError, Regex, extract_output_fields, parse
from slq.schema import Record, UnknownFieldError


def test_parse_global():
    ast = parse("/count/")
    assert isinstance(ast, Regex)
    assert ast.field == "content"
    assert ast.raw == "count"


def test_parse_fbr_kind():
    ast = parse(":k/session/")
    assert isinstance(ast, Regex)
    assert ast.field == "kind"
    assert ast.raw == "session"


def test_parse_fbr_session():
    ast = parse(":se/5df37bef/")
    assert ast.field == "session_id"
    assert ast.raw == "5df37bef"


def test_parse_and():
    ast = parse(":k/user/ & /count/")
    assert isinstance(ast, And)
    assert len(ast.operands) == 2


def test_parse_and_adjacency():
    ast = parse(":k/user/ /count/")
    assert isinstance(ast, And)


def test_parse_and_keyword():
    ast = parse(":k/user/ and /count/")
    assert isinstance(ast, And)


def test_parse_or():
    ast = parse(":k/user/ | :k/agent/")
    assert isinstance(ast, Or)


def test_parse_or_keyword():
    ast = parse(":k/user/ or :k/agent/")
    assert isinstance(ast, Or)


def test_parse_or_comma():
    ast = parse(":k/user/, :k/agent/")
    assert isinstance(ast, Or)


def test_parse_not_bang():
    ast = parse("! :k/session/")
    assert isinstance(ast, Not)


def test_parse_not_keyword():
    ast = parse("not :k/session/")
    assert isinstance(ast, Not)


def test_parse_parens():
    ast = parse("(:k/user/ or :k/agent/) /count/")
    assert isinstance(ast, And)


def test_parse_precedence():
    ast = parse("! :k/session/ | /count/")
    assert isinstance(ast, Or)
    assert isinstance(ast.operands[0], Not)


def test_parse_invalid_regex():
    with pytest.raises(ParseError):
        parse("/[/")


def test_parse_unknown_field():
    with pytest.raises(UnknownFieldError):
        parse(":xyz/foo/")


def test_parse_prefix_field():
    ast = parse(":time/2026/")
    assert ast.field == "timestamp"
    assert ast.raw == "2026"


def test_parse_prefix_unambiguous():
    ast = parse(":to/codex/")
    assert ast.field == "tool"


def test_parse_prefix_ambiguous():
    with pytest.raises(UnknownFieldError) as exc_info:
        parse(":re/2026/")
    assert "ambiguous" in str(exc_info.value)
    assert "record_count" in str(exc_info.value)
    assert "record_id" in str(exc_info.value)
    assert "rec_type" in str(exc_info.value)


def test_parse_empty_regex():
    with pytest.raises(ParseError):
        parse("//")


def test_parse_display_only_field():
    ast = parse(":kind:role")
    assert isinstance(ast, And)
    assert len(ast.operands) == 2
    assert ast.operands[0].field == "kind"
    assert ast.operands[0].raw == ""
    assert ast.operands[1].field == "role"
    assert ast.operands[1].raw == ""


def test_parse_display_only_with_filter():
    ast = parse(":time/2026/:kind:role")
    fields = extract_output_fields(ast)
    # Display-only terms take over the projection; the timestamp filter still runs.
    assert fields == ["kind", "role"]
    assert evaluate(Record(timestamp="2026-08-29", kind="user", role="assistant"), ast)


def test_extract_output_fields_filter_only():
    ast = parse(":time/2026/")
    assert extract_output_fields(ast) == ["timestamp"]


def test_extract_output_fields_display_terms():
    ast = parse(":time/2026/:kind:role")
    assert extract_output_fields(ast) == ["kind", "role"]


def test_extract_output_fields_global():
    ast = parse("/count/")
    assert extract_output_fields(ast) == ["content"]
