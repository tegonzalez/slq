import datetime
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..eval import allows_kind, allows_value
from ..query import QueryAST
from ..resources import get_resource, get_resource_manager
from ..schema import Record, SessionRecord, normalize_kind
from . import DataSource, _extract_text, _file_mtime, _model_from, _parse_timestamp, _session_sort_key


class ClaudeSource(DataSource):
    name = "claude"

    def __init__(self, paths: Optional[List[Path]] = None, sessions_dir: Optional[Path] = None):
        super().__init__(paths)
        self._sessions_dir = sessions_dir

    @property
    def default_paths(self) -> List[Path]:
        if self._paths:
            return self._paths
        return [Path.home() / ".claude" / "projects"]

    def records(self, ast: QueryAST, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        paths = (env or {}).get("paths") or self.default_paths
        sessions_dir = (env or {}).get("sessions_dir") or self._sessions_dir or (Path.home() / ".claude" / "sessions")
        metadata = self._load_metadata(sessions_dir)
        for base in paths:
            if not base.exists():
                continue
            for project_dir in sorted(base.iterdir()):
                if not project_dir.is_dir():
                    continue
                project = project_dir.name
                if not _allows_value_on_file(ast, "project", project):
                    continue
                for file in sorted(project_dir.glob("*.jsonl")):
                    session_id = file.stem
                    if not _allows_value_on_file(ast, "session_id", session_id):
                        continue
                    meta = metadata.get(session_id)
                    cwd = (meta or {}).get("cwd")
                    if not _allows_value_on_file(ast, "cwd", cwd):
                        continue
                    yield from self._read_file(file, ast, session_id, project, meta)

    def sessions(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        paths = (env or {}).get("paths") or self.default_paths
        sessions_dir = (env or {}).get("sessions_dir") or self._sessions_dir or (Path.home() / ".claude" / "sessions")
        metadata = self._load_metadata(sessions_dir)
        manager = get_resource_manager()
        items: List[Tuple[Path, str, Optional[Dict[str, Any]]]] = []
        for base in paths:
            if not base.exists():
                continue
            for project_dir in sorted(base.iterdir()):
                if not project_dir.is_dir():
                    continue
                project = project_dir.name
                for file in sorted(project_dir.glob("*.jsonl")):
                    session_id = file.stem
                    meta = metadata.get(session_id)
                    items.append((file, project, meta))

        workers = manager.queue.max_workers
        chunk_size = max(1, (len(items) + workers - 1) // workers)
        chunks = [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]
        records: List[Record] = []
        for chunk in manager.map(self._list_chunk, chunks):
            records.extend(record for record in chunk if record)
        records.sort(key=_session_sort_key)
        for record in records:
            yield record

    def _list_chunk(
        self,
        items: List[Tuple[Path, str, Optional[Dict[str, Any]]]],
    ) -> List[Record]:
        return [r for r in (self._list_file_once(i) for i in items) if r]

    def _list_file_once(
        self,
        item: Tuple[Path, str, Optional[Dict[str, Any]]],
    ) -> Optional[Record]:
        file, project, meta = item
        session_id = file.stem

        first_ts: Optional[datetime.datetime] = None
        if meta:
            first_ts = _parse_timestamp(meta.get("startedAt"))

        if first_ts is None:
            resource = get_resource(file)
            first_idx, first_obj = resource.first_object(lambda o: isinstance(o, dict))
            if first_obj:
                first_ts = _parse_timestamp(
                    first_obj.get("timestamp")
                    or (first_obj.get("message") or {}).get("timestamp")
                    or (first_obj.get("message") or {}).get("created_at")
                )

        if first_ts is None:
            first_ts = _file_mtime(file)

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
            cwd=(meta or {}).get("cwd"),
            project=project,
            record_count=None,
            duration=None,
            raw=meta,
        )

    def _load_metadata(self, sessions_dir: Path) -> Dict[str, Dict[str, Any]]:
        mapping: Dict[str, Dict[str, Any]] = {}
        if not sessions_dir.exists():
            return mapping
        for path in sessions_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    obj = json.load(f)
                sid = obj.get("sessionId") or path.stem
                mapping[sid] = obj
            except (OSError, json.JSONDecodeError):
                continue
        return mapping

    def _read_file(
        self,
        file: Path,
        ast: QueryAST,
        session_id: str,
        project: Optional[str],
        meta: Optional[Dict[str, Any]],
    ) -> Iterator[Record]:
        resource = get_resource(file)
        need_session = allows_kind(ast, "session")

        def mapper(idx: int, obj: Optional[Dict[str, Any]]) -> Optional[Record]:
            if not isinstance(obj, dict):
                return None
            return self._map_record(obj, file, session_id, project, meta, idx)

        if need_session:
            records: List[Record] = []
            for rec in resource.iter_records(mapper):
                records.append(rec)
                yield rec
            if records:
                session = self._session_record(records, file, session_id, project, meta)
                if session:
                    yield session
        else:
            for rec in resource.iter_records(mapper):
                yield rec

    def _map_record(
        self,
        obj: Dict[str, Any],
        file: Path,
        session_id: str,
        project: Optional[str],
        meta: Optional[Dict[str, Any]],
        idx: int,
    ) -> Record:
        msg = obj.get("message") or obj
        if not isinstance(msg, dict):
            msg = obj
        rec_type = obj.get("type") or msg.get("type")
        role = msg.get("role") or obj.get("role")
        if not role and rec_type in ("user", "assistant"):
            role = rec_type
        kind = normalize_kind(role or rec_type)
        record_id = msg.get("id") or obj.get("uuid") or f"{session_id}-{idx}"
        ts = _parse_timestamp(
            obj.get("timestamp") or msg.get("timestamp") or msg.get("created_at")
        )
        content = _extract_text(msg.get("content"))
        cwd = obj.get("cwd") or (meta or {}).get("cwd")
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
            cwd=cwd,
            project=project,
            model=_model_from(msg) or _model_from(obj),
            raw=obj,
        )

    def _session_record(
        self,
        records: List[Record],
        file: Path,
        session_id: str,
        project: Optional[str],
        meta: Optional[Dict[str, Any]],
    ) -> Record:
        event_records = [r for r in records if r.kind != "meta"]
        if not event_records:
            return None
        first_ts = min((r.timestamp for r in event_records if r.timestamp), default=None)
        last_ts = max((r.timestamp for r in event_records if r.timestamp), default=None)
        content = "\n".join(r.content for r in event_records if r.content)
        duration: Optional[float] = None
        if first_ts and last_ts:
            duration = (last_ts - first_ts).total_seconds()
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
            cwd=(meta or {}).get("cwd"),
            project=project,
            record_count=len(event_records),
            duration=duration,
            raw=meta,
        )


def _allows_value_on_file(ast: QueryAST, field: str, value: Optional[str]) -> bool:
    if value is None:
        return True
    return allows_value(ast, field, value)
