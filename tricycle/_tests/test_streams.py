import pytest  # type: ignore
import locale
import random
import sys

import trio
import trio.testing
from async_generator import asynccontextmanager
from functools import partial
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    List,
    Optional,
    Sequence,
    Tuple,
    cast,
)
from typing_extensions import AsyncContextManager
from .. import BufferedReceiveStream, TextReceiveStream


async def test_buffered_receive(autojump_clock: trio.testing.MockClock) -> None:
    send_stream, receive_stream_raw = trio.testing.memory_stream_one_way_pair()
    receive_stream = BufferedReceiveStream(receive_stream_raw, chunk_size=8)

    orig_receive_some = receive_stream_raw.receive_some
    raw_receive_sizes = []

    async def hooked_receive_some(max_bytes: int) -> bytes:
        result = await orig_receive_some(max_bytes)
        raw_receive_sizes.append(len(result))
        return result

    receive_stream_raw.receive_some = hooked_receive_some  # type: ignore

    # Send a big block, receive a little at a time
    data = bytes(val for val in range(64))
    await send_stream.send_all(data)

    async def checked_receive(num_bytes: int, raw_reads: Sequence[int] = ()) -> bytes:
        try:
            with trio.testing.assert_checkpoints():
                return await receive_stream.receive(num_bytes)
        finally:
            assert list(raw_reads) == raw_receive_sizes
            raw_receive_sizes[:] = []

    chunks = [
        await checked_receive(4, [8]),
        await checked_receive(1),
        await checked_receive(3),  # go exactly to end of chunk
        await checked_receive(1, [8]),
        await checked_receive(9, [8]),  # receive across chunk boundary
        await checked_receive(18, [12]),  # >1 chunk beyond buffered amount
        await checked_receive(12, [12]),  # >1 chunk starting from boundary
        await checked_receive(14, [14]),  # 2 bytes left after this point
        await checked_receive(1, [2]),
        await checked_receive(1),  # everything consumed
    ]
    assert b"".join(chunks) == data

    receive_stream.unget(b"1234")
    assert await receive_stream.receive(2) == b"12"
    receive_stream.unget(b"012")
    assert await receive_stream.receive(4) == b"0123"
    receive_stream.unget(b"tt")
    assert await receive_stream.receive(3) == b"tt4"

    with pytest.raises(trio.TooSlowError), trio.fail_after(1):
        await checked_receive(1)
    await send_stream.send_all(b"xyz")
    with pytest.raises(trio.TooSlowError), trio.fail_after(1):
        await checked_receive(10, [3])
    await send_stream.send_all(b"abcdabcdabcd")
    with pytest.raises(trio.TooSlowError), trio.fail_after(1):
        await checked_receive(16, [12])
    assert b"xyzabcd" == await checked_receive(7)
    await send_stream.aclose()
    assert b"abcdabcd" == await checked_receive(32, [0])
    assert b"" == await checked_receive(32, [0])

    # now try a clean EOF
    send_stream, receive_stream_raw = trio.testing.memory_stream_one_way_pair()
    receive_stream = BufferedReceiveStream(receive_stream_raw, chunk_size=8)
    orig_receive_some = receive_stream_raw.receive_some
    receive_stream_raw.receive_some = hooked_receive_some  # type: ignore

    await send_stream.send_all(b"1234")
    assert b"12" == await checked_receive(2, [4])
    with pytest.raises(trio.TooSlowError), trio.fail_after(1):
        await checked_receive(3)
    await send_stream.aclose()
    assert b"34" == await checked_receive(3, [0])

    await receive_stream.aclose()


@pytest.fixture  # type: ignore  # "Untyped decorator makes ... untyped"
async def receiver_factory() -> AsyncIterator[
    Callable[[], AsyncContextManager[BufferedReceiveStream]]
]:
    async def send_task(send_stream: trio.abc.SendStream) -> None:
        for val in b"0123456789":
            await send_stream.send_all(bytes([val]))
            await trio.sleep(1)
        await send_stream.aclose()

    @asynccontextmanager
    async def receiver() -> AsyncIterator[BufferedReceiveStream]:
        send_stream, receive_stream_raw = trio.testing.memory_stream_one_way_pair()
        async with trio.open_nursery() as nursery:
            nursery.start_soon(send_task, send_stream)
            try:
                yield BufferedReceiveStream(receive_stream_raw, chunk_size=8)
            finally:
                nursery.cancel_scope.cancel()

    yield receiver


