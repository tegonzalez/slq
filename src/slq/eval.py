import re
from typing import Any, Optional

from .query import And, Not, Or, QueryAST, Regex
from .schema import Record, record_value


def evaluate(record: Record, ast: QueryAST, negated: bool = False) -> bool:
    if isinstance(ast, Regex):
        value = record_value(record, ast.field)
        match = ast.pattern.search(value)
        if match and not negated and ast.raw != "":
            offset = match.start()
            ast.hint = offset
            hints = record.meta.setdefault("hint", {})
            if ast.field not in hints or offset < hints[ast.field]:
                hints[ast.field] = offset
        return bool(match)
    if isinstance(ast, Not):
        return not evaluate(record, ast.operand, not negated)
    if isinstance(ast, And):
        for op in ast.operands:
            if not evaluate(record, op, negated):
                return False
        return True
    if isinstance(ast, Or):
        result = False
        for op in ast.operands:
            if evaluate(record, op, negated):
                result = True
        return result
    raise TypeError(f"unknown AST node {ast!r}")


def _field_matcher(ast: QueryAST, field: str) -> Optional["re.Pattern[str]"]:
    if isinstance(ast, Regex):
        return ast.pattern if ast.field == field else None
    if isinstance(ast, Not):
        return None
    if isinstance(ast, And):
        for op in ast.operands:
            m = _field_matcher(op, field)
            if m is not None:
                return m
        return None
    if isinstance(ast, Or):
        patterns = []
        for op in ast.operands:
            m = _field_matcher(op, field)
            if m is None:
                return None
            patterns.append(m)
        if not patterns:
            return None
        combined = "|".join(f"(?:{p.pattern})" for p in patterns)
        return re.compile(combined)
    return None


def allows_value(ast: QueryAST, field: str, value: Any) -> bool:
    if isinstance(ast, Regex):
        if ast.field != field:
            return True
        return bool(ast.pattern.search(str(value)))
    if isinstance(ast, Not):
        if isinstance(ast.operand, Regex) and ast.operand.field == field:
            return not bool(ast.operand.pattern.search(str(value)))
        return True
    if isinstance(ast, And):
        return all(allows_value(op, field, value) for op in ast.operands)
    if isinstance(ast, Or):
        return any(allows_value(op, field, value) for op in ast.operands)
    return True


def allows_kind(ast: QueryAST, kind: str) -> bool:
    return allows_value(ast, "kind", kind)


def required_kind(ast: QueryAST) -> Optional[str]:
    if isinstance(ast, Regex) and ast.field == "kind":
        return ast.raw
    if isinstance(ast, Not) or isinstance(ast, And) or isinstance(ast, Or):
        return None
    return None
