import argparse
import datetime
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, TextIO

from .cursor import Cursor
from .eval import evaluate
from .output import render_records
from .query import ParseError, extract_output_fields, parse
from .schema import (
    CANONICAL_FIELDS,
    FieldRecord,
    Record,
    UnknownFieldError,
    resolve_field,
)
from .sources.claude import ClaudeSource
from .sources.codex import CodexSource
from .sources.devin import DevinSource
from .stats import stats
from .workqueue import get_workqueue


SOURCES = [CodexSource(), ClaudeSource(), DevinSource()]


def _init_workqueue() -> None:
    """Compute platform thread count at process init and create the global queue."""
    get_workqueue()


def main(argv: Optional[List[str]] = None, out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    _init_workqueue()
    argv = list(argv or sys.argv[1:])
    argv = _preprocess_argv(argv)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-f", "--format", choices=("plain", "json", "text"), default="plain"
    )
    common.add_argument("-F", "--fields", help="comma-separated display fields")
    common.add_argument(
        "-w",
        "--width",
        dest="precompute_widths",
        action="store_true",
        default=None,
        help="pre-calculate column widths and align output (default for ls)",
    )
    common.add_argument(
        "-s",
        "--stream",
        dest="precompute_widths",
        action="store_false",
        default=None,
        help="stream output without pre-calculating column widths (default for query)",
    )

    parser = argparse.ArgumentParser(prog="slq", parents=[common])
    subparsers = parser.add_subparsers(dest="command", required=True)

    query = subparsers.add_parser(
        "query", parents=[common], help="run an FBR query"
    )
    query.add_argument("expression", nargs="*", help="FBR expression (joined with spaces)")
    query.add_argument("-C", "--context", type=int, default=0, help="lines of context around matches")
    query.add_argument("--stats", action="store_true", help="emit stats record")
    query.add_argument("--since", help="filter records at or after this timestamp")
    query.add_argument("--until", help="filter records at or before this timestamp")
    query.add_argument("-n", "--limit", type=int, help="stop after N records")

    ls = subparsers.add_parser(
        "ls", parents=[common], help="list sources or source sessions"
    )
    ls.add_argument("source", nargs="?", help="source name (codex, claude, ...)")

    args = parser.parse_args(argv)
    if args.precompute_widths is None:
        args.precompute_widths = args.command == "ls"

    try:
        if args.command == "query":
            return _run_query(args, out, err)
        if args.command == "ls":
            return _run_ls(args, out, err)
    except KeyboardInterrupt:
        get_workqueue().shutdown(wait=False)
        err.write("\nslq: interrupted\n")
        return 130
    except BrokenPipeError:
        get_workqueue().shutdown(wait=False)
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return code
    return 0


def _preprocess_argv(argv: List[str]) -> List[str]:
    """Make FBR expressions the default ``query`` subcommand; bare ``slq`` prints usage.

    Global options may appear before the subcommand; they are moved after the
    inferred subcommand so ``argparse`` subparsers can consume them.
    """
    if not argv:
        return ["--help"]

    # Options that take a value (as a separate token or with ``=``).
    one_value = {
        "-f", "--format", "-F", "--fields",
        "-C", "--context", "-n", "--limit",
        "--since", "--until",
    }
    # Options that do not take a value.
    no_value = {"-w", "--width", "-s", "--stream", "--stats", "-h", "--help"}

    leading: List[str] = []
    i = 0
    n = len(argv)
    while i < n:
        a = argv[i]
        # Top-level help should show the main help, not the ls subcommand help.
        if a in ("-h", "--help"):
            return argv
        if a in no_value:
            leading.append(a)
            i += 1
            continue
        if a in one_value:
            leading.append(a)
            i += 1
            if i < n:
                leading.append(argv[i])
                i += 1
            continue
        # Long option with inline value, e.g. --format=json or --since=2026-08-29.
        if a.startswith("--") and "=" in a:
            key = a.split("=", 1)[0]
            if key in one_value:
                leading.append(a)
                i += 1
                continue
        # Short option with inline value, e.g. -fjson, -C3, -n5.
        if a.startswith("-") and not a.startswith("--") and len(a) > 2:
            short = a[:2]
            if short in one_value:
                leading.append(a)
                i += 1
                continue
        break

    if i >= n:
        return ["ls"] + leading

    first = argv[i]
    rest = argv[i + 1 :]
    if first in ("query", "ls"):
        return [first] + leading + rest
    if first.startswith(":") or first.startswith("/"):
        return ["query"] + leading + [first] + rest
    return ["ls"] + leading + [first] + rest


