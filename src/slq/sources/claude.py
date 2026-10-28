import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..eval import allows_kind, allows_value
from ..query import QueryAST
from ..resources import get_resource, get_resource_manager
from ..schema import Record, SessionRecord, SourceRecord, normalize_kind
from . import DataSource, _extract_text, _file_mtime, _model_from, _parse_timestamp, _session_sort_key


def _default_claude_roots() -> List[Path]:
    roots: List[Path] = []
    cfg_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if cfg_dir:
        roots.append(Path(cfg_dir).expanduser() / "projects")
    roots.append(Path.home() / ".claude" / "projects")

    ccs_roots: List[Path] = []
    ccs_env = os.environ.get("CCS_DIR", "").strip()
    if ccs_env:
        ccs_roots.append(Path(ccs_env).expanduser() / "instances")
    ccs_roots.append(Path.home() / ".ccs" / "instances")

    for inst_root in ccs_roots:
        try:
            if not inst_root.is_dir():
                continue
            for inst in sorted(inst_root.iterdir()):
                if inst.name.startswith("."):
                    continue
                roots.append(inst / "projects")
        except (OSError, PermissionError):
            continue
    return roots


def _infer_profile(projects_dir: Path) -> str:
    for candidate in (projects_dir, _safe_resolve(projects_dir)):
        if candidate.name == "projects":
            parent = candidate.parent
            if parent.name in (".claude", "claude") and parent.parent.name != "instances":
                return "default"
            if parent.parent.name == "instances":
                return parent.name
    if projects_dir.name == "projects":
        return projects_dir.parent.name or "default"
    return projects_dir.name or "default"


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _scan_header(
    resource: Any,
    *,
    need_ts: bool,
    need_cwd: bool,
    need_model: bool,
    max_lines: int = 32,
) -> Tuple[Optional[datetime.datetime], Optional[str], Optional[str]]:
    first_ts: Optional[datetime.datetime] = None
    cwd: Optional[str] = None
    model: Optional[str] = None
    seen = 0

    def _visit(obj: Optional[Dict[str, Any]]) -> bool:
        nonlocal first_ts, cwd, model, seen
        seen += 1
        if isinstance(obj, dict):
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
            if need_ts and first_ts is None:
                first_ts = _parse_timestamp(
                    obj.get("timestamp") or msg.get("timestamp") or msg.get("created_at")
                )
            if need_cwd and cwd is None:
                cwd = obj.get("cwd") or msg.get("cwd")
            if need_model and model is None:
                model = _model_from(msg) or _model_from(obj)
        done = (
            (not need_ts or first_ts is not None)
            and (not need_cwd or cwd is not None)
            and (not need_model or model is not None)
        )
        return done or seen >= max_lines

    resource.first_object(_visit)
    return first_ts, cwd, model


