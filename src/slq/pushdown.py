import dataclasses
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from .query import And, Not, Or, QueryAST, Regex, _compile


@dataclasses.dataclass
class QueryRequest:
    """Bundle passed to a ``DataSource`` so it can decide how to traverse storage.

    The JSONL sources currently treat this as a convenience wrapper around
    ``ast`` and ``env``.  SQLite-backed sources can also use ``since``,
    ``until`` and ``limit`` for SQL pushdown.
    """

    ast: Optional[QueryAST] = None
    env: Optional[Dict[str, Any]] = None
    since: Optional[datetime.datetime] = None
    until: Optional[datetime.datetime] = None
    limit: Optional[int] = None


@dataclasses.dataclass
class SQLColumn:
    """Mapping for one canonical ``Record`` field to a SQL expression.

    ``expr`` must produce the same string that ``record_value(record, field)``
    would produce, so regex and range filters in SQL match what the Python
    ``Cursor`` would do.  For ``text``/``hash``/``path`` fields this is usually
    ``COALESCE(raw, '')``.  For ``number`` fields it is a ``CAST(... AS TEXT)``.
    For ``datetime`` fields it is
    ``strftime('%Y-%m-%d %H:%M:%S', datetime(raw_expr))``.
    """

    expr: str


class SQLBuilder:
    """Translate a ``QueryAST`` into a SQLite ``WHERE`` clause.

    Each source provides a map from canonical field name to a ``SQLColumn``.
    The builder walks ``Regex``/``And``/``Or``/``Not`` nodes and produces a
    parameterized ``WHERE`` fragment plus a list of parameters.

    If a field is not present in the source schema, the builder treats that
    sub-expression as "unknown" and emits ``1=1`` for it, so the source can
    return a safe superset and the ``Cursor`` can apply the real filter in
    Python.  This keeps partial pushdown correct even when the schema does not
    cover every canonical field.
    """

    def __init__(self, columns: Dict[str, SQLColumn]):
        self._columns = columns

    def build(
        self,
        ast: Optional[QueryAST],
        since: Optional[datetime.datetime] = None,
        until: Optional[datetime.datetime] = None,
    ) -> Tuple[str, List[Any]]:
        where, params = self._visit(ast)
        ts_col = self._columns.get("timestamp")
        if ts_col is not None:
            if since is not None:
                ts_sql = ts_col.expr
                where = f"({where}) AND ({ts_sql} >= ?)"
                params.append(self._format_dt(since))
            if until is not None:
                ts_sql = ts_col.expr
                where = f"({where}) AND ({ts_sql} <= ?)"
                params.append(self._format_dt(until))
        return where, params

    def _format_dt(self, dt: datetime.datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _visit(self, node: Optional[QueryAST]) -> Tuple[str, List[Any]]:
        if node is None:
            return ("1=1", [])
        if isinstance(node, Regex):
            return self._regex(node)
        if isinstance(node, And):
            return self._and(node)
        if isinstance(node, Or):
            return self._or(node)
        if isinstance(node, Not):
            return self._not(node)
        raise TypeError(f"unsupported AST node: {type(node).__name__}")

    def _regex(self, node: Regex) -> Tuple[str, List[Any]]:
        if node.raw == "":
            return ("1=1", [])
        column = self._columns.get(node.field)
        if column is None:
            return ("1=1", [])
        return (f"({column.expr} REGEXP ?)", [node.raw])

    def _and(self, node: And) -> Tuple[str, List[Any]]:
        known_clauses: List[str] = []
        known_params: List[Any] = []
        for op in node.operands:
            clause, params = self._visit(op)
            if clause != "1=1":
                known_clauses.append(clause)
                known_params.extend(params)
        if not known_clauses:
            return ("1=1", [])
        if len(known_clauses) == 1:
            return (known_clauses[0], known_params)
        return (f"({' AND '.join(known_clauses)})", known_params)

    def _or(self, node: Or) -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        for op in node.operands:
            clause, ps = self._visit(op)
            if clause == "1=1":
                return ("1=1", [])
            clauses.append(clause)
            params.extend(ps)
        if not clauses:
            return ("1=1", [])
        if len(clauses) == 1:
            return (clauses[0], params)
        return (f"({' OR '.join(clauses)})", params)

    def _not(self, node: Not) -> Tuple[str, List[Any]]:
        clause, params = self._visit(node.operand)
        if clause == "1=1":
            return ("1=1", [])
        return (f"(NOT {clause})", params)


def drop_field(ast: QueryAST, field: str) -> QueryAST:
    """Return a new AST with all filters on ``field`` replaced by display-only terms.

    This is useful when a source must not push a particular filter down to the
    storage layer -- for example, ``kind=session`` should not filter event rows
    because the session record is constructed separately.
    """
    if isinstance(ast, Regex):
        if ast.field == field:
            return Regex(field=field, pattern=_compile(""), raw="")
        return ast
    if isinstance(ast, And):
        return And([drop_field(op, field) for op in ast.operands])
    if isinstance(ast, Or):
        return Or([drop_field(op, field) for op in ast.operands])
    if isinstance(ast, Not):
        return Not(drop_field(ast.operand, field))
    return ast
