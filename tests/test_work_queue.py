import threading
import time

from app.work_queue import WorkQueue


def test_tasks_run_in_order_on_a_single_thread():
    queue = WorkQueue("test", capacity=10)
    seen = []

    for index in range(5):
        queue.submit(lambda index=index: seen.append((index, threading.current_thread().name)))
    queue.wait_idle()

    assert [index for index, _ in seen] == [0, 1, 2, 3, 4]
    assert {name for _, name in seen} == {"test-0"}


def test_several_workers_run_tasks_at_the_same_time():
    queue = WorkQueue("test", capacity=10, workers=4)
    running = []
    peak = []
    guard = threading.Lock()

    def slow() -> None:
        with guard:
            running.append(1)
            peak.append(len(running))
        time.sleep(0.1)
        with guard:
            running.pop()

    start = time.perf_counter()
    for _ in range(4):
        queue.submit(slow)
    queue.wait_idle()

    assert max(peak) == 4
    assert time.perf_counter() - start < 0.35


def test_full_queue_refuses_the_task():
    release = threading.Event()
    started = threading.Event()
    queue = WorkQueue("test", capacity=1)

    def blocking() -> None:
        started.set()
        release.wait()

    assert queue.submit(blocking)
    started.wait()
    assert queue.submit(lambda: None)
    assert queue.submit(lambda: None) is False
    release.set()
    queue.wait_idle()


def test_a_failing_task_does_not_stop_the_queue():
    queue = WorkQueue("test", capacity=10)
    seen = []

    def failing() -> None:
        raise RuntimeError("falhou")

    queue.submit(failing)
    queue.submit(lambda: seen.append("depois"))
    queue.wait_idle()

    assert seen == ["depois"]