class ClaudeSource(DataSource):
    name = "claude"

    def __init__(self, paths: Optional[List[Path]] = None, sessions_dir: Optional[Path] = None):
        super().__init__(paths)
        self._sessions_dir = sessions_dir

    @property
    def default_paths(self) -> List[Path]:
        if self._paths:
            return self._paths
        return _default_claude_roots()

    def admits(self, path: Path) -> bool:
        return path.is_dir()

    def list(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        for path in self.admitted_paths(env):
            yield SourceRecord(
                tool=self.name,
                kind="source",
                record_id=self.name,
                path=str(path),
                profile=_infer_profile(path),
                content="",
            )

    def _sessions_dir_for_base(self, base: Path, env: Optional[Dict[str, Any]] = None) -> Path:
        explicit = (env or {}).get("sessions_dir") or self._sessions_dir
        if explicit is not None:
            return Path(explicit)
        return base.parent / "sessions"

    def records(self, ast: QueryAST, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        for base in self.admitted_paths(env):
            profile = _infer_profile(base)
            if not _allows_value_on_file(ast, "profile", profile):
                continue
            metadata = self._load_metadata(self._sessions_dir_for_base(base, env))
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
                    yield from self._read_file(file, ast, session_id, project, profile, meta)

    def sessions(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        manager = get_resource_manager()
        items: List[Tuple[Path, str, str, Optional[Dict[str, Any]]]] = []
        for base in self.admitted_paths(env):
            profile = _infer_profile(base)
            metadata = self._load_metadata(self._sessions_dir_for_base(base, env))
            for project_dir in sorted(base.iterdir()):
                if not project_dir.is_dir():
                    continue
                project = project_dir.name
                for file in sorted(project_dir.glob("*.jsonl")):
                    meta = metadata.get(file.stem)
                    items.append((file, project, profile, meta))
        workers = manager.queue.max_workers
        chunk_size = max(1, (len(items) + workers - 1) // workers)
        chunks = [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]
        records: List[Record] = []
        for chunk in manager.map(self._list_chunk, chunks):
            records.extend(record for record in chunk if record)
        records.sort(key=_session_sort_key)
        for record in records:
            yield record

    def _list_chunk(self, items: List[Tuple[Path, str, str, Optional[Dict[str, Any]]]]) -> List[Record]:
        return [r for r in (self._list_file_once(item) for item in items) if r]

    def _list_file_once(
        self,
        item: Tuple[Path, str, str, Optional[Dict[str, Any]]],
    ) -> Optional[Record]:
        file, project, profile, meta = item
        session_id = file.stem
        first_ts = _parse_timestamp((meta or {}).get("startedAt"))
        cwd = (meta or {}).get("cwd")
        model = _model_from(meta) if meta else None

        if first_ts is None or cwd is None or model is None:
            resource = get_resource(file)
            scanned_ts, scanned_cwd, scanned_model = _scan_header(
                resource,
                need_ts=first_ts is None,
                need_cwd=cwd is None,
                need_model=model is None,
            )
            if first_ts is None:
                first_ts = scanned_ts
            if cwd is None:
                cwd = scanned_cwd
            if model is None:
                model = scanned_model

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
            cwd=cwd,
            profile=profile,
            project=project,
            model=model,
            record_count=None,
            duration=None,
            raw=meta,
        )

    def _load_metadata(self, sessions_dir: Path) -> Dict[str, Dict[str, Any]]:
        if not sessions_dir.exists():
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for file in sorted(sessions_dir.glob("*.json")):
            try:
                with file.open("r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                sid = data.get("sessionId")
                if sid:
                    out[sid] = data
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def _read_file(
        self,
        file: Path,
        ast: QueryAST,
        session_id: Optional[str],
        project: Optional[str],
        profile: Optional[str],
        meta: Optional[Dict[str, Any]],
    ) -> Iterator[Record]:
        resource = get_resource(file)
        need_session = allows_kind(ast, "session")

        def mapper(idx: int, obj: Optional[Dict[str, Any]]) -> Optional[Record]:
            if not obj:
                return None
            return self._map_record(obj, file, session_id, project, profile, meta, idx)

        if need_session:
            records: List[Record] = []
            for rec in resource.iter_records(mapper):
                records.append(rec)
                yield rec
            if records:
                session = self._session_record(records, file, session_id, project, profile, meta)
                if session:
                    yield session
        else:
            for rec in resource.iter_records(mapper):
                yield rec

    def _map_record(
        self,
        obj: Dict[str, Any],
        file: Path,
        session_id: Optional[str],
        project: Optional[str],
        profile: Optional[str],
        meta: Optional[Dict[str, Any]],
        idx: int,
    ) -> Record:
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        ts = _parse_timestamp(obj.get("timestamp") or msg.get("timestamp") or msg.get("created_at"))
        role = msg.get("role") or obj.get("role")
        rec_type = obj.get("type") or msg.get("type") or role
        kind = normalize_kind(role or rec_type)
        record_id = obj.get("uuid") or msg.get("id") or f"{session_id}-{idx}"
        parent_id = obj.get("parentUuid") or msg.get("parent_id")
        content = _extract_text(msg.get("content") or obj.get("content"))
        cwd = obj.get("cwd") or (meta or {}).get("cwd")
        model = _model_from(msg) or _model_from(obj)
        return Record(
            tool=self.name,
            session_id=session_id,
            record_id=record_id,
            parent_id=parent_id,
            timestamp=ts,
            kind=kind,
            role=role or rec_type,
            rec_type=rec_type,
            content=content,
            path=str(file),
            cwd=cwd,
            profile=profile,
            project=project,
            model=model,
            raw=obj,
        )

    def _session_record(
        self,
        records: List[Record],
        file: Path,
        session_id: Optional[str],
        project: Optional[str],
        profile: Optional[str],
        meta: Optional[Dict[str, Any]],
    ) -> Record:
        first_ts = min((r.timestamp for r in records if r.timestamp), default=None)
        last_ts = max((r.timestamp for r in records if r.timestamp), default=None)
        if not first_ts and meta:
            first_ts = _parse_timestamp(meta.get("startedAt"))
        content = "\n".join(r.content for r in records if r.content)
        duration: Optional[float] = None
        if first_ts and last_ts:
            duration = (last_ts - first_ts).total_seconds()
        cwd = (meta or {}).get("cwd") or next((r.cwd for r in records if r.cwd), None)
        model = (_model_from(meta) if meta else None) or next((r.model for r in records if r.model), None)
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
            profile=profile,
            project=project,
            model=model,
            record_count=len(records),
            duration=duration,
            raw=meta,
        )


def _allows_value_on_file(ast: QueryAST, field: str, value: Optional[str]) -> bool:
    if value is None:
        return True
    return allows_value(ast, field, value)
