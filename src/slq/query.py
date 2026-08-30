import dataclasses
import re
from typing import List, Optional

from .schema import UnknownFieldError, resolve_field, resolve_field_prefix


class ParseError(Exception):
    pass


class InvalidRegexError(ParseError):
    pass


@dataclasses.dataclass
class QueryAST:
    pass


@dataclasses.dataclass
class Regex(QueryAST):
    field: str
    pattern: "re.Pattern[str]"
    raw: str


@dataclasses.dataclass
class And(QueryAST):
    operands: List[QueryAST]


@dataclasses.dataclass
class Or(QueryAST):
    operands: List[QueryAST]


@dataclasses.dataclass
class Not(QueryAST):
    operand: QueryAST


_OPERATORS = frozenset("!&|(),:")


def _is_delim(c: str) -> bool:
    if not c:
        return False
    if c.isspace() or c.isalnum() or c == "_":
        return False
    if c in _OPERATORS:
        return False
    return True


def parse(expr: str) -> QueryAST:
    parser = _Parser(expr)
    ast = parser.parse_or()
    parser.skip_whitespace()
    if not parser.eof():
        raise ParseError(f"unexpected {parser.peek()!r} at position {parser.pos}")
    return ast


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.n = len(text)

    def eof(self) -> bool:
        return self.pos >= self.n

    def peek(self) -> str:
        if self.eof():
            return ""
        return self.text[self.pos]

    def next(self) -> str:
        c = self.peek()
        self.pos += 1
        return c

    def skip_whitespace(self) -> None:
        while self.pos < self.n and self.text[self.pos].isspace():
            self.pos += 1

    def peek_word(self) -> Optional[str]:
        start = self.pos
        while self.pos < self.n and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        word = self.text[start:self.pos]
        self.pos = start
        return word if word else None

    def consume_word(self, expected: Optional[str] = None) -> str:
        start = self.pos
        while self.pos < self.n and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        word = self.text[start:self.pos]
        if expected is not None and word != expected:
            raise ParseError(f"expected {expected!r} but found {word!r} at position {start}")
        return word

    def parse_or(self) -> QueryAST:
        left = self.parse_and()
        while True:
            self.skip_whitespace()
            if self.eof():
                break
            c = self.peek()
            if c == "|" or c == ",":
                self.next()
                right = self.parse_and()
                left = Or([left, right])
                continue
            word = self.peek_word()
            if word == "or":
                self.consume_word("or")
                right = self.parse_and()
                left = Or([left, right])
                continue
            break
        return left

    def parse_and(self) -> QueryAST:
        left = self.parse_not()
        while True:
            self.skip_whitespace()
            if self.eof():
                break
            c = self.peek()
            if c in ")|," or self.peek_word() == "or":
                break
            if c == "&":
                self.next()
                self.skip_whitespace()
                right = self.parse_not()
                left = And([left, right])
                continue
            word = self.peek_word()
            if word == "and":
                self.consume_word("and")
                self.skip_whitespace()
                right = self.parse_not()
                left = And([left, right])
                continue
            if self._is_not_expr_start():
                right = self.parse_not()
                left = And([left, right])
                continue
            break
        return left

    def _is_not_expr_start(self) -> bool:
        c = self.peek()
        if c == "!" or c == ":" or c == "(" or _is_delim(c):
            return True
        word = self.peek_word()
        if word == "not":
            return True
        return False

    def parse_not(self) -> QueryAST:
        self.skip_whitespace()
        if self.eof():
            raise ParseError("unexpected end of expression")
        c = self.peek()
        if c == "!":
            self.next()
            self.skip_whitespace()
            return Not(self.parse_primary())
        word = self.peek_word()
        if word == "not":
            self.consume_word("not")
            self.skip_whitespace()
            return Not(self.parse_primary())
        return self.parse_primary()

    def parse_primary(self) -> QueryAST:
        self.skip_whitespace()
        if self.eof():
            raise ParseError("unexpected end of expression")
        c = self.peek()
        if c == "(":
            self.next()
            ast = self.parse_or()
            self.skip_whitespace()
            if self.eof() or self.peek() != ")":
                raise ParseError("missing closing ')'")
            self.next()
            return ast
        if c == ":":
            return self._parse_fbr()
        if _is_delim(c):
            return self._parse_global()
        raise ParseError(
            f"unexpected {c!r} at position {self.pos}; expected a term, '(', ':', or a delimiter"
        )

    def _parse_fbr(self) -> Regex:
        self.next()  # consume ':'
        self.skip_whitespace()
        field: Optional[str] = None
        if self.peek().isalpha() or self.peek() == "_":
            field = self.consume_word()

        # A field name with no delimiter is a display-only term: it selects the
        # field for output without filtering. If a field name is followed by a
        # real delimiter, parse the regex and treat it as a filter term.
        if field and (self.eof() or not _is_delim(self.peek())):
            canonical = resolve_field_prefix(field)
            return Regex(field=canonical, pattern=_compile(""), raw="")

        if self.eof() or not _is_delim(self.peek()):
            raise ParseError(f"expected a delimiter after field at position {self.pos}")
        delim = self.next()
        start = self.pos
        while not self.eof() and self.peek() != delim:
            self.pos += 1
        if self.eof():
            raise ParseError(f"unterminated regex; missing closing {delim!r}")
        raw = self.text[start:self.pos]
        self.next()  # consume closing delimiter
        canonical = resolve_field_prefix(field) if field else "content"
        return Regex(field=canonical, pattern=_compile(raw), raw=raw)

    def _parse_global(self) -> Regex:
        delim = self.next()
        start = self.pos
        while not self.eof() and self.peek() != delim:
            self.pos += 1
        if self.eof():
            raise ParseError(f"unterminated regex; missing closing {delim!r}")
        raw = self.text[start:self.pos]
        self.next()  # consume closing delimiter
        return Regex(field="content", pattern=_compile(raw), raw=raw)


def extract_output_fields(ast: QueryAST) -> Optional[List[str]]:
    """Return the fields the query selects for output.

    Display-only terms (empty regex) define the projection explicitly. If none
    are present, the constrained fields become the projection. If the query has
    no field terms, returns ``None`` so the caller can use ``Record`` defaults.
    """
    display_fields: List[str] = []
    filter_fields: List[str] = []

    def visit(node: QueryAST) -> None:
        if isinstance(node, Regex):
            if node.raw == "":
                if node.field not in display_fields:
                    display_fields.append(node.field)
            else:
                if node.field not in filter_fields:
                    filter_fields.append(node.field)
        elif isinstance(node, (And, Or)):
            for op in node.operands:
                visit(op)
        elif isinstance(node, Not):
            visit(node.operand)

    visit(ast)
    if display_fields:
        return display_fields
    if filter_fields:
        return filter_fields
    return None


def _compile(raw: str) -> "re.Pattern[str]":
    try:
        return re.compile(raw)
    except re.error as exc:
        raise InvalidRegexError(f"invalid regex {raw!r}: {exc}") from exc