def _run_query(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    if not args.expression:
        err.write("slq: missing FBR expression\n")
        return 2

    expr = " ".join(args.expression)
    try:
        ast = parse(expr)
    except (ParseError, UnknownFieldError) as exc:
        err.write(f"slq: parse error: {exc}\n")
        return 2

    if args.fields:
        fields = _parse_fields(args.fields)
    else:
        fields = extract_output_fields(ast)

    # Stats records carry their summary in `content`; the query field list would
    # hide it. Use the record's default fields unless the user supplied -F.
    if args.stats and not args.fields:
        fields = None

    since = _parse_time(args.since)
    until = _parse_time(args.until)

    records = _collect_records(ast, env={"since": since, "until": until})
    if args.context > 0:
        records = _with_context(records, ast, args.context)
        cursor = Cursor(records, since=since, until=until, limit=args.limit, fields=fields)
    else:
        cursor = Cursor(records, ast=ast, since=since, until=until, limit=args.limit, fields=fields)

    if args.stats:
        records_out = stats(cursor)
    else:
        records_out = iter(cursor)

    render_records(records_out, args.format, fields=fields, out=out, precompute_widths=args.precompute_widths)
    return 0


def _run_ls(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    if args.source == "fields":
        _render_field_records(args, out)
        return 0

    if args.source:
        source = _find_source(args.source)
        if source is None:
            err.write(f"slq: unknown source: {args.source}\n")
            return 2
        records = source.sessions()
        fields = _parse_fields(args.fields) if args.fields else None
        render_records(records, args.format, fields=fields, out=out, precompute_widths=args.precompute_widths)
        return 0

    # Bare `ls` lists data sources followed by the record fieldspec.
    _render_source_records(args, out)
    if args.format in ("plain", "text"):
        out.write("\n")
    _render_field_records(args, out)
    return 0


def _render_source_records(args: argparse.Namespace, out: TextIO) -> None:
    fields = _parse_fields(args.fields) if args.fields else None
    records = _list_all_sources()
    render_records(records, args.format, fields=fields, out=out, precompute_widths=args.precompute_widths)


def _render_field_records(args: argparse.Namespace, out: TextIO) -> None:
    # Field records use their own default fields; the `-F` projection is not
    # applicable here because the whole purpose is to show the field list.
    render_records(_list_fields(), args.format, out=out, precompute_widths=args.precompute_widths)


def _list_fields() -> Iterator[Record]:
    for name in sorted(CANONICAL_FIELDS):
        yield FieldRecord(
            field_name=name,
            field_type=Record.field_format(name),
        )


def _find_source(name: str) -> Optional[Any]:
    for source in SOURCES:
        if source.name == name:
            return source
    return None


def _list_all_sources() -> Iterator[Record]:
    for source in SOURCES:
        yield from source.list()


def _collect_records(ast: Any, env: Optional[Dict[str, Any]] = None) -> Iterable[Record]:
    def gen():
        for source in SOURCES:
            if not source.can_answer(ast):
                continue
            for record in source.records(ast, env):
                yield record
    return gen()


def _with_context(records: Iterable[Record], ast: Any, n: int) -> Iterator[Record]:
    base = 0
    buf: List[Record] = []
    matches: List[int] = []
    emitted: set = set()
    for idx, record in enumerate(records):
        record.meta["_match"] = bool(evaluate(record, ast))
        buf.append(record)
        if record.meta["_match"]:
            matches.append(idx)
        while matches and (idx - matches[0]) >= n:
            m = matches.pop(0)
            for j in range(m - n, m + n + 1):
                if j in emitted:
                    continue
                bj = j - base
                if 0 <= bj < len(buf):
                    emitted.add(j)
                    r = buf[bj]
                    r.meta["context"] = "match" if j == m else "context"
                    yield r
            trim_to = (matches[0] - n) if matches else (m + n + 1)
            trim_to = max(trim_to - base, 0)
            if trim_to > 0:
                del buf[:trim_to]
                base += trim_to
        if not matches:
            keep = len(buf) - n
            if keep > 0:
                del buf[:keep]
                base += keep
    for m in matches:
        for j in range(m - n, m + n + 1):
            if j in emitted:
                continue
            bj = j - base
            if 0 <= bj < len(buf):
                emitted.add(j)
                r = buf[bj]
                r.meta["context"] = "match" if j == m else "context"
                yield r


def _parse_fields(text: Optional[str]) -> Optional[List[str]]:
    if not text:
        return None
    fields = [f.strip() for f in text.split(",") if f.strip()]
    return [resolve_field(f) for f in fields]


def _parse_time(text: Optional[str]) -> Optional[datetime.datetime]:
    if not text:
        return None
    try:
        value = text.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"invalid timestamp: {text!r}")


if __name__ == "__main__":
    sys.exit(main())
