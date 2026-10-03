import threading
import time

from app.jobs import JobRunner


def test_duplicate_call_is_ignored_while_running():
    runner = JobRunner()
    started, release = threading.Event(), threading.Event()
    runs = []

    def slow():
        runs.append("run")
        started.set()
        release.wait(timeout=5)

    first = threading.Thread(target=runner.run_exclusive, args=("ingest", slow))
    first.start()
    assert started.wait(timeout=5)

    runner.run_exclusive("ingest", lambda: runs.append("duplicate"))
    release.set()
    first.join()

    assert runs == ["run"]


def test_jobs_in_the_same_group_run_one_at_a_time():
    runner = JobRunner()
    active, peak = [0], [0]
    guard = threading.Lock()

    def work():
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with guard:
            active[0] -= 1

    threads = [
        threading.Thread(
            target=runner.run_exclusive, args=(name, work), kwargs={"serialize_with": "llm"}
        )
        for name in ("personas", "translations")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak[0] == 1


def test_different_groups_may_overlap():
    runner = JobRunner()
    barrier = threading.Barrier(2, timeout=5)

    threads = [
        threading.Thread(target=runner.run_exclusive, args=(name, barrier.wait))
        for name in ("ingest", "purge")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not barrier.broken
