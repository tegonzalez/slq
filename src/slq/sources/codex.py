import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..eval import allows_kind
from ..query import QueryAST
from ..resources import get_resource, get_resource_manager
from ..schema import Record, SessionRecord, normalize_kind
from . import DataSource, _extract_text, _extract_uuid, _file_mtime, _model_from, _parse_timestamp, _session_sort_key


def _has_jsonl(path: Path) -> bool:
    try:
        return any(path.rglob("*.jsonl"))
    except (OSError, PermissionError):
        return False


class CodexSource(DataSource):
    name = "codex"

    def __init__(self, paths: Optional[List[Path]] = None):
        super().__init__(paths)

    @property
    def default_paths(self) -> List[Path]:
        if self._paths:
            return self._paths
        return [
            Path.home() / ".codex" / "sessions",
        ]

    def admits(self, path: Path) -> bool:
        return path.is_dir() and _has_jsonl(path)

    def records(self, ast: QueryAST, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        for base in self.admitted_paths(env):
            for file in sorted(base.rglob("*.jsonl")):
                yield from self._read_file(file, ast)

    def sessions(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        manager = get_resource_manager()
        files: List[Path] = []
        for base in self.admitted_paths(env):
            files.extend(sorted(base.rglob("*.jsonl")))
        workers = manager.queue.max_workers
        chunk_size = max(1, (len(files) + workers - 1) // workers)
        chunks = [files[i : i + chunk_size] for i in range(0, len(files), chunk_size)]
        records: List[Record] = []
        for chunk in manager.map(self._list_chunk, chunks):
            records.extend(record for record in chunk if record)
        records.sort(key=_session_sort_key)
        for record in records:
            yield record

    def _list_chunk(self, files: List[Path]) -> List[Record]:
        return [r for r in (self._list_file_once(f) for f in files) if r]

    def _list_file_once(self, file: Path) -> Optional[Record]:
        session_id = _extract_session_id(file)
        resource = get_resource(file)

        first_idx, first_obj = resource.first_object(_is_event)
        if not first_obj:
            return None

        first_ts = _extract_timestamp(first_obj)
        if first_ts is None:
            first_ts = _file_mtime(file)

        cwd = None
        model = None
        inner = first_obj.get("payload") or first_obj
        if isinstance(inner, dict):
            cwd = inner.get("cwd")
            model = _model_from(inner) or _model_from(first_obj)

        return SessionRecord(
            tool=self.name,
            session_id=session_id,
            record_id=session_id,
            timestamp=first_ts,
            end_timestamp=None,
            kind="session",
            rec_type="session",
            content="",
            path=str(file),
            cwd=cwd,
            model=model,
            record_count=None,
            duration=None,
            raw=None,
        )

    def _read_file(self, file: Path, ast: QueryAST) -> Iterator[Record]:
        session_id = _extract_session_id(file)
        file_date = _file_date(file)
        if not allows_value_on_file(ast, "session_id", session_id, file):
            return
        if not allows_value_on_file(ast, "timestamp", file_date, file):
            return

        resource = get_resource(file)
        need_session = allows_kind(ast, "session")

        def mapper(idx: int, obj: Optional[Dict[str, Any]]) -> Optional[Record]:
            if not obj:
                return None
            inner = obj.get("payload", obj)
            if not isinstance(inner, dict):
                return None
            return self._map_record(obj, inner, file, session_id, idx)

        if need_session:
            records: List[Record] = []
            for rec in resource.iter_records(mapper):
                records.append(rec)
                yield rec
            if records:
                session = self._session_record(records, file, session_id)
                if session:
                    yield session
        else:
            for rec in resource.iter_records(mapper):
                yield rec

    def _map_record(
        self,
        obj: Dict[str, Any],
        inner: Dict[str, Any],
        file: Path,
        session_id: Optional[str],
        idx: int,
    ) -> Record:
        ts = _parse_timestamp(inner.get("created_at") or obj.get("timestamp"))
        role = inner.get("role") or obj.get("role")
        rec_type = inner.get("type") or obj.get("type") or role
        kind = normalize_kind(role or rec_type)
        record_id = inner.get("id") or f"{session_id}-{idx}"
        content = _extract_text(inner.get("content"))
        return Record(
            tool=self.name,
            session_id=session_id,
            record_id=record_id,
            timestamp=ts,
            kind=kind,
            role=role or rec_type,
            rec_type=rec_type,
            content=content,
            path=str(file),
            cwd=inner.get("cwd"),
            model=_model_from(inner) or _model_from(obj),
            raw=obj,
        )

    def _session_record(
        self,
        records: List[Record],
        file: Path,
        session_id: Optional[str],
    ) -> Record:
        event_records = [r for r in records if r.kind != "meta"]
        if not event_records:
            return None
        session_meta: Optional[Dict[str, Any]] = None
        for r in records:
            if r.rec_type == "session_meta" and isinstance(r.raw, dict) and isinstance(r.raw.get("payload"), dict):
                session_meta = r.raw["payload"]
                break
        first_ts = min((r.timestamp for r in event_records if r.timestamp), default=None)
        last_ts = max((r.timestamp for r in event_records if r.timestamp), default=None)
        content = "\n".join(r.content for r in event_records if r.content)
        duration: Optional[float] = None
        if first_ts and last_ts:
            duration = (last_ts - first_ts).total_seconds()
        cwd = None
        model = None
        for r in event_records:
            if not cwd and r.cwd:
                cwd = r.cwd
            if not model and r.model:
                model = r.model
            if cwd and model:
                break
        if not cwd and session_meta:
            cwd = session_meta.get("cwd")
        if not model:
            model = _model_from(session_meta) if session_meta else None
        return Record(
            tool=self.name,
            session_id=session_id,
            record_id=session_id,
            timestamp=first_ts,
            end_timestamp=last_ts,
            kind="session",
            role="session",
            rec_type="session",
            content=content,
            path=str(file),
            cwd=cwd,
            model=model,
            record_count=len(event_records),
            duration=duration,
            raw=session_meta,
        )


def _is_event(obj: Optional[Dict[str, Any]]) -> bool:
    return isinstance(obj, dict) and obj.get("type") != "session_meta"


def _extract_timestamp(obj: Optional[Dict[str, Any]]) -> Optional[datetime.datetime]:
    if not isinstance(obj, dict):
        return None
    inner = obj.get("payload") or obj
    if isinstance(inner, dict):
        return _parse_timestamp(inner.get("created_at") or obj.get("timestamp"))
    return _parse_timestamp(obj.get("timestamp"))


def _extract_session_id(file: Path) -> Optional[str]:
    stem = file.stem
    m = _extract_uuid(stem)
    if m:
        return m
    return stem


def _file_date(file: Path) -> Optional[str]:
    parts = file.parts
    try:
        if len(parts) >= 4:
            return f"{parts[-4]}-{parts[-3]}-{parts[-2]}"
    except (ValueError, IndexError):
        pass
    return None


def allows_value_on_file(
    ast: QueryAST,
    field: str,
    value: Optional[str],
    file: Path,
) -> bool:
    from ..eval import allows_value
    if value is None:
        return True
    return allows_value(ast, field, value)
