import pytest
import trio
import trio.testing
from functools import partial
from typing import Optional, Any, cast

from .. import TreeVar, TreeVarToken


async def test_treevar() -> None:
    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[Optional[int]]("tv2", default=None)
    tv3 = TreeVar("tv3", default=-1)
    assert tv1.name == "tv1"
    assert "TreeVar name='tv2'" in repr(tv2)

    with pytest.raises(LookupError):
        tv1.get()
    assert tv2.get() is None
    assert tv1.get(42) == 42
    assert tv2.get(42) == 42

    NOTHING = cast(int, object())

    async def should_be(val1: int, val2: int, new1: int = NOTHING) -> None:
        assert tv1.get(NOTHING) == val1
        assert tv2.get(NOTHING) == val2
        if new1 is not NOTHING:
            tv1.set(new1)

    tok1 = tv1.set(10)
    async with trio.open_nursery() as outer:
        tok2 = tv1.set(15)
        with tv2.being(20):
            assert tv2.get_in(trio.lowlevel.current_task()) == 20
            async with trio.open_nursery() as inner:
                tv1.reset(tok2)
                outer.start_soon(should_be, 10, NOTHING, 100)
                inner.start_soon(should_be, 15, 20, 200)
                await trio.testing.wait_all_tasks_blocked()
                assert tv1.get_in(trio.lowlevel.current_task()) == 10
                await should_be(10, 20, 300)
                assert tv1.get_in(inner) == 15
                assert tv1.get_in(outer) == 10
                assert tv1.get_in(trio.lowlevel.current_task()) == 300
                assert tv2.get_in(inner) == 20
                assert tv2.get_in(outer) is None
                assert tv2.get_in(trio.lowlevel.current_task()) == 20
                tv1.reset(tok1)
                await should_be(NOTHING, 20)
                assert tv1.get_in(inner) == 15
                assert tv1.get_in(outer) == 10
                with pytest.raises(LookupError):
                    assert tv1.get_in(trio.lowlevel.current_task())
                # Test get_in() needing to search a parent task but
                # finding no value there:
                tv3 = TreeVar("tv3", default=-1)
                assert tv3.get_in(outer) == -1
                assert tv3.get_in(outer, -42) == -42
        assert tv2.get() is None
        assert tv2.get_in(trio.lowlevel.current_task()) is None


def trivial_abort(_: object) -> trio.lowlevel.Abort:
    return trio.lowlevel.Abort.SUCCEEDED  # pragma: no cover


async def test_treevar_follows_eventual_parent() -> None:
    tv1 = TreeVar[str]("tv1")

    async def manage_target(task_status: trio.TaskStatus[trio.Nursery]) -> None:
        assert tv1.get() == "source nursery"
        with tv1.being("target nursery"):
            assert tv1.get() == "target nursery"
            async with trio.open_nursery() as target_nursery:
                with tv1.being("target nested child"):
                    assert tv1.get() == "target nested child"
                    task_status.started(target_nursery)
                    await trio.lowlevel.wait_task_rescheduled(trivial_abort)
                    assert tv1.get() == "target nested child"
                assert tv1.get() == "target nursery"
            assert tv1.get() == "target nursery"
        assert tv1.get() == "source nursery"

    async def verify(
        value: str, *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED
    ) -> None:
        assert tv1.get() == value
        task_status.started()
        assert tv1.get() == value

    with tv1.being("source nursery"):
        async with trio.open_nursery() as source_nursery:
            with tv1.being("source->target start call"):
                target_nursery = await source_nursery.start(manage_target)
            with tv1.being("verify task"):
                source_nursery.start_soon(verify, "source nursery")
                target_nursery.start_soon(verify, "target nursery")
                await source_nursery.start(verify, "source nursery")
                await target_nursery.start(verify, "target nursery")
            trio.lowlevel.reschedule(target_nursery.parent_task)


async def test_treevar_token_bound_to_task_that_obtained_it() -> None:
    tv1 = TreeVar[int]("tv1")
    token: Optional[TreeVarToken[int]] = None

    async def get_token() -> None:
        nonlocal token
        token = tv1.set(10)
        try:
            await trio.lowlevel.wait_task_rescheduled(trivial_abort)
        finally:
            tv1.reset(token)
            with pytest.raises(LookupError):
                tv1.get()
            with pytest.raises(LookupError):
                tv1.get_in(trio.lowlevel.current_task())

    async with trio.open_nursery() as nursery:
        nursery.start_soon(get_token)
        await trio.testing.wait_all_tasks_blocked()
        assert token is not None
        with pytest.raises(ValueError, match="different Context"):
            tv1.reset(token)
        assert tv1.get_in(list(nursery.child_tasks)[0]) == 10
        nursery.cancel_scope.cancel()


def test_treevar_outside_run() -> None:
    async def run_sync(fn: Any, *args: Any) -> Any:
        return fn(*args)

    tv1 = TreeVar("tv1", default=10)
    for operation in (
        tv1.get,
        partial(tv1.get, 20),
        partial(tv1.set, 30),
        lambda: tv1.reset(trio.run(run_sync, tv1.set, 10)),
        tv1.being(40).__enter__,
    ):
        with pytest.raises(RuntimeError, match="must be called from async context"):
            operation()  # type: ignore
