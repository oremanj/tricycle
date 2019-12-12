import attr
import pytest  # type: ignore
import types
import trio
import trio.testing
from async_generator import asynccontextmanager
from typing import Any, AsyncIterator, Coroutine, Iterator, List
from trio_typing import TaskStatus

from .. import ScopedObject, BackgroundObject


def test_too_much_magic() -> None:
    with pytest.raises(TypeError) as info:

        class TooMuchMagic(ScopedObject):  # pragma: no cover
            async def __open__(self) -> None:
                pass

            @asynccontextmanager
            async def __wrap__(self) -> AsyncIterator[None]:
                yield

    assert str(info.value) == (
        "ScopedObjects can define __open__/__close__, or __wrap__, but not both"
    )


@types.coroutine
def async_yield(value: str) -> Iterator[str]:
    yield value


def test_mro() -> None:
    class A(ScopedObject):
        async def __open__(self) -> None:
            await async_yield("open A")

    class B(A):
        async def __open__(self) -> None:
            await async_yield("open B")

        async def __close__(self) -> None:
            await async_yield("close B")

    class C(A):
        async def __open__(self) -> None:
            await async_yield("open C")

        async def __close__(self) -> None:
            await async_yield("close C")

    class D(B, C):
        def __init__(self, value: int):
            self.value = value

        async def __close__(self) -> None:
            await async_yield("close D")

    assert D.__mro__ == (D, B, C, A, ScopedObject, object)
    d_mgr = D(42)
    assert not isinstance(d_mgr, D)
    assert not hasattr(d_mgr, "value")
    assert hasattr(d_mgr, "__aenter__")

    async def use_it() -> None:
        async with d_mgr as d:
            assert isinstance(d, D)
            assert d.value == 42
            await async_yield("body")

    coro: Coroutine[str, None, None] = use_it()
    record = []
    while True:
        try:
            record.append(coro.send(None))
        except StopIteration:
            break
    assert record == [
        "open A",
        "open C",
        "open B",
        "body",
        "close D",
        "close B",
        "close C",
    ]


@attr.s(auto_attribs=True)
class Example(BackgroundObject):
    ticks: int = 0
    record: List[str] = attr.Factory(list)
    exiting: bool = False

    def __attrs_post_init__(self) -> None:
        assert not hasattr(self, "nursery")
        self.record.append("attrs_post_init")

    async def __open__(self) -> None:
        self.record.append("open")
        await self.nursery.start(self._background_task)
        self.record.append("started")

    async def __close__(self) -> None:
        assert len(self.nursery.child_tasks) != 0
        # Make sure this doesn't raise AttributeError in aexit:
        del self.nursery
        self.record.append("close")
        self.exiting = True

    async def _background_task(self, *, task_status: TaskStatus[None]) -> None:
        self.record.append("background")
        await trio.sleep(1)
        self.record.append("starting")
        task_status.started()
        self.record.append("running")
        while not self.exiting:
            await trio.sleep(1)
            self.ticks += 1
        self.record.append("stopping")


class DaemonExample(Example, daemon=True):
    pass


async def test_background(autojump_clock: trio.testing.MockClock) -> None:
    async with Example(ticks=100) as obj:
        assert obj.record == [
            "attrs_post_init",
            "open",
            "background",
            "starting",
            "running",
            "started",
        ]
        del obj.record[:]
        await trio.sleep(5.5)
    assert obj.record == ["close", "stopping"]
    # 1 sec start + 6 ticks
    assert trio.current_time() == 7.0
    assert obj.ticks == 106
    assert not hasattr(obj, "nursery")

    # With daemon=True, the background tasks are cancelled when the parent exits
    async with DaemonExample() as obj2:
        assert obj2.record == [
            "attrs_post_init",
            "open",
            "background",
            "starting",
            "running",
            "started",
        ]
        del obj2.record[:]
        await trio.sleep(5.5)
    assert obj2.record == ["close"]
    assert trio.current_time() == 13.5
    assert obj2.ticks == 5
