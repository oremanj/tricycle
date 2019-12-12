import pytest  # type: ignore
from typing import Any
from trio_typing import TaskStatus

import trio
import trio.testing
from .. import open_service_nursery


async def test_basic(autojump_clock: trio.testing.MockClock) -> None:
    record = []
    async with open_service_nursery() as nursery:

        @nursery.start_soon
        async def background_task() -> None:
            try:
                await trio.sleep_forever()
            finally:
                record.append("background_task exiting")

        (task,) = nursery.child_tasks
        assert "background_task" in task.name

        nursery.cancel_scope.cancel()
        with trio.CancelScope(shield=True):
            await trio.sleep(1)
        record.append("body exiting")
        await trio.sleep(0)
        pytest.fail("should've been cancelled")  # pragma: no cover

    assert nursery.cancel_scope.cancelled_caught
    assert record == ["body exiting", "background_task exiting"]


async def test_start(autojump_clock: trio.testing.MockClock) -> None:
    record = []

    async def sleep_then_start(val: int, *, task_status: TaskStatus[int]) -> None:
        await trio.sleep(1)
        task_status.started(val)
        try:
            await trio.sleep(10)
            record.append("background task finished")  # pragma: no cover
        finally:
            record.append("background task exiting")

    async def shielded_sleep_then_start(*, task_status: TaskStatus[None]) -> None:
        with trio.CancelScope(shield=True):
            await trio.sleep(1)
        task_status.started()
        await trio.sleep(10)

    async with open_service_nursery() as nursery:
        # Child can be cancelled normally while it's starting
        with trio.move_on_after(0.5) as scope:
            await nursery.start(sleep_then_start, 1)
        assert scope.cancelled_caught
        assert not nursery.child_tasks

        # If started() is the first thing to notice a cancellation, the task
        # stays in the old nursery and remains unshielded
        with trio.move_on_after(0.5) as scope:
            await nursery.start(shielded_sleep_then_start)
        assert scope.cancelled_caught
        assert not nursery.child_tasks

        assert trio.current_time() == 1.5

        # Otherwise, once started() is called the child is shielded until
        # the 'async with' block exits.
        assert 42 == await nursery.start(sleep_then_start, 42)
        assert trio.current_time() == 2.5

        nursery.cancel_scope.cancel()
        with trio.CancelScope(shield=True):
            await trio.sleep(1)
        record.append("parent task finished")

    assert trio.current_time() == 3.5
    assert record == ["parent task finished", "background task exiting"]


async def test_problems() -> None:
    async with open_service_nursery() as nursery:
        with pytest.raises(TypeError) as info:
            nursery.start_soon(trio.sleep)
        assert "missing 1 required positional argument" in str(info.value)

        with pytest.raises(TypeError) as info:
            nursery.start_soon(trio.sleep(1))  # type: ignore
        assert "Trio was expecting an async function" in str(info.value)

        with pytest.raises(TypeError) as info:
            nursery.start_soon(int, 42)  # type: ignore
        assert "appears to be synchronous" in str(info.value)

        first_call = True

        def evil() -> Any:
            nonlocal first_call
            if first_call:
                first_call = False
                return 42
            else:
                return trio.sleep(0)

        with pytest.raises(trio.TrioInternalError) as info:
            nursery.start_soon(evil)
        assert "all bets are off at this point" in str(info.value)
