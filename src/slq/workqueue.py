import collections
import os
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable, Iterable, Iterator, Optional


class _WorkItem:
    __slots__ = ("future", "fn", "args", "kwargs", "submit_time")

    def __init__(self, fn: Callable[..., Any], args: Any, kwargs: Any) -> None:
        self.future: Future[Any] = Future()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.submit_time = time.monotonic()


class _Worker:
    """A worker thread that waits for tasks assigned by the scheduler."""

    def __init__(self, queue: "WorkQueue") -> None:
        self.queue = queue
        self.task: Optional[_WorkItem] = None
        self._stop = False
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="slq-wq-worker",
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while True:
            with self.queue._cond:
                if self._stop:
                    return
                self.queue._idle_workers.add(self)
                self.queue._cond.notify_all()
                while self.task is None and not self._stop:
                    self.queue._cond.wait()
                if self._stop:
                    self.queue._idle_workers.discard(self)
                    return
                task = self.task
                self.task = None
                self.queue._idle_workers.discard(self)
            try:
                result = task.fn(*task.args, **task.kwargs)
                task.future.set_result(result)
            except BaseException as exc:
                task.future.set_exception(exc)

    def shutdown(self) -> None:
        with self.queue._cond:
            self._stop = True
            self.queue._cond.notify_all()
        self._thread.join()


class WorkQueue:
    """A dynamic, job-stealing workqueue.

    The queue starts with one worker. A scheduler thread assigns tasks to idle
    workers. If a task has been waiting for longer than ``quantum`` seconds and
    no worker has become idle, a new worker is spawned up to ``max_workers``.
    Workers are never reaped until the queue is shut down.

    The default ``max_workers`` is ``max(1, nproc - 1)``; the default ``quantum``
    is 10 milliseconds. ``max_workers`` can also be set via the ``SLQ_WORKERS``
    environment variable or passed explicitly.
    """

    DEFAULT_QUANTUM = 0.01

    def __init__(
        self,
        max_workers: Optional[int] = None,
        quantum: Optional[float] = None,
    ):
        if max_workers is None:
            env = os.environ.get("SLQ_WORKERS")
            if env and env.isdigit():
                max_workers = max(1, int(env))
            else:
                cpus = os.cpu_count() or 1
                max_workers = max(1, cpus - 1)
        if quantum is None:
            quantum = self.DEFAULT_QUANTUM
        self._max_workers = max_workers
        self._quantum = max(0.0, float(quantum))
        self._queue: collections.deque[_WorkItem] = collections.deque()
        self._workers: list[_Worker] = []
        self._idle_workers: set[_Worker] = set()
        self._cond = threading.Condition()
        self._shutdown = False
        self._scheduler = threading.Thread(
            target=self._schedule,
            daemon=True,
            name="slq-wq-scheduler",
        )
        self._scheduler.start()
        self._spawn_idle_worker()

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def quantum(self) -> float:
        return self._quantum

    def _spawn_idle_worker(self) -> None:
        worker = _Worker(self)
        self._workers.append(worker)
        worker.start()

    def _spawn_worker(self, item: _WorkItem) -> _Worker:
        worker = _Worker(self)
        worker.task = item
        self._workers.append(worker)
        worker.start()
        return worker

    def _schedule(self) -> None:
        while True:
            with self._cond:
                if self._shutdown:
                    return
                if not self._queue:
                    self._cond.wait()
                    continue

                # Assign to an idle worker if one exists.
                if self._idle_workers:
                    worker = self._idle_workers.pop()
                    worker.task = self._queue.popleft()
                    self._cond.notify_all()
                    continue

                # If we are at max workers, wait for one to become idle.
                if len(self._workers) >= self._max_workers:
                    self._cond.wait()
                    continue

                # If the oldest task has waited at least one quantum, spawn.
                oldest = self._queue[0]
                elapsed = time.monotonic() - oldest.submit_time
                if elapsed >= self._quantum:
                    self._spawn_worker(oldest)
                    self._queue.popleft()
                    continue

                # Otherwise wait for either an idle worker or the quantum.
                self._cond.wait(timeout=self._quantum - elapsed)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        """Submit a job and return a ``Future``."""
        item = _WorkItem(fn, args, kwargs)
        with self._cond:
            self._queue.append(item)
            self._cond.notify_all()
        return item.future

    def map(
        self,
        fn: Callable[..., Any],
        iterable: Iterable[Any],
        *,
        chunksize: int = 1,
    ) -> Iterator[Any]:
        """Apply ``fn`` to ``iterable`` in parallel, preserving order."""
        # ``chunksize`` is accepted for compatibility with ``ThreadPoolExecutor``;
        # the scheduler treats each item as a separate task.
        items = list(iterable)
        futures = [self.submit(fn, item) for item in items]
        for future in futures:
            # Use a short timeout so the main thread remains responsive to
            # signals such as SIGINT while waiting for long-running workers.
            while True:
                try:
                    yield future.result(timeout=0.1)
                    break
                except TimeoutError:
                    if self._shutdown:
                        return

    def shutdown(self, wait: bool = True) -> None:
        """Stop the scheduler and all workers."""
        with self._cond:
            self._shutdown = True
            self._cond.notify_all()
        if wait:
            self._scheduler.join()
            for worker in list(self._workers):
                worker.shutdown()

    def __del__(self) -> None:
        try:
            self.shutdown(wait=False)
        except Exception:
            pass


_QUEUE: Optional[WorkQueue] = None
_QUEUE_LOCK = threading.Lock()


def get_workqueue(
    max_workers: Optional[int] = None,
    quantum: Optional[float] = None,
) -> WorkQueue:
    """Return the process-global workqueue, creating it on first use."""
    global _QUEUE
    if _QUEUE is None:
        with _QUEUE_LOCK:
            if _QUEUE is None:
                _QUEUE = WorkQueue(max_workers=max_workers, quantum=quantum)
    return _QUEUE


def set_workqueue(queue: WorkQueue) -> None:
    """Replace the global workqueue (mainly for tests)."""
    global _QUEUE
    with _QUEUE_LOCK:
        _QUEUE = queue
