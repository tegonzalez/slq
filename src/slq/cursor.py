import datetime
from typing import Iterable, Iterator, List, Optional

from .eval import evaluate
from .query import QueryAST
from .schema import Record


class Cursor:
    def __init__(
        self,
        records: Iterable[Record],
        ast: Optional[QueryAST] = None,
        limit: Optional[int] = None,
        since: Optional[datetime.datetime] = None,
        until: Optional[datetime.datetime] = None,
        fields: Optional[List[str]] = None,
    ):
        self._records = iter(records)
        self.ast = ast
        self.limit = limit
        self.since = since
        self.until = until
        self.fields = fields

    def __iter__(self) -> Iterator[Record]:
        count = 0
        for record in self._records:
            if self.since is not None and record.timestamp is not None and record.timestamp < self.since:
                continue
            if self.until is not None and record.timestamp is not None and record.timestamp > self.until:
                continue
            if self.ast is not None and not evaluate(record, self.ast):
                continue
            if self.limit is not None and count >= self.limit:
                break
            yield record
            count += 1
