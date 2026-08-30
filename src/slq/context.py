from typing import Any, Iterable, Iterator, List, Set

from .eval import evaluate
from .schema import Record


def with_context(records: Iterable[Record], ast: Any, n: int) -> Iterator[Record]:
    """Yield records with context around each match.

    For each matching record, also emit the ``n`` records before and after it
    that have not already been emitted, marking matches with ``context=match``
    and surrounding records with ``context=context``.
    """
    base = 0
    buf: List[Record] = []
    matches: List[int] = []
    emitted: Set[int] = set()
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
