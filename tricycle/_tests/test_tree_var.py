import pytest
import trio
import trio.testing
from functools import partial
from typing import Optional, Any, cast
from typing import NoReturn

from collections.abc import AsyncGenerator
import sys
import random
from trio._core._tests.test_asyncgen import step_outside_async_context
from threading import Thread
import time

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


def test_treevar_sync_context() -> None:
    async def run_sync(fn: Any, *args: Any) -> Any:
        return fn(*args)

    tv1 = TreeVar("tv1", default=10)
    for operation in (
        tv1.get,
        partial(tv1.get, 20),
        partial(tv1.set, 30),
        lambda: tv1.reset(tv1.set(10)),
        tv1.being(40).__enter__,
    ):
        operation()  # type: ignore

    diff_context_regex = r".*was created in a different Context"
    # Resetting the context var in sync context to the token set in async context should raise
    with pytest.raises(ValueError, match=diff_context_regex):
        tv1.reset(trio.run(run_sync, tv1.set, 10))

    tv2 = TreeVar("tv2", default=10)
    # Assert that being also works in sync context
    with tv2.being(30):
        assert tv2.get() == 30
    assert tv2.get() == 10

    def mix_async_and_sync() -> None:
        token_sync = tv2.set(15)
        assert tv2.get() == 15

        trio_task: trio.lowlevel.Task = None  # type: ignore[assignment]
        token_async: TreeVarToken[int] = None  # type: ignore[assignment]

        async def set_and_get() -> None:
            nonlocal trio_task
            nonlocal token_async
            # Assert that the new trio run picks up the
            # most-recently set value in the sync context
            assert tv2.get() == 15

            token_async = tv2.set(20)
            # Assert that setting in async context works
            assert tv2.get() == 20

            # Assert that resetting the context var in async context
            # to the token set in sync context raises
            with pytest.raises(ValueError, match=diff_context_regex):
                tv2.reset(token_sync)

            # Assert that resetting the context var in async context
            # to the token set in the async context works
            tv2.reset(token_async)
            assert tv2.get() == 15

            # Set it to another value again and make sure sync context
            # is not afffected
            tv2.set(20)
            trio_task = trio.lowlevel.current_task()

        trio.run(set_and_get)

        # Assert that getting the last value set inside the trio task works
        assert tv2.get_in(trio_task) == 20

        # Assert that the value is not affected by the trio's run
        assert tv2.get() == 15

        # Assert that resetting the token in the same context works
        tv2.reset(token_sync)
        assert tv2.get() == 10
        with pytest.raises(ValueError, match=diff_context_regex):
            tv2.reset(token_async)

    mix_async_and_sync()


def test_treevar_on_kernel_threads() -> None:
    #  val1 = for tv1
    #  val2 = for tv2
    #  _v1  = initial value
    #  _v2  = new value
    val1_v1 = random.randint(1, 10)
    val1_v2 = random.randint(1, 10)
    val2_v1 = random.randint(1, 10)
    val2_v2 = random.randint(1, 10)

    def thread_task() -> None:
        # Assert that first time getting value in a new kernel thread raises LookupError
        with pytest.raises(LookupError):
            tv1.get()
        with pytest.raises(LookupError):
            tv2.get()

        tv1.set(val1_v2)
        tv2.set(val2_v2)
        time.sleep(0.1)  # increase chance of context switching

        # Assert that the value is not mixed up between multiple kernel threads
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2

    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[int]("tv2")
    tv1.set(val1_v1)
    tv2.set(val2_v1)
    Thread(target=thread_task).start()
    Thread(target=thread_task).start()


def test_treevar_on_trio_threads() -> None:
    #  val1 = for tv1
    #  val2 = for tv2
    #  _v1  = initial value
    #  _v2  = new value
    #  _v3  = newer value
    val1_v1 = random.randint(1, 10)
    val1_v2 = random.randint(1, 10)
    val1_v3 = random.randint(1, 10)
    val2_v1 = random.randint(1, 10)
    val2_v2 = random.randint(1, 10)
    val2_v3 = random.randint(1, 10)

    def trio_thread_task() -> None:
        # Assert that the value is the value set at the point the trio task started the thread
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2

        tv1.set(val1_v3)
        tv2.set(val2_v3)
        time.sleep(0.1)  # increase chance of context switching

        # Assert that the value is the value set in this thread
        assert tv1.get() == val1_v3
        assert tv2.get() == val2_v3

    async def nursery_task() -> None:
        # Assert that the value is the value set before the nursery started the task
        assert tv1.get() == val1_v1
        assert tv2.get() == val2_v1

        # Set to a diff value
        tv1.set(val1_v2)
        tv2.set(val2_v2)

        await trio.to_thread.run_sync(trio_thread_task)
        await trio.sleep(0)

        # Assert that the value is the value set in this task before the thread was run
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2

    async def main() -> None:
        # Assert that the value is the value set when trio event loop started
        assert tv1.get() == val1_v1
        assert tv2.get() == val2_v1
        async with trio.open_nursery() as nursery:
            nursery.start_soon(nursery_task)
            nursery.start_soon(nursery_task)

    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[int]("tv2")
    tv1.set(val1_v1)
    tv2.set(val2_v1)
    trio.run(main)


