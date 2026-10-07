import threading
import time

from app.priority_lock import PriorityLock


def test_waiting_requests_go_by_priority_then_arrival():
    lock = PriorityLock()
    order = []
    holding = threading.Event()
    release = threading.Event()

    def first() -> None:
        with lock.hold(5):
            holding.set()
            release.wait()

    def waiter(name: str, priority: int) -> None:
        with lock.hold(priority):
            order.append(name)

    blocker = threading.Thread(target=first)
    blocker.start()
    holding.wait()
    waiters = []
    for name, priority in (("fonte", 2), ("afinidade", 1), ("chat-1", 0), ("chat-2", 0)):
        thread = threading.Thread(target=waiter, args=(name, priority))
        thread.start()
        waiters.append(thread)
        time.sleep(0.02)  # garante a ordem de chegada
    release.set()
    for thread in [blocker, *waiters]:
        thread.join()

    assert order == ["chat-1", "chat-2", "afinidade", "fonte"]


def test_only_one_holder_at_a_time():
    lock = PriorityLock()
    running = []
    peak = []

    def work(priority: int) -> None:
        with lock.hold(priority):
            running.append(1)
            peak.append(len(running))
            time.sleep(0.005)
            running.pop()

    threads = [threading.Thread(target=work, args=(i % 3,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max(peak) == 1
    assert len(peak) == 12


def test_the_lock_is_released_when_the_holder_fails():
    lock = PriorityLock()

    try:
        with lock.hold(0):
            raise RuntimeError("falhou")
    except RuntimeError:
        pass

    with lock.hold(0):
        pass
