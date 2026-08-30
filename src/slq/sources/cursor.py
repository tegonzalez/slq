import asyncio
import datetime
import heapq
import json
import queue
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

import aiosqlite

from .. import platform
from ..eval import allows_kind
from ..pushdown import QueryRequest
from ..query import QueryAST
from ..schema import Record, SessionRecord
from . import DataSource, _parse_timestamp, _session_sort_key
from .cursor_sql import EVENT_KINDS, columns, event_query, session_query


_STREAM_END = object()


def _cursor_timestamp(value: Any) -> Optional[datetime.datetime]:
    """Normalize Cursor's mixed timestamp shapes to UTC."""
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        return None
    return timestamp.astimezone(datetime.timezone.utc)


class CursorSource(DataSource):
    """Source adapter for the Cursor session store."""

    name = "cursor"

    @property
    def default_paths(self) -> List[Path]:
        if self._paths:
            return self._paths
        return [
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb",
            Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
        ]

    def _resolve_store(self, path: Path) -> Optional[Path]:
        """Return the ``state.vscdb`` path that a candidate root resolves to."""
        if path.is_file() and path.name == "state.vscdb":
            return path
        if path.is_dir():
            candidates = [
                path / "state.vscdb",
                path / "User" / "globalStorage" / "state.vscdb",
            ]
            for candidate in candidates:
                if candidate.is_file():
                    return candidate
        return None

    def admits(self, path: Path) -> bool:
        return self._resolve_store(path) is not None

    def admitted_paths(self, env: Optional[Dict[str, Any]] = None) -> List[Path]:
        result: List[Path] = []
        for path in self._candidate_paths(env):
            resolved = self._resolve_store(path)
            if resolved is None:
                continue
            if any(platform.same_path(resolved, seen) for seen in result):
                continue
            result.append(resolved)
        return result

    def sessions(self, env: Optional[Dict[str, Any]] = None) -> Iterator[Record]:
        paths = self.admitted_paths(env)
        if not paths:
            return
        session_iters = [self._sessions_stream(p) for p in paths]
        yield from self._merge_by_timestamp(session_iters)

    def records(
        self,
        ast: Optional[QueryAST] = None,
        env: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Record]:
        env = env or {}
        since = env.get("since")
        until = env.get("until")
        request = QueryRequest(ast=ast, env=env, since=since, until=until)
        paths = self.admitted_paths(env)
        if not paths:
            return

        need_session = request.ast is not None and allows_kind(request.ast, "session")
        need_events = request.ast is None or any(
            allows_kind(request.ast, k) for k in EVENT_KINDS
        )

        if not need_session and not need_events:
            return

        if need_session and not need_events:
            session_iters = [self._sessions_stream(p) for p in paths]
            yield from self._merge_by_timestamp(session_iters)
            return

        if need_events and not need_session:
            event_iters = [self._events_stream(request, p) for p in paths]
            yield from self._merge_by_timestamp(event_iters)
            return

        # The query may match both sessions and events; collect the small session
        # set first, then merge it with the event stream so the result is ordered.
        sessions: List[Record] = []
        for p in paths:
            sessions.extend(self._sessions_stream(p))
        sessions.sort(key=_session_sort_key)

        event_iters = [self._events_stream(request, p) for p in paths]
        yield from self._merge_by_timestamp([iter(sessions)] + event_iters)

    def _merge_by_timestamp(self, iterables: List[Iterable[Record]]) -> Iterator[Record]:
        def key(record: Record):
            if record.timestamp is None:
                return (0, datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
            return (1, record.timestamp)

        yield from heapq.merge(*iterables, key=key)

    def _sessions_stream(self, path: Path) -> Iterator[Record]:
        result: List[Record] = []

        async def _run() -> None:
            async with self._open_db(path) as db:
                await self._init_db(db)
                async with db.execute(session_query()) as cursor:
                    async for row in cursor:
                        rec = self._map_session(row, str(path))
                        if rec:
                            result.append(rec)

        asyncio.run(_run())
        result.sort(key=_session_sort_key)
        for rec in result:
            yield rec

    def _events_stream(
        self, request: QueryRequest, path: Path
    ) -> Iterator[Record]:
        q: queue.Queue = queue.Queue(maxsize=64)
        errors: List[BaseException] = []

        def _runner() -> None:
            try:
                asyncio.run(self._events_async(request, path, q))
            except BaseException as exc:
                errors.append(exc)
            finally:
                q.put(_STREAM_END)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        while True:
            rec = q.get()
            if rec is _STREAM_END:
                break
            yield rec
        thread.join()
        if errors:
            raise errors[0]

    async def _events_async(
        self, request: QueryRequest, path: Path, out: queue.Queue
    ) -> None:
        builder = columns()
        since = request.since
        until = request.until
        where, params = builder.build(request.ast, since=since, until=until)
        sql = event_query(where)

        async with self._open_db(path) as db:
            await self._init_db(db)
            async with db.execute(sql, params) as cursor:
                async for row in cursor:
                    rec = self._map_event(row, str(path))
                    if rec:
                        out.put(rec)

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

    @staticmethod
    def _map_event(row: sqlite3.Row, db_path: str) -> Optional[Record]:
        try:
            bubble = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(bubble, dict):
            return None

        header: Dict[str, Any] = {}
        header_raw = row["header_value"]
        if header_raw:
            try:
                decoded = json.loads(header_raw)
            except (json.JSONDecodeError, TypeError):
                decoded = None
            if isinstance(decoded, dict):
                header = decoded

        key = str(row["key"])
        key_parts = key.split(":", 2)
        if len(key_parts) != 3:
            return None
        session_id = key_parts[1]
        bubble_id = str(bubble.get("bubbleId") or key_parts[2])

        bubble_type = bubble.get("type")
        if bubble_type == 1:
            kind = "user"
            role = "user"
        elif bubble_type == 2:
            kind = "agent"
            role = "assistant"
        else:
            kind = "other"
            role = "other"

        workspace = (
            (header.get("workspaceIdentifier") or {}).get("uri") or {}
        ).get("fsPath")
        duration_ms = bubble.get("turnDurationMs")

        return Record(
            tool=CursorSource.name,
            session_id=session_id,
            record_id=bubble_id,
            timestamp=_cursor_timestamp(bubble.get("createdAt")),
            kind=kind,
            role=role,
            rec_type="bubble",
            subtype=header.get("unifiedMode"),
            content=str(bubble.get("text") or ""),
            path=db_path,
            cwd=workspace,
            project=workspace,
            model=bubble.get("modelType"),
            duration=(float(duration_ms) / 1000.0 if duration_ms is not None else None),
            meta={"title": header.get("name")},
            raw=bubble,
        )

    @staticmethod
    def _map_session(row: sqlite3.Row, db_path: str) -> Optional[Record]:
        try:
            header = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            header = {}
        if not isinstance(header, dict):
            header = {}

        workspace = (
            (header.get("workspaceIdentifier") or {}).get("uri") or {}
        ).get("fsPath")
        created = _cursor_timestamp(row["createdAt"])
        updated = _cursor_timestamp(row["lastUpdatedAt"])
        duration: Optional[float] = None
        if created is not None and updated is not None:
            duration = (updated - created).total_seconds()

        session_id = str(row["composerId"])
        return SessionRecord(
            tool=CursorSource.name,
            session_id=session_id,
            record_id=session_id,
            timestamp=created,
            end_timestamp=updated,
            kind="session",
            role="session",
            rec_type="session",
            subtype=header.get("unifiedMode"),
            content=str(header.get("name") or header.get("subtitle") or ""),
            path=db_path,
            cwd=workspace,
            project=workspace,
            model=header.get("modelType"),
            record_count=row["record_count"],
            duration=duration,
            meta={
                "archived": bool(row["isArchived"]),
                "subagent": bool(row["isSubagent"]),
            },
            raw=header,
        )
