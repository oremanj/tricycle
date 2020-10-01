import pytest  # type: ignore
import itertools
import trio
import trio.testing
from .. import RWLock
from typing import List, Optional
from trio_typing import TaskStatus


async def test_rwlock(autojump_clock: trio.testing.MockClock) -> None:
    lock = RWLock()
    assert not lock.locked()

    lock.acquire_read_nowait()
    assert lock.locked() == "read"

    with pytest.raises(RuntimeError):
        lock.acquire_read_nowait()
    with pytest.raises(RuntimeError):
        lock.acquire_write_nowait()
    lock.release()
    with pytest.raises(RuntimeError):
        lock.release()

    with trio.testing.assert_checkpoints():
        await lock.acquire_write()
    assert lock.locked() == "write"
    with pytest.raises(RuntimeError):
        await lock.acquire_read()
    with pytest.raises(RuntimeError):
        await lock.acquire_write()
    lock.release()

    async with lock.read_locked():
        assert lock.locked() == "read"

    async with lock.write_locked():
        assert lock.locked() == "write"

    start_order = itertools.count()
    acquire_times: List[Optional[float]] = [None] * 10

    async def holder_task(
        for_write: bool, task_status: TaskStatus[trio.lowlevel.Task]
    ) -> None:
        my_slot = next(start_order)
        repr(lock)  # smoke test
        task_status.started(trio.lowlevel.current_task())
        await lock.acquire(for_write=for_write)
        acquire_times[my_slot] = trio.current_time()
        try:
            await trio.sleep(1)
        finally:
            lock.release()

    async with trio.open_nursery() as nursery:
        t0 = await nursery.start(holder_task, True)
        t1a = await nursery.start(holder_task, False)
        t1b = await nursery.start(holder_task, False)
        t1c = await nursery.start(holder_task, False)
        await nursery.start(holder_task, True)  # t2
        await nursery.start(holder_task, False)  # t3a
        await nursery.start(holder_task, False)  # t3b
        await nursery.start(holder_task, True)  # t4
        await nursery.start(holder_task, True)  # t5
        t6 = await nursery.start(holder_task, False)

        await trio.sleep(0.5)
        assert "write-locked" in repr(lock)
        assert lock.statistics().__dict__ == {
            "locked": "write",
            "readers": frozenset(),
            "writer": t0,
            "readers_waiting": 6,
            "writers_waiting": 3,
        }
        with pytest.raises(RuntimeError):
            lock.release()
        with pytest.raises(trio.WouldBlock):
            lock.acquire_read_nowait()
        with pytest.raises(trio.WouldBlock):
            lock.acquire_write_nowait()

        await trio.sleep(1)
        assert "read-locked" in repr(lock)
        assert lock.statistics().__dict__ == {
            "locked": "read",
            "readers": frozenset([t1a, t1b, t1c]),
            "writer": None,
            "readers_waiting": 3,
            "writers_waiting": 3,
        }
        with pytest.raises(RuntimeError):
            lock.release()
        with pytest.raises(trio.WouldBlock):
            # even in read state, can't acquire for read if writers are waiting
            lock.acquire_read_nowait()
        with pytest.raises(trio.WouldBlock):
            lock.acquire_write_nowait()

        await trio.sleep(5)
        assert "read-locked" in repr(lock)
        assert lock.statistics().__dict__ == {
            "locked": "read",
            "readers": frozenset([t6]),
            "writer": None,
            "readers_waiting": 0,
            "writers_waiting": 0,
        }
        lock.acquire_read_nowait()
        lock.release()
        with pytest.raises(trio.WouldBlock):
            lock.acquire_write_nowait()

    assert acquire_times == pytest.approx([0, 1, 1, 1, 2, 3, 3, 4, 5, 6])

    # test cancellation
    start_order = itertools.count()
    async with trio.open_nursery() as nursery:
        await nursery.start(holder_task, True)
        await nursery.start(holder_task, True)
        await nursery.start(holder_task, False)
        await nursery.start(holder_task, False)
        await nursery.start(holder_task, False)
        await nursery.start(holder_task, True)
        await nursery.start(holder_task, False)
        await nursery.start(holder_task, False)
        await nursery.start(holder_task, True)
        await nursery.start(holder_task, True)
        await nursery.start(holder_task, False)

        await trio.sleep(0.5)
        nursery.cancel_scope.cancel()

    assert nursery.cancel_scope.cancelled_caught
    assert trio.current_time() == pytest.approx(7.5)
    assert "unlocked" in repr(lock)
    assert lock.statistics().__dict__ == {
        "locked": "",
        "readers": frozenset(),
        "writer": None,
        "readers_waiting": 0,
        "writers_waiting": 0,
    }


async def test_read_biased(autojump_clock: trio.testing.MockClock) -> None:
    lock = RWLock(read_biased=True)
    assert "read-biased" in repr(lock)
    assert lock.read_biased

    async def holder_task(
        for_write: bool, task_status: TaskStatus[trio.lowlevel.Task]
    ) -> None:
        task_status.started(trio.lowlevel.current_task())
        await lock.acquire(for_write=for_write)
        try:
            await trio.sleep(1)
        finally:
            lock.release()

    async with trio.open_nursery() as nursery:
        t1a = await nursery.start(holder_task, False)
        t1b = await nursery.start(holder_task, False)
        t2 = await nursery.start(holder_task, True)
        t1c = await nursery.start(holder_task, False)

        # Reader (t1c) that arrives after the writer (t2) can get the
        # lock immediately, before the writer does
        await trio.sleep(0.5)
        assert lock.statistics().readers == frozenset([t1a, t1b, t1c])
        assert lock.statistics().writer is None

        await trio.sleep(1)
        assert lock.statistics().readers == frozenset()
        assert lock.statistics().writer is t2

        # If an additional writer gets in line for a writer-held lock
        # before any readers do, they get it before readers that come later
        # (i.e., the bias towards readers is "weak" -- "strong" would wake
        # up all readers when any writer released).
        t3 = await nursery.start(holder_task, True)
        t4a = await nursery.start(holder_task, False)
        t5 = await nursery.start(holder_task, True)
        t4b = await nursery.start(holder_task, False)

        await trio.sleep(1)
        assert lock.statistics().readers == frozenset()
        assert lock.statistics().writer is t3

        await trio.sleep(1)
        assert lock.statistics().readers == frozenset([t4a, t4b])
        assert lock.statistics().writer is None

        await trio.sleep(1)
        assert lock.statistics().readers == frozenset()
        assert lock.statistics().writer is t5

        # Read-bias can be turned on and off dynamically
        lock.read_biased = False
        assert not lock.read_biased
        t6 = await nursery.start(holder_task, False)
        t7 = await nursery.start(holder_task, True)
        t8 = await nursery.start(holder_task, False)

        # Now reader t8 has to wait because writer t7 arrived first,
        # even though the lock is held by reader t6
        await trio.sleep(1)
        assert lock.statistics().readers == frozenset([t6])
        assert lock.statistics().writer is None

        # If we turn on read-bias again, t8 immediately gets the lock
        lock.read_biased = True
        assert lock.statistics().readers == frozenset([t6, t8])
        assert lock.statistics().writer is None

        await trio.sleep(0.75)
        assert lock.statistics().readers == frozenset([t8])
        assert lock.statistics().writer is None

        await trio.sleep(0.75)
        assert lock.statistics().readers == frozenset()
        assert lock.statistics().writer is t7