async def test_buffered_receive_helpers(
    autojump_clock: trio.testing.MockClock,
    receiver_factory: Callable[[], AsyncContextManager[BufferedReceiveStream]],
) -> None:
    async with receiver_factory() as receive_stream:
        assert b"012345" == await receive_stream.receive_all_or_none(6)
        assert b"6789" == await receive_stream.receive_all_or_none(4)
        assert None is await receive_stream.receive_all_or_none(42)

    async with receiver_factory() as receive_stream:
        assert b"0" == await receive_stream.receive_all_or_none(1)
        assert b"123456789" == await receive_stream.receive_all_or_none(9)
        assert None is await receive_stream.receive_all_or_none(3)

    async with receiver_factory() as receive_stream:
        assert b"012345" == await receive_stream.receive_all_or_none(6)
        with pytest.raises(ValueError) as info:
            await receive_stream.receive_all_or_none(5)
        assert str(info.value) == (
            "unclean EOF (4 bytes after boundary, expected at least 5)"
        )
        assert b"6789" == await receive_stream.receive(4)
        assert None is await receive_stream.receive_all_or_none(4)
        assert b"" == await receive_stream.receive(4)

    async with receiver_factory() as receive_stream:
        assert b"012345" == await receive_stream.receive_all_or_none(6)
        with pytest.raises(ValueError) as info:
            await receive_stream.receive_all_or_none(5)
        assert str(info.value) == (
            "unclean EOF (4 bytes after boundary, expected at least 5)"
        )
        assert b"6789" == await receive_stream.receive(4)
        assert None is await receive_stream.receive_all_or_none(4)
        assert b"" == await receive_stream.receive(4)

    async with receiver_factory() as receive_stream:
        assert b"0" == await receive_stream.receive_exactly(1)
        assert b"1234567" == await receive_stream.receive_exactly(7)
        with pytest.raises(ValueError) as info:
            await receive_stream.receive_exactly(3)
        assert str(info.value) == "unclean EOF (read only 2/3 bytes)"
        assert b"89" == await receive_stream.receive_exactly(2)
        with pytest.raises(ValueError) as info:
            await receive_stream.receive_exactly(3)
        assert str(info.value) == "unclean EOF (read only 0/3 bytes)"


