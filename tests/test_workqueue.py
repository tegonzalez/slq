import os
import time

import pytest

from slq.workqueue import WorkQueue, get_workqueue, set_workqueue


def teardown_function():
    q = get_workqueue()
    q.shutdown()
    set_workqueue(WorkQueue())


def test_default_workers_is_nproc_minus_one():
    q = get_workqueue()
    cpus = os.cpu_count() or 1
    assert q.max_workers == max(1, cpus - 1)


def test_custom_workers():
    q = WorkQueue(max_workers=2)
    assert q.max_workers == 2
    q.shutdown()


def test_map_preserves_order():
    q = WorkQueue(max_workers=2)
    results = list(q.map(lambda x: x * 2, range(5)))
    assert results == [0, 2, 4, 6, 8]
    q.shutdown()


def test_starts_with_one_worker():
    q = WorkQueue(max_workers=4)
    # Give the scheduler a moment to start.
    time.sleep(0.02)
    assert len(q._workers) == 1
    q.shutdown()


def test_single_fast_task_stays_one_worker():
    q = WorkQueue(max_workers=4, quantum=0.1)
    results = list(q.map(lambda x: x, [1, 2, 3]))
    assert results == [1, 2, 3]
    time.sleep(0.02)
    assert len(q._workers) == 1
    q.shutdown()


def test_slow_tasks_spawn_up_to_max():
    q = WorkQueue(max_workers=3, quantum=0.005)

    def slow(x):
        time.sleep(0.05)
        return x

    futures = [q.submit(slow, i) for i in range(3)]
    # Give the scheduler time to spawn more workers.
    time.sleep(0.03)
    assert len(q._workers) == 3
    for i, f in enumerate(futures):
        assert f.result() == i
    q.shutdown()


def test_max_workers_is_respected():
    q = WorkQueue(max_workers=2, quantum=0.001)

    def slow(x):
        time.sleep(0.05)
        return x

    futures = [q.submit(slow, i) for i in range(10)]
    time.sleep(0.05)
    assert len(q._workers) == 2
    for i, f in enumerate(futures):
        assert f.result() == i
    q.shutdown()


def test_map_stops_on_shutdown():
    q = WorkQueue(max_workers=2)

    def slow(x):
        time.sleep(10)
        return x

    def stop_later():
        time.sleep(0.05)
        q.shutdown()

    import threading
    threading.Thread(target=stop_later, daemon=True).start()
    start = time.monotonic()
    results = list(q.map(slow, [1, 2, 3]))
    elapsed = time.monotonic() - start
    assert results == []
    assert elapsed < 0.5
