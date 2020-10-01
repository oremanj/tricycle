import pytest  # type: ignore

import trio
import trio.testing
from .. import MultiCancelScope


async def test_basic(autojump_clock: trio.testing.MockClock) -> None:
    parent = MultiCancelScope()
    finish_order = []

    async def cancel_child_before_entering() -> None:
        child = parent.open_child()
        assert not child.cancel_called
        child.cancel()
        assert child.cancel_called
        assert not child.cancelled_caught
        await trio.sleep(0.2)
        with child:
            assert not child.cancelled_caught
            await trio.sleep(1)
        assert child.cancelled_caught
        finish_order.append("cancel_child_before_entering")

    async def cancel_child_after_entering() -> None:
        with parent.open_child() as child:
            await trio.sleep(0.3)
            child.cancel()
            await trio.sleep(1)
        assert child.cancel_called
        assert child.cancelled_caught
        finish_order.append("cancel_child_after_entering")

    async def cancel_child_via_local_deadline() -> None:
        child = parent.open_child()
        child.deadline = trio.current_time() + 0.4
        deadline_before_entering = child.deadline
        with child:
            assert child.deadline == deadline_before_entering
            await trio.sleep(1)
        assert child.cancel_called
        assert child.cancelled_caught
        finish_order.append("cancel_child_via_local_deadline")

    async def cancel_child_via_local_deadline_2() -> None:
        child = parent.open_child()
        child.deadline = trio.current_time() + 1.0
        with child:
            child.deadline -= 0.9
            await trio.sleep(1)
        assert child.cancel_called
        assert child.cancelled_caught
        finish_order.append("cancel_child_via_local_deadline_2")

    async def cancel_parent_before_entering() -> None:
        child = parent.open_child()
        await trio.sleep(0.6)
        assert child.cancel_called
        assert not child.cancelled_caught
        with child:
            await trio.sleep(1)
        assert child.cancelled_caught
        finish_order.append("cancel_parent_before_entering")

    async def cancel_parent_after_entering() -> None:
        with parent.open_child() as child:
            await trio.sleep(1)
        assert child.cancel_called
        assert child.cancelled_caught
        finish_order.append("cancel_parent_after_entering")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(cancel_child_before_entering)
        nursery.start_soon(cancel_child_after_entering)
        nursery.start_soon(cancel_child_via_local_deadline)
        nursery.start_soon(cancel_child_via_local_deadline_2)
        nursery.start_soon(cancel_parent_before_entering)
        nursery.start_soon(cancel_parent_after_entering)
        await trio.sleep(0.5)
        assert "MultiCancelScope cancelled" not in repr(parent)
        assert not parent.cancel_called
        parent.cancel()
        assert parent.cancel_called
        assert "MultiCancelScope cancelled" in repr(parent)
        parent.cancel()
        await trio.sleep(0.2)

        nursery.cancel_scope.deadline = trio.current_time() + 0.1
        with parent.open_child() as child:
            child.deadline = nursery.cancel_scope.deadline
            assert child.cancel_called
            assert not child.cancelled_caught
            await trio.sleep_forever()
        assert child.cancelled_caught
        finish_order.append("cancel_parent_before_creating")

    assert not nursery.cancel_scope.cancelled_caught
    assert finish_order == [
        "cancel_child_via_local_deadline_2",  # t+0.1
        "cancel_child_before_entering",  # t+0.2
        "cancel_child_after_entering",  # t+0.3
        "cancel_child_via_local_deadline",  # t+0.4
        "cancel_parent_after_entering",  # t+0.5
        "cancel_parent_before_entering",  # t+0.6
        "cancel_parent_before_creating",  # t+0.7
    ]


async def test_shielding(autojump_clock: trio.testing.MockClock) -> None:
    parent = MultiCancelScope()
    finish_order = []

    async def shield_child_on_creation() -> None:
        try:
            with parent.open_child(shield=True):
                await trio.sleep(1)
            assert False  # pragma: no cover
        finally:
            finish_order.append("shield_child_on_creation")

    async def shield_child_before_entering() -> None:
        child = parent.open_child()
        child.shield = True
        try:
            with child:
                await trio.sleep(1)
            assert False  # pragma: no cover
        finally:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.1)
            finish_order.append("shield_child_before_entering")

    async def shield_child_after_entering() -> None:
        try:
            with parent.open_child() as child:
                child.shield = True
                await trio.sleep(1)
            assert False  # pragma: no cover
        finally:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.2)
            finish_order.append("shield_child_after_entering")

    async def shield_child_when_parent_shielded() -> None:
        try:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.3)
            with parent.open_child():
                await trio.sleep(1)
        finally:
            with trio.CancelScope(shield=True):
                await trio.sleep(0.3)
            finish_order.append("shield_child_when_parent_shielded")

    async def shield_child_after_parent_unshielded() -> None:
        with parent.open_child(shield=True) as child:
            this_task = trio.lowlevel.current_task()

            def abort_fn(_):  # type: ignore
                trio.lowlevel.reschedule(this_task)
                return trio.lowlevel.Abort.FAILED

            await trio.lowlevel.wait_task_rescheduled(abort_fn)
            child.shield = True
            await trio.sleep(0.5)
        assert not child.cancelled_caught
        finish_order.append("shield_child_after_parent_unshielded")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(shield_child_on_creation)
        nursery.start_soon(shield_child_before_entering)
        nursery.start_soon(shield_child_after_entering)
        nursery.start_soon(shield_child_when_parent_shielded)
        nursery.start_soon(shield_child_after_parent_unshielded)

        nursery.cancel_scope.cancel()
        assert parent.shield == False
        with trio.CancelScope(shield=True):
            await trio.sleep(0.2)
        assert "MultiCancelScope shielded" not in repr(parent)
        parent.shield = True
        assert "MultiCancelScope shielded" in repr(parent)
        assert parent.shield == True
        with trio.CancelScope(shield=True):
            await trio.sleep(0.2)
        parent.shield = False

    assert finish_order == [
        "shield_child_on_creation",  # t+0.4
        "shield_child_before_entering",  # t+0.5
        "shield_child_after_entering",  # t+0.6
        "shield_child_when_parent_shielded",  # t+0.7
        "shield_child_after_parent_unshielded",  # t+0.8
    ]
