import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from .workqueue import WorkQueue, get_workqueue


class FileResource:
    """Centralized, seekable, thread-safe access to a single JSONL file.

    The resource keeps one or more lightweight caches:

    - ``_count``: a line count, built by reading once without storing offsets.
    - ``_offsets`` and ``_objects``: per-line byte offsets and parsed objects,
      built lazily when indexed access or full iteration is requested.
    - ``_records``: mapped records, cached when a source asks for them.

    If the file changes (mtime or size), all caches are discarded and rebuilt
    on the next access. All cache mutations are protected by ``_lock``.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._count: Optional[int] = None
        self._offsets: List[int] = []
        self._objects: List[Optional[Dict[str, Any]]] = []
        self._records: List[Any] = []
        self._records_mapper_id: Optional[int] = None
        self._records_dirty = True
        self._mtime: Optional[float] = None
        self._size: Optional[int] = None
        self._set_stat()

    def _set_stat(self) -> None:
        try:
            st = self.path.stat()
            self._mtime = st.st_mtime
            self._size = st.st_size
        except (OSError, FileNotFoundError):
            self._mtime = None
            self._size = None

    def _is_dirty(self) -> bool:
        try:
            st = self.path.stat()
        except (OSError, FileNotFoundError):
            return True
        return st.st_mtime != self._mtime or st.st_size != self._size

    def _maybe_refresh(self) -> None:
        if not self._is_dirty():
            return
        with self._lock:
            if not self._is_dirty():
                return
            self._count = None
            self._offsets = []
            self._objects = []
            self._records = []
            self._records_dirty = True
            self._records_mapper_id = None
            self._set_stat()

    def count(self) -> int:
        """Return the number of non-empty JSONL lines (fast; no offsets stored)."""
        self._maybe_refresh()
        if self._count is None:
            n = 0
            try:
                with self.path.open("rb") as f:
                    for line in f:
                        if line.strip():
                            n += 1
            except (OSError, FileNotFoundError):
                pass
            with self._lock:
                self._count = n
        return self._count

    def _ensure_offsets(self) -> None:
        self._maybe_refresh()
        if self._offsets:
            return
        offsets: List[int] = []
        try:
            with self.path.open("rb") as f:
                offset = 0
                for line in f:
                    if line.strip():
                        offsets.append(offset)
                    offset += len(line)
        except (OSError, FileNotFoundError):
            pass
        with self._lock:
            self._offsets = offsets
            self._objects = [None] * len(offsets)
            if self._count is None:
                self._count = len(offsets)

    def _read_line(self, idx: int) -> bytes:
        self._ensure_offsets()
        if idx < 0 or idx >= len(self._offsets):
            raise IndexError(f"line index {idx} out of range")
        with self.path.open("rb") as f:
            f.seek(self._offsets[idx])
            return f.readline()

    def object(self, idx: int) -> Optional[Dict[str, Any]]:
        """Return the parsed JSON object at line index ``idx``."""
        self._ensure_offsets()
        if idx < 0 or idx >= len(self._objects):
            raise IndexError(f"object index {idx} out of range")
        obj = self._objects[idx]
        if obj is None:
            line = self._read_line(idx)
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                obj = None
            with self._lock:
                self._objects[idx] = obj
        return obj

    def first_object(
        self,
        predicate: Optional[Callable[[Optional[Dict[str, Any]]], bool]] = None,
    ) -> Optional[Tuple[int, Optional[Dict[str, Any]]]]:
        """Return the first matching object and its index.

        If offsets are already known, use them. Otherwise, stream the file and
        avoid building the offset table so lightweight callers (e.g. ``ls``) do
        not pay the cost of full indexing.
        """
        self._maybe_refresh()
        if self._offsets:
            for i in range(len(self._offsets)):
                obj = self.object(i)
                if predicate is None or predicate(obj):
                    return i, obj
            return None

        idx = 0
        try:
            with self.path.open("rb") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        obj = None
                    if predicate is None or predicate(obj):
                        return idx, obj
                    idx += 1
        except (OSError, FileNotFoundError):
            pass
        return None

    def last_object(
        self,
        predicate: Optional[Callable[[Optional[Dict[str, Any]]], bool]] = None,
    ) -> Optional[Tuple[int, Optional[Dict[str, Any]]]]:
        """Return the last matching object and its index."""
        self._ensure_offsets()
        for i in range(len(self._offsets) - 1, -1, -1):
            obj = self.object(i)
            if predicate is None or predicate(obj):
                return i, obj
        return None

    def iter_objects(
        self,
        start: int = 0,
        stop: Optional[int] = None,
    ) -> Iterator[Tuple[int, Optional[Dict[str, Any]]]]:
        """Iterate from ``start`` to ``stop`` (exclusive)."""
        self._ensure_offsets()
        stop = stop if stop is not None else len(self._offsets)
        with self.path.open("rb") as f:
            for idx in range(start, stop):
                if f.tell() != self._offsets[idx]:
                    f.seek(self._offsets[idx])
                line = f.readline()
                obj = self._objects[idx]
                if obj is None:
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        obj = None
                    with self._lock:
                        self._objects[idx] = obj
                yield idx, obj

    def iter_records(
        self,
        mapper: Callable[[int, Optional[Dict[str, Any]]], Optional[Any]],
    ) -> Iterator[Any]:
        """Stream records from the file without building the offset index."""
        self._maybe_refresh()
        idx = 0
        try:
            with self.path.open("rb") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        obj = None
                    rec = mapper(idx, obj)
                    if rec is not None:
                        yield rec
                    idx += 1
        except (OSError, FileNotFoundError):
            return

    def records(
        self,
        mapper: Callable[[int, Optional[Dict[str, Any]]], Optional[Any]],
    ) -> List[Any]:
        """Return all mapped records, caching when the file and mapper are stable."""
        self._ensure_offsets()
        mapper_id = id(mapper)
        if self._records_dirty or self._records_mapper_id != mapper_id:
            self._records = [rec for rec in self.iter_records(mapper) if rec is not None]
            with self._lock:
                self._records_mapper_id = mapper_id
                self._records_dirty = False
        return self._records


class ResourceManager:
    """Owns the lifetime of ``FileResource`` objects and a shared workqueue."""

    def __init__(self, queue: Optional[WorkQueue] = None):
        self._resources: Dict[Path, FileResource] = {}
        self._resources_lock = threading.Lock()
        self._queue = queue or get_workqueue()

    @property
    def queue(self) -> WorkQueue:
        return self._queue

    def open(self, path: Path) -> FileResource:
        """Return a ``FileResource``, refreshing it if the file changed."""
        path = Path(path)
        with self._resources_lock:
            existing = self._resources.get(path)
            if existing is not None and not existing._is_dirty():
                return existing
            resource = FileResource(path)
            self._resources[path] = resource
            return resource

    def map(
        self,
        fn: Callable[..., Any],
        iterable: Iterable[Any],
        *,
        chunksize: int = 1,
    ) -> Iterator[Any]:
        """Map ``fn`` over ``iterable`` using the shared workqueue."""
        return self._queue.map(fn, iterable, chunksize=chunksize)

    def submit(self, *args: Any, **kwargs: Any) -> Any:
        return self._queue.submit(*args, **kwargs)

    def clear(self) -> None:
        with self._resources_lock:
            self._resources.clear()


_MANAGER: Optional[ResourceManager] = None
_MANAGER_LOCK = threading.Lock()


def get_resource(path: Path) -> FileResource:
    return get_resource_manager().open(path)


def get_resource_manager() -> ResourceManager:
    """Return the process-global ``ResourceManager``."""
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = ResourceManager()
    return _MANAGER


def clear_resources() -> None:
    manager = get_resource_manager()
    manager.clear()
