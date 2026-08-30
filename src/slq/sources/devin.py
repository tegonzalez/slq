import asyncio
import json
import queue
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import aiosqlite

from ..eval import allows_kind
from ..pushdown import QueryRequest, SQLBuilder, SQLColumn, drop_field
from ..query import QueryAST
from ..schema import Record, SessionRecord
from . import DataSource, _extract_text, _parse_timestamp, _session_sort_key


class DevinSource(DataSource):
    """Source adapter for the Devin CLI SQLite session store.

    Reads the canonical chat database at ``~/.local-rw/share/devin/cli/sessions.db``
    (or a user-supplied path via ``env["paths"]``) and maps ``message_nodes`` rows to
    the shared ``Record`` schema.  Queries are pushed down to SQLite via the
    ``SQLBuilder`` so regex, kind, timestamp and session filters run in the
    database before the ``Cursor`` sees the rows.
    """

    name = "devin"

    @staticmethod
    def _short_hash(session_id: str, min_len: int = 12, max_len: int = 16) -> str:
        """Return a short, hyphen-bounded identifier for a Devin session slug.

        The goal is a value that is recognisably different from the 8-character
        UUID prefixes used by codex/claude, while still being short and unique
        enough for display.  We prefer whole hyphen-separated segments, but will
        extend into the next segment if needed to reach ``min_len``.
        """
        if len(session_id) <= max_len:
            return session_id
        parts = session_id.split("-")
        result = parts[0]
        if len(result) >= max_len:
            return result[:max_len]
        for part in parts[1:]:
            candidate = f"{result}-{part}"
            if len(candidate) <= max_len:
                result = candidate
            else:
                if len(result) >= min_len:
                    break
                needed = max_len - len(result) - 1
                if needed > 0:
                    result = f"{result}-{part[:needed]}"
                break
        return result

    def __init__(self, paths: Optional[List[Path]] = None):
        super().__init__(paths)

    @property
    def default_paths(self) -> List[Path]:
        if self._paths:
            return self._paths
        return [
            Path.home() / ".devin" / "sessions.db",
            Path.home() / ".local-rw" / "share" / "devin" / "cli" / "sessions.db",
            Path.home() / ".local" / "share" / "devin" / "cli" / "sessions.db",
        ]

    def sessions(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        result: List[Record] = []

        async def _run(path: Path) -> None:
            async with self._open_db(path) as db:
                await self._init_db(db)
                sql = self._session_sql()
                async with db.execute(sql) as cursor:
                    async for row in cursor:
                        rec = self._map_session(row, str(path))
                        if rec:
                            result.append(rec)

        for path in self.admitted_paths(env):
            asyncio.run(_run(path))

        result.sort(key=_session_sort_key)
        for rec in result:
            yield rec

    def records(
        self,
        ast: Optional[QueryAST] = None,
        env: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Record]:
        env = env or {}
        since = env.get("since")
        until = env.get("until")
        request = QueryRequest(ast=ast, env=env, since=since, until=until)

        for path in self.admitted_paths(env):
            q: queue.Queue = queue.Queue(maxsize=64)

            def _runner(p: Path = path) -> None:
                asyncio.run(self._records_async(request, p, q))

            thread = threading.Thread(target=_runner, daemon=True)
            thread.start()
            while True:
                rec = q.get()
                if rec is None:
                    break
                yield rec
            thread.join()

    async def _records_async(
        self,
        request: QueryRequest,
        path: Path,
        out: queue.Queue,
    ) -> None:
        builder = self._event_columns(str(path))
        since = request.since
        until = request.until

        need_session = request.ast is not None and allows_kind(request.ast, "session")
        query_ast = drop_field(request.ast, "kind") if need_session else request.ast
        where, params = builder.build(query_ast, since=since, until=until)

        sql = f"""
        SELECT
            m.row_id,
            m.session_id,
            m.node_id,
            m.parent_node_id,
            m.chat_message,
            s.working_directory,
            s.workspace_dirs,
            s.model,
            s.backend_type,
            s.agent_mode,
            s.title,
            CAST(s.created_at AS INTEGER) AS session_created_at,
            CAST(s.last_activity_at AS INTEGER) AS session_last_activity_at
        FROM message_nodes m
        JOIN sessions s ON m.session_id = s.id
        WHERE {where}
        ORDER BY m.session_id, m.row_id
        """

        async with self._open_db(path) as db:
            await self._init_db(db)
            async with db.execute(sql, params) as cursor:
                current_session: Optional[str] = None
                session_events: List[Record] = []
                session_meta: Optional[Dict[str, Any]] = None

                async for row in cursor:
                    rec = self._map_event(row, str(path))
                    if not rec:
                        continue

                    if need_session:
                        if rec.session_id != current_session:
                            if current_session and session_events:
                                session = self._build_session_record(
                                    session_events, session_meta, str(path)
                                )
                                if session:
                                    out.put(session)
                            current_session = rec.session_id
                            session_events = []
                            session_meta = None
                        session_events.append(rec)
                        if session_meta is None:
                            session_meta = self._session_meta_from_event_row(row)

                    out.put(rec)

                if need_session and current_session and session_events:
                    session = self._build_session_record(
                        session_events, session_meta, str(path)
                    )
                    if session:
                        out.put(session)

        out.put(None)

    def _open_db(self, path: Path) -> aiosqlite.Connection:
        return aiosqlite.connect(f"file:{path}?mode=ro", uri=True)

    async def _init_db(self, db: aiosqlite.Connection) -> aiosqlite.Connection:
        db.row_factory = sqlite3.Row
        await db.create_function(
            "regexp",
            2,
            lambda pattern, value: 1 if re.search(pattern or "", value or "") else 0,
            deterministic=True,
        )
        return db

    def _event_columns(self, db_path: str) -> SQLBuilder:
        c = {
            "tool": SQLColumn("'devin'"),
            "session_id": SQLColumn("m.session_id"),
            "record_id": SQLColumn("m.session_id || '-' || m.node_id"),
            "parent_id": SQLColumn(
                "CASE WHEN m.parent_node_id IS NULL THEN '' ELSE m.session_id || '-' || m.parent_node_id END"
            ),
            "timestamp": SQLColumn(
                "COALESCE(strftime('%Y-%m-%d %H:%M:%S', datetime(json_extract(m.chat_message, '$.metadata.created_at'))), '')"
            ),
            "end_timestamp": SQLColumn("''"),
            "kind": SQLColumn(self._kind_sql()),
            "role": SQLColumn("COALESCE(json_extract(m.chat_message, '$.role'), '')"),
            "rec_type": SQLColumn(self._rec_type_sql()),
            "subtype": SQLColumn(
                "COALESCE(json_extract(m.chat_message, '$.metadata.telemetry.source'), '')"
            ),
            "content": SQLColumn(self._content_sql()),
            "path": SQLColumn(f"'{db_path}'"),
            "cwd": SQLColumn("COALESCE(s.working_directory, '')"),
            "project": SQLColumn("COALESCE(json_extract(s.workspace_dirs, '$[0]'), '')"),
            "model": SQLColumn(
                "COALESCE(json_extract(m.chat_message, '$.metadata.generation_model'), s.model, '')"
            ),
            "record_count": SQLColumn("''"),
            "duration": SQLColumn(self._duration_sql()),
        }
        return SQLBuilder(c)

    @staticmethod
    def _kind_sql() -> str:
        return """
        CASE
          WHEN json_extract(m.chat_message, '$.role') = 'system' THEN 'meta'
          WHEN json_extract(m.chat_message, '$.role') = 'user' THEN 'user'
          WHEN json_extract(m.chat_message, '$.role') = 'assistant'
               AND json_extract(m.chat_message, '$.metadata.finish_reason') = 'tool_calls' THEN 'tool_call'
          WHEN json_extract(m.chat_message, '$.role') = 'assistant' THEN 'agent'
          WHEN json_extract(m.chat_message, '$.role') = 'tool' THEN 'tool_output'
          ELSE 'other'
        END
        """.strip()

    @staticmethod
    def _rec_type_sql() -> str:
        return """
        CASE
          WHEN json_extract(m.chat_message, '$.role') = 'assistant'
            THEN COALESCE(json_extract(m.chat_message, '$.metadata.finish_reason'), '')
          WHEN json_extract(m.chat_message, '$.role') = 'tool'
            THEN COALESCE(json_extract(m.chat_message, '$.metadata.extensions."chisel/tool_result_meta".kind'), '')
          ELSE COALESCE(json_extract(m.chat_message, '$.metadata.telemetry.source'), '')
        END
        """.strip()

    @staticmethod
    def _content_sql() -> str:
        return """
        CASE
          WHEN json_extract(m.chat_message, '$.role') = 'assistant'
               AND json_extract(m.chat_message, '$.metadata.finish_reason') = 'tool_calls'
            THEN COALESCE(json(json_extract(m.chat_message, '$.metadata.extensions."chisel/tool_call_content"')), '')
          ELSE COALESCE(json_extract(m.chat_message, '$.content'), '')
        END
        """.strip()

    @staticmethod
    def _duration_sql() -> str:
        return """
        CASE
          WHEN json_extract(m.chat_message, '$.metadata.metrics.total_time_ms') IS NOT NULL
            THEN CAST(CAST(json_extract(m.chat_message, '$.metadata.metrics.total_time_ms') AS REAL) / 1000.0 AS TEXT)
          WHEN json_extract(m.chat_message, '$.metadata.extensions."chisel/tool_call_timing".duration_ms') IS NOT NULL
            THEN CAST(CAST(json_extract(m.chat_message, '$.metadata.extensions."chisel/tool_call_timing".duration_ms') AS REAL) / 1000.0 AS TEXT)
          ELSE ''
        END
        """.strip()

    @staticmethod
    def _map_event(row: sqlite3.Row, db_path: str) -> Optional[Record]:
        raw = row["chat_message"]
        if not raw:
            return None
        try:
            chat = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

        meta = chat.get("metadata") or {}
        role = chat.get("role") or ""
        finish_reason = meta.get("finish_reason")
        telemetry = meta.get("telemetry") or {}

        kind = "other"
        if role == "system":
            kind = "meta"
        elif role == "user":
            kind = "user"
        elif role == "assistant" and finish_reason == "tool_calls":
            kind = "tool_call"
        elif role == "assistant":
            kind = "agent"
        elif role == "tool":
            kind = "tool_output"

        if role == "assistant":
            rec_type = finish_reason or ""
        elif role == "tool":
            tool_meta = (
                meta.get("extensions", {}).get("chisel/tool_result_meta") or {}
            )
            rec_type = tool_meta.get("kind") or ""
        else:
            rec_type = telemetry.get("source") or ""

        if role == "assistant" and finish_reason == "tool_calls":
            tool_calls = (
                meta.get("extensions", {}).get("chisel/tool_call_content") or {}
            )
            content = json.dumps(tool_calls, default=str, sort_keys=True)
        else:
            content = _extract_text(chat.get("content"))

        duration: Optional[float] = None
        metrics = meta.get("metrics") or {}
        if "total_time_ms" in metrics and metrics["total_time_ms"] is not None:
            duration = float(metrics["total_time_ms"]) / 1000.0
        else:
            timing = (
                meta.get("extensions", {}).get("chisel/tool_call_timing") or {}
            )
            if "duration_ms" in timing and timing["duration_ms"] is not None:
                duration = float(timing["duration_ms"]) / 1000.0

        session_id = row["session_id"] or ""
        node_id = row["node_id"]
        parent_node_id = row["parent_node_id"]

        workspace_dirs: List[str] = []
        workspace_raw = row["workspace_dirs"]
        if workspace_raw:
            try:
                workspace_dirs = json.loads(workspace_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        project = workspace_dirs[0] if workspace_dirs else None

        return Record(
            tool=DevinSource.name,
            session_id=session_id,
            record_id=f"{session_id}-{node_id}",
            parent_id=(
                f"{session_id}-{parent_node_id}" if parent_node_id is not None else None
            ),
            short_hash=DevinSource._short_hash(session_id),
            timestamp=_parse_timestamp(meta.get("created_at")),
            end_timestamp=None,
            kind=kind,
            role=role,
            rec_type=rec_type,
            subtype=telemetry.get("source") or "",
            content=content,
            path=db_path,
            cwd=row["working_directory"],
            project=project,
            model=meta.get("generation_model") or row["model"],
            record_count=None,
            duration=duration,
            meta={
                "backend_type": row["backend_type"],
                "agent_mode": row["agent_mode"],
                "title": row["title"],
                "request_id": meta.get("request_id"),
                "finish_reason": finish_reason,
                "input_tokens": metrics.get("input_tokens"),
                "output_tokens": metrics.get("output_tokens"),
                "cache_read_tokens": metrics.get("cache_read_tokens"),
                "total_tokens": metrics.get("num_tokens"),
            },
            raw=chat,
        )

    @staticmethod
    def _session_meta_from_event_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "working_directory": row["working_directory"],
            "workspace_dirs": row["workspace_dirs"],
            "model": row["model"],
            "backend_type": row["backend_type"],
            "agent_mode": row["agent_mode"],
            "title": row["title"],
            "created_at": row["session_created_at"],
            "last_activity_at": row["session_last_activity_at"],
        }

    @staticmethod
    def _build_session_record(
        events: List[Record],
        meta: Optional[Dict[str, Any]],
        db_path: str,
    ) -> Optional[Record]:
        if not events:
            return None
        event_records = [r for r in events if r.kind != "meta"]
        if not event_records:
            return None

        first_ts = min(
            (r.timestamp for r in event_records if r.timestamp),
            default=None,
        )
        last_ts = max(
            (r.timestamp for r in event_records if r.timestamp),
            default=None,
        )

        duration: Optional[float] = None
        if first_ts and last_ts:
            duration = (last_ts - first_ts).total_seconds()

        session_id = events[0].session_id
        cwd = meta.get("working_directory") if meta else None
        project = meta.get("project") if meta else None
        model = meta.get("model") if meta else None
        title = meta.get("title") if meta else None

        for r in event_records:
            if not cwd and r.cwd:
                cwd = r.cwd
            if not model and r.model:
                model = r.model
            if not project and r.project:
                project = r.project
            if cwd and model and project:
                break

        return SessionRecord(
            tool=DevinSource.name,
            session_id=session_id,
            record_id=session_id,
            short_hash=DevinSource._short_hash(session_id),
            timestamp=first_ts,
            end_timestamp=last_ts,
            kind="session",
            role="session",
            rec_type="session",
            subtype="session",
            content=title or "",
            path=db_path,
            cwd=cwd,
            project=project,
            model=model,
            record_count=len(event_records),
            duration=duration,
            meta={
                "backend_type": meta.get("backend_type") if meta else None,
                "agent_mode": meta.get("agent_mode") if meta else None,
                "title": title,
            },
            raw=meta,
        )

    def _session_sql(self) -> str:
        return f"""
        SELECT
            s.id,
            s.working_directory,
            s.workspace_dirs,
            s.model,
            s.backend_type,
            s.agent_mode,
            s.title,
            CAST(s.created_at AS INTEGER) AS created_at,
            CAST(s.last_activity_at AS INTEGER) AS last_activity_at,
            COUNT(m.row_id) FILTER (
                WHERE COALESCE(json_extract(m.chat_message, '$.role'), '') != 'system'
            ) AS record_count
        FROM sessions s
        LEFT JOIN message_nodes m ON m.session_id = s.id
        GROUP BY s.id
        ORDER BY created_at
        """

    @staticmethod
    def _map_session(row: sqlite3.Row, db_path: str) -> Optional[SessionRecord]:
        session_id = row["id"] or ""
        created = row["created_at"]
        last = row["last_activity_at"]

        first_ts = _parse_timestamp(created)
        last_ts = _parse_timestamp(last)
        duration: Optional[float] = None
        if first_ts and last_ts:
            duration = (last_ts - first_ts).total_seconds()

        workspace_dirs: List[str] = []
        workspace_raw = row["workspace_dirs"]
        if workspace_raw:
            try:
                workspace_dirs = json.loads(workspace_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        project = workspace_dirs[0] if workspace_dirs else None

        return SessionRecord(
            tool=DevinSource.name,
            session_id=session_id,
            record_id=session_id,
            short_hash=DevinSource._short_hash(session_id),
            timestamp=first_ts,
            end_timestamp=last_ts,
            kind="session",
            role="session",
            rec_type="session",
            subtype="session",
            content=row["title"] or "",
            path=db_path,
            cwd=row["working_directory"],
            project=project,
            model=row["model"],
            record_count=row["record_count"],
            duration=duration,
            meta={
                "backend_type": row["backend_type"],
                "agent_mode": row["agent_mode"],
                "title": row["title"],
            },
            raw={
                "id": session_id,
                "working_directory": row["working_directory"],
                "workspace_dirs": workspace_dirs,
                "model": row["model"],
                "backend_type": row["backend_type"],
                "agent_mode": row["agent_mode"],
                "title": row["title"],
                "created_at": created,
                "last_activity_at": last,
            },
        )
