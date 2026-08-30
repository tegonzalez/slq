import datetime
from collections import Counter
from typing import Any, Dict, Iterable, Iterator, Optional

from .schema import Record


def stats(records: Iterable[Record]) -> Iterator[Record]:
    total = 0
    by_tool: Dict[str, int] = Counter()
    by_kind: Dict[str, int] = Counter()
    by_day: Dict[str, int] = Counter()
    for record in records:
        total += 1
        by_tool[record.tool or "unknown"] += 1
        by_kind[record.kind or "unknown"] += 1
        if record.timestamp:
            day = record.timestamp.date().isoformat()
            by_day[day] += 1
    meta: Dict[str, Any] = {
        "total": total,
        "by_tool": dict(by_tool),
        "by_kind": dict(by_kind),
        "by_day": dict(by_day),
    }
    summary = (
        f"total={total} "
        f"by_tool={dict(by_tool)} "
        f"by_kind={dict(by_kind)} "
        f"by_day={dict(by_day)}"
    )
    yield Record(
        tool="slq",
        session_id="",
        record_id="",
        kind="stats",
        content=summary,
        meta=meta,
    )
