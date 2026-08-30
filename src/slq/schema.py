import dataclasses
import datetime
import json
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple


class QueryError(Exception):
    pass


class UnknownFieldError(QueryError):
    pass


def record_field(*, format: str, computed: bool = False, **kwargs: Any) -> dataclasses.Field:
    """Declare a record field with a named renderer and optional computed flag.

    This is the field decorator used by ``Record`` subclasses to identify
    stored vs. computed fields and to dispatch to a single renderer per type.
    """
    metadata = {"format": format, "computed": computed}
    if "metadata" in kwargs:
        metadata.update(kwargs.pop("metadata"))
    return dataclasses.field(metadata=metadata, **kwargs)


@dataclasses.dataclass
class Record:
    """Base dataclass for every record emitted by ``slq``.

    Subclasses set ``default_fields`` to provide a polymorphic field set for
    rendering. ``record_fields()`` reflects on the dataclass fields.
    """

    tool: Optional[str] = record_field(format="text", default=None)
    session_id: Optional[str] = record_field(format="hash", default=None)
    record_id: Optional[str] = record_field(format="hash", default=None)
    parent_id: Optional[str] = record_field(format="hash", default=None)
    short_hash: Optional[str] = record_field(format="short-hash", computed=True, default=None)
    timestamp: Optional[datetime.datetime] = record_field(format="datetime", default=None)
    end_timestamp: Optional[datetime.datetime] = record_field(format="datetime", default=None)
    kind: Optional[str] = record_field(format="text", default=None)
    role: Optional[str] = record_field(format="text", default=None)
    rec_type: Optional[str] = record_field(format="text", default=None)
    subtype: Optional[str] = record_field(format="text", default=None)
    content: Optional[str] = record_field(format="text", default=None)
    path: Optional[str] = record_field(format="path", default=None)
    cwd: Optional[str] = record_field(format="path", default=None)
    project: Optional[str] = record_field(format="text", default=None)
    model: Optional[str] = record_field(format="text", default=None)
    record_count: Optional[int] = record_field(format="number", default=None)
    duration: Optional[float] = record_field(format="number", default=None)
    meta: Dict[str, Any] = dataclasses.field(default_factory=dict)
    raw: Any = dataclasses.field(default=None)

    default_fields: ClassVar[Tuple[str, ...]] = (
        "tool",
        "session_id",
        "record_id",
        "timestamp",
        "kind",
        "content",
    )

    def __post_init__(self) -> None:
        self.timestamp = _to_datetime(self.timestamp)
        self.end_timestamp = _to_datetime(self.end_timestamp)
        if self.record_count is not None and not isinstance(self.record_count, int):
            self.record_count = int(self.record_count)
        if self.duration is not None and not isinstance(self.duration, (int, float)):
            self.duration = float(self.duration)
        if self.content is None:
            self.content = ""
        if self.short_hash is None:
            if self.session_id:
                self.short_hash = self.session_id[:8]
            elif self.record_id and isinstance(self.record_id, str):
                self.short_hash = self.record_id[:8]

    @classmethod
    def record_fields(cls) -> List[dataclasses.Field]:
        """Return the dataclass fields for this record type."""
        return list(dataclasses.fields(cls))

    @classmethod
    def field_format(cls, name: str) -> str:
        field = cls.__dataclass_fields__.get(name)
        if field and field.metadata:
            return field.metadata.get("format", "default")
        return "default"


@dataclasses.dataclass
class SourceRecord(Record):
    """Record for source-level listings (``slq ls``)."""

    default_fields: ClassVar[Tuple[str, ...]] = ("tool", "path")


@dataclasses.dataclass
class SessionRecord(Record):
    """Record for session file listings (``slq ls <source>``)."""

    default_fields: ClassVar[Tuple[str, ...]] = ("timestamp", "short_hash")


@dataclasses.dataclass
class FieldRecord(Record):
    """Record for listing the available query/record fields (``slq ls fields``)."""

    field_name: str = record_field(format="text", default="")
    field_type: str = record_field(format="text", default="")

    default_fields: ClassVar[Tuple[str, ...]] = ("field_name", "field_type")


CANONICAL_FIELDS = frozenset(
    f.name
    for f in Record.record_fields()
    if f.name not in ("meta", "raw")
)

VALID_FIELD_NAMES = sorted(CANONICAL_FIELDS)


def resolve_field(name: str) -> str:
    if name not in CANONICAL_FIELDS:
        raise UnknownFieldError(
            f"unknown field {name!r}; "
            f"valid fields: {', '.join(VALID_FIELD_NAMES)}"
        )
    return name


def resolve_field_prefix(name: str) -> str:
    """Resolve a field spec that may be a prefix of a canonical field name.

    An exact canonical name is resolved first. If the prefix is unique, the
    canonical field is returned. If it matches zero or multiple fields, an
    error lists the valid names or the possible matches.
    """
    if name in CANONICAL_FIELDS:
        return name
    matches = [n for n in VALID_FIELD_NAMES if n.startswith(name)]
    if not matches:
        raise UnknownFieldError(
            f"unknown field {name!r}; "
            f"valid fields: {', '.join(VALID_FIELD_NAMES)}"
        )
    if len(matches) == 1:
        return matches[0]
    raise UnknownFieldError(
        f"ambiguous field {name!r}; possible matches: {', '.join(matches)}"
    )


def _to_datetime(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value
    if isinstance(value, str):
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    if isinstance(value, (int, float)):
        v = value
        if v > 1e12:
            v = v / 1000.0
        return datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc)
    raise QueryError(f"cannot parse timestamp {value!r}")


def _render_datetime(value: Any) -> str:
    if not isinstance(value, datetime.datetime):
        return format_value(value)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _render_hash(value: Any) -> str:
    return format_value(value)


def _render_short_hash(value: Any) -> str:
    return format_value(value)


def _render_path(value: Any) -> str:
    return format_value(value)


def _render_text(value: Any) -> str:
    return format_value(value)


def _render_number(value: Any) -> str:
    return format_value(value)


def _render_default(value: Any) -> str:
    return format_value(value)


FIELD_RENDERERS: Dict[str, Callable[[Any], str]] = {
    "datetime": _render_datetime,
    "hash": _render_hash,
    "short-hash": _render_short_hash,
    "path": _render_path,
    "text": _render_text,
    "number": _render_number,
    "default": _render_default,
}


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, sort_keys=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def record_value(record: Record, field: str) -> str:
    if field == "meta":
        return json.dumps(record.meta, default=str, sort_keys=True)
    if field == "raw":
        return json.dumps(record.raw, default=str, sort_keys=True)
    value = getattr(record, field, None)
    fmt = record.__class__.field_format(field)
    renderer = FIELD_RENDERERS.get(fmt, _render_default)
    return renderer(value)


def normalize_kind(value: Optional[str]) -> str:
    if not value:
        return "other"
    v = value.lower()
    if v in ("user", "human"):
        return "user"
    if v in ("assistant", "agent", "developer"):
        return "agent"
    if v in ("thinking", "thought"):
        return "thinking"
    if v in ("tool_call", "tool_use", "function_call"):
        return "tool_call"
    if v in ("tool_output", "tool_result", "tool_response"):
        return "tool_output"
    if v in ("meta", "system", "session_meta", "mode", "permission-mode"):
        return "meta"
    return "other"
