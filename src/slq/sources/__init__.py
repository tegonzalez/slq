import datetime
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..eval import allows_value
from ..query import QueryAST
from ..schema import Record, SourceRecord


class DataSource(ABC):
    name: str = ""

    def __init__(self, paths: Optional[List[Path]] = None):
        self._paths = paths

    @property
    @abstractmethod
    def default_paths(self) -> List[Path]:
        ...

    def can_answer(self, ast: QueryAST) -> bool:
        return allows_value(ast, "tool", self.name)

    @abstractmethod
    def records(self, ast: QueryAST, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        ...

    def list(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        """List source-level rows (tool, default paths) as ``Record`` DTOs."""
        for path in self.default_paths:
            yield SourceRecord(
                tool=self.name,
                kind="source",
                record_id=self.name,
                path=str(path),
                content="",
            )

    def sessions(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        """List session-level rows as ``Record`` DTOs.

        The default implementation yields nothing; sources with session files
        override it.
        """
        return
        yield


UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _extract_uuid(text: str) -> Optional[str]:
    m = UUID_RE.search(text)
    return m.group(0) if m else None


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_extract_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "thinking"):
            if key in value:
                return _extract_text(value[key])
        return "\n".join(_extract_text(v) for v in value.values())
    return str(value)


def _parse_timestamp(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value
    if isinstance(value, (int, float)):
        v = value
        if v > 1e12:
            v = v / 1000.0
        return datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _model_from(obj: Any) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    for key in ("model", "model_provider"):
        if key in obj and obj[key]:
            return str(obj[key])
    meta = obj.get("metadata")
    if isinstance(meta, dict):
        for key in ("model", "model_provider"):
            if key in meta and meta[key]:
                return str(meta[key])
    return None


def _session_sort_key(record: Record) -> Tuple[bool, datetime.datetime]:
    """Sort with un-dated records first, then by timestamp ascending."""
    return (record.timestamp is not None, record.timestamp or datetime.datetime.min)


def _file_mtime(file: Path) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromtimestamp(file.stat().st_mtime, tz=datetime.timezone.utc)
    except OSError:
        return None