async def test_text_receive(autojump_clock: trio.testing.MockClock) -> None:
    test_input = (
        b"The quick brown fox jumps over the lazy dog.\r\n\n\r\r\n\n"
        b"Yup.\n"
        b"That \xf0\x9f\xa6\x8a is still jumping.\r"  # fox emoji
    )

    # Test that encoding=None uses the locale preferred encoding
    stream = TextReceiveStream(None)  # type: ignore
    assert stream.encoding == locale.getpreferredencoding(False)
    del stream

    newline: Optional[str]
    for newline in ("\r", "\n", "\r\n", "", "jump", None):
        output_str = test_input.decode("utf-8")
        if newline == "":
            output_lines = output_str.splitlines(True)
        elif newline is None:
            output_lines = (
                output_str.replace("\r\n", "\n").replace("\r", "\n").splitlines(True)
            )
        else:
            output_lines = [line + newline for line in output_str.split(newline)]
            if output_lines[-1] == newline:
                del output_lines[-1]
            else:
                output_lines[-1] = output_lines[-1][: -len(newline)]

        Streams = Tuple[trio.testing.MemorySendStream, TextReceiveStream]

        async def make_streams_with_hook(
            hook: Optional[
                Callable[
                    [trio.testing.MemorySendStream, trio.testing.MemoryReceiveStream],
                    Awaitable[None],
                ]
            ]
        ) -> Streams:

            send_stream, receive_stream_raw = trio.testing.memory_stream_one_way_pair()
            receive_stream = TextReceiveStream(
                receive_stream_raw, "UTF-8", chunk_size=8, newline=newline
            )
            if hook is not None:
                send_stream.send_all_hook = partial(
                    hook, send_stream, receive_stream_raw
                )
            assert receive_stream.encoding == "UTF-8"
            assert receive_stream.errors is None
            return send_stream, receive_stream

        async def make_streams_all_at_once() -> Streams:
            return await make_streams_with_hook(None)

        async def make_streams_one_byte_at_a_time() -> Streams:
            async def trickle(
                send: trio.testing.MemorySendStream,
                receive: trio.testing.MemoryReceiveStream,
            ) -> None:
                while trio.testing.memory_stream_pump(send, receive, max_bytes=1):
                    await trio.sleep(1)

            return await make_streams_with_hook(trickle)

        async def make_streams_random_small_units() -> Streams:
            async def trickle(
                send: trio.testing.MemorySendStream,
                receive: trio.testing.MemoryReceiveStream,
            ) -> None:
                while trio.testing.memory_stream_pump(
                    send, receive, max_bytes=random.randint(1, 16)
                ):
                    await trio.sleep(1)

            return await make_streams_with_hook(trickle)

        for strategy in (
            make_streams_all_at_once,
            make_streams_one_byte_at_a_time,
            make_streams_random_small_units,
            make_streams_random_small_units,
            make_streams_random_small_units,
            make_streams_random_small_units,
            make_streams_random_small_units,
            make_streams_random_small_units,
        ):
            send_stream, receive_stream = await strategy()
            received_lines: List[str] = []

            async def receive_in_background() -> None:
                async for line in receive_stream:
                    received_lines.append(line)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(receive_in_background)
                await send_stream.send_all(test_input)
                await trio.sleep(2)
                length_before_eof = len(received_lines)
                await send_stream.aclose()

            # Universal newline support will wait for a potential \n
            # after the trailing \r and we don't get that line until EOF.
            assert len(received_lines) == length_before_eof + (newline != "\r")
            assert received_lines == output_lines
            # The .newlines property is broken on PyPy:
            # https://bitbucket.org/pypy/pypy/issues/3012
            if sys.implementation.name == "cpython":
                if not newline:
                    newlines_seen = cast(Tuple[str, ...], receive_stream.newlines)
                    assert set(newlines_seen) == {"\r", "\n", "\r\n"}
                else:
                    assert receive_stream.newlines is None


async def test_text_receive_fix_errors() -> None:
    test_input = b"The quick brown \xf0\x9f\xa6\x8a jumps over the lazy dog.\n"
    for chunk_size in range(1, len(test_input)):
        send_stream, receive_stream_raw = trio.testing.memory_stream_one_way_pair()
        receive_stream = TextReceiveStream(
            receive_stream_raw, chunk_size=chunk_size, encoding="ascii"
        )
        await send_stream.send_all(test_input)
        await send_stream.aclose()
        with pytest.raises(UnicodeDecodeError):
            await receive_stream.receive_line()
        with pytest.raises(UnicodeDecodeError):
            await receive_stream.receive_line()
        receive_stream.errors = "replace"
        assert receive_stream.errors == "replace"
        line = await receive_stream.receive_line()
        x = chr(65533)
        assert f"The quick brown {x}{x}{x}{x} jumps over the lazy dog.\n" == line
        assert "" == await receive_stream.receive_line()
        await receive_stream.aclose()


async def test_text_receive_hits_max_chars() -> None:
    test_input = b"The quick\nbrown \xf0\x9f\xa6\x8a\njumps over\r\nthe lazy dog.\n"
    for chunk_size in range(1, len(test_input)):
        send_stream, receive_stream_raw = trio.testing.memory_stream_one_way_pair()
        receive_stream = TextReceiveStream(
            receive_stream_raw, chunk_size=chunk_size, encoding="utf-8"
        )
        await send_stream.send_all(test_input)
        await send_stream.aclose()

        fox = chr(129_418)
        assert "The quick\n" == await receive_stream.receive_line(12)
        assert f"brown {fox}" == await receive_stream.receive_line(7)
        assert "\n" == await receive_stream.receive_line(10)
        assert "jumps ov" == await receive_stream.receive_line(8)
        assert "er\r" == await receive_stream.receive_line(3)
        assert "\n" == await receive_stream.receive_line(1)
        assert "the lazy dog.\n" == await receive_stream.receive_line(20)
        assert "" == await receive_stream.receive_line(1)