def test_treevar_on_kernel_threads_with_trio_threads() -> None:
    #  val1 = for tv1
    #  val2 = for tv2
    #  _v1  = initial value
    #  _v2  = new value
    #  _v3  = newer value
    val1_v1 = random.randint(1, 10)
    val1_v2 = random.randint(1, 10)
    val1_v3 = random.randint(1, 10)
    val2_v1 = random.randint(1, 10)
    val2_v2 = random.randint(1, 10)
    val2_v3 = random.randint(1, 10)

    def trio_thread_task() -> None:
        # Assert that the value is the value set at the point the trio task started the thread
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2

        tv1.set(val1_v3)
        tv2.set(val2_v3)
        time.sleep(0.1)

        # Assert that the value is the value set in this thread
        assert tv1.get() == val1_v3
        assert tv2.get() == val2_v3

    async def main() -> None:
        # Assert that the value is the value set when trio event loop started
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2
        await trio.to_thread.run_sync(trio_thread_task)

    def thread_task() -> None:
        # Assert that first time getting value in a new kernel thread raises LookupError
        with pytest.raises(LookupError):
            tv1.get()
        with pytest.raises(LookupError):
            tv2.get()
        tv1.set(val1_v2)
        tv2.set(val2_v2)
        trio.run(main)

    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[int]("tv2")
    tv1.set(val1_v1)
    tv2.set(val2_v1)
    Thread(target=thread_task).start()
    Thread(target=thread_task).start()


def test_treevar_on_kernel_threads_with_kernel_threads() -> None:
    #  val1 = for tv1
    #  val2 = for tv2
    #  _v1  = initial value
    val1_v1 = random.randint(1, 10)
    val2_v1 = random.randint(1, 10)

    def inner_thread_task() -> None:
        # Assert that first time getting value in a new kernel thread raises LookupError
        with pytest.raises(LookupError):
            tv1.get()
        with pytest.raises(LookupError):
            tv2.get()

    def thread_task() -> None:
        tv1.set(val1_v1)
        tv2.set(val2_v1)
        time.sleep(0.1)  # Increase chance of context switching

        assert tv1.get() == val1_v1
        assert tv2.get() == val2_v1
        Thread(target=inner_thread_task).start()
        Thread(target=inner_thread_task).start()

    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[int]("tv2")
    Thread(target=thread_task).start()
    Thread(target=thread_task).start()


def test_treevar_on_kernel_threads_with_trio_threads_with_kernel_threads() -> None:
    #  val1 = for tv1
    #  val2 = for tv2
    #  _v1  = initial value
    #  _v2  = new value
    #  _v3  = newer value
    val1_v1 = random.randint(1, 10)
    val1_v2 = random.randint(1, 10)
    val2_v1 = random.randint(1, 10)
    val2_v2 = random.randint(1, 10)

    def inner_thread_task() -> None:
        # Assert that first time getting value in a new kernel thread raises LookupError
        with pytest.raises(LookupError):
            tv1.get()
        with pytest.raises(LookupError):
            tv2.get()

    def trio_thread_task() -> None:
        # Assert that the value is the value set trio thread was spaned
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2
        Thread(target=inner_thread_task).start()
        Thread(target=inner_thread_task).start()

    async def nursery_task() -> None:
        # Assert that the value is the value set when task started
        assert tv1.get() == val1_v1
        assert tv2.get() == val2_v1

        tv1.set(val1_v2)
        tv2.set(val2_v2)
        await trio.to_thread.run_sync(trio_thread_task)

    async def main() -> None:
        # Assert that the value is the value set when trio event loop started
        assert tv1.get() == val1_v1
        assert tv2.get() == val2_v1
        async with trio.open_nursery() as nursery:
            nursery.start_soon(nursery_task)
            nursery.start_soon(nursery_task)

    def thread_task() -> None:
        tv1.set(val1_v1)
        tv2.set(val2_v1)
        trio.run(main)

    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[int]("tv2")
    Thread(target=thread_task).start()
    Thread(target=thread_task).start()


def test_treevar_set_in_finalizer_does_not_affect_other_tasks() -> None:
    """
    The flow of the test is as follows:
      - normal task waits for custom finalizer to be called
      - custom finalizer of generator is called
      - sets tv1 to a different value
        - normal task gets tv1 value

    This test asserts 2 things:
      - value of tv1 in a regular trio task is not affected by async gen's finalizer
      - async gen finalizer is actually called because otherwise this test will block forever
    """
    #  val1 = for tv1
    #  val2 = for tv2
    #  _v1  = initial value
    #  _v2  = new value
    val1_v1 = random.randint(1, 10)
    val1_v2 = random.randint(1, 10)
    val2_v1 = random.randint(1, 10)
    val2_v2 = random.randint(1, 10)

    tv1 = TreeVar[int]("tv1")
    tv2 = TreeVar[int]("tv2")

    finalizer_has_set_value = trio.Event()

    def my_finalizer(_: AsyncGenerator[object, NoReturn]) -> None:
        tv1.set(val1_v2)
        tv2.set(val2_v2)
        finalizer_has_set_value.set()
        # Assert that the value is the same as the one set earlier in agen finalizer
        assert tv1.get() == val1_v2
        assert tv2.get() == val2_v2

    async def set_at_finalizer() -> None:
        async def agen() -> AsyncGenerator[int, None]:
            yield 42

        await step_outside_async_context(agen())

    async def get() -> None:
        await finalizer_has_set_value.wait()
        # The value should be unaffected by the value set in the generator's finalizer
        assert tv1.get() == val1_v1
        assert tv2.get() == val2_v1

    async def main() -> None:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(set_at_finalizer)
            nursery.start_soon(get)

    tv1.set(val1_v1)
    tv2.set(val2_v1)
    old_hooks = sys.get_asyncgen_hooks()
    sys.set_asyncgen_hooks(finalizer=my_finalizer)
    try:
        trio.run(main)
    finally:
        sys.set_asyncgen_hooks(*old_hooks)
