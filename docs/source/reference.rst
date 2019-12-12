API reference
=============

.. module:: tricycle

Synchronization primitives
--------------------------

.. autoclass:: RWLock

   .. automethod:: acquire
   .. automethod:: acquire_read
   .. automethod:: acquire_write
   .. automethod:: acquire_nowait
   .. automethod:: acquire_read_nowait
   .. automethod:: acquire_write_nowait
   .. automethod:: release
   .. automethod:: read_locked
   .. automethod:: write_locked
   .. automethod:: locked
   .. automethod:: statistics


Stream helpers
--------------

tricycle comes with two wrappers around Trio receive streams:
:class:`BufferedReceiveStream`, which helps in parsing binary protocols that
use fixed-length fields, and :class:`TextReceiveStream`, which helps in
parsing line-oriented textual data.

.. autoclass:: BufferedReceiveStream
   :show-inheritance:
   :members:

.. autoclass:: TextReceiveStream
   :show-inheritance:
   :members:

   .. attribute:: transport_stream
   .. attribute:: encoding
   .. attribute:: errors
   .. attribute:: chunk_size

      The values passed as constructor parameters are also available as
      attributes on the resulting :class:`TextReceiveStream` object.
      :attr:`errors` and :attr:`chunk_size` are writable; the others are read-only.
      (For example, if a read fails with a :exc:`UnicodeDecodeError`, it is safe
      to set ``stream.errors = "replace"`` and retry the read.)


Cancellation helpers
--------------------

Gracefully shutting down a complex task tree can sometimes require
tasks to be cancelled in a particular order. As a motivating example,
we'll consider a simple protocol implementation where the client and
server exchange newline-terminated textual messages, and the client is
supposed to send a message containing the text "goodbye" before it
disconnects::

    async def receive_messages(
        source: trio.abc.ReceiveStream, sink: trio.abc.SendChannel[str]
    ) -> None:
        async for line in TextReceiveStream(source, newline="\r\n"):
            await sink.send(line.rstrip("\r\n"))
        await sink.aclose()

    async def send_messages(
        source: trio.abc.ReceiveChannel[str], sink: trio.abc.HalfCloseableStream
    ) -> None:
        async with source:
            async for msg in source:
                await sink.send_all(msg.encode("utf-8") + b"\r\n")
            await sink.send_eof()

    @asynccontextmanager
    async def wrap_stream(
        stream: trio.abc.HalfCloseableStream
    ) -> AsyncIterator[trio.abc.ReceiveChannel[str], trio.abc.SendChannel[str]]:
        async with trio.open_nursery() as nursery:
            incoming_w, incoming_r = trio.open_memory_channel[str](0)
            outgoing_w, outgoing_r = trio.open_memory_channel[str](0)
            nursery.start_soon(receive_messages, stream, incoming_w)
            nursery.start_soon(send_messages, outgoing_r, stream)
            try:
                yield (incoming_r, outgoing_w)
            finally:
                with trio.move_on_after(1) as scope:
                    scope.shield = True
                    await outgoing_w.send("goodbye")

    async def example() -> None:
        with trio.move_on_after(5):
            async with trio.open_tcp_stream("example.com", 1234) as stream, \
                       wrap_stream(stream) as (incoming, outgoing):
                async for line in incoming:
                    await outgoing.send("you said: " + line)
                    if line == "quit":
                        break

The intent is that ``example()`` will echo back each message it receives,
until either it receives a "quit" message or five seconds have elapsed.
``wrap_stream()`` has carefully set up a shielded cancel scope around
the place where it sends the goodbye message, so that the message can
still be sent if the ``async with wrap_stream(...)`` block is
cancelled.  (Without this shield, the call to ``send()`` would
immediately raise :exc:`~trio.Cancelled` without sending anything.)

If you run this, though, you'll find that it doesn't quite work.
Exiting due to a "quit" will send the goodbye, but exiting on a
cancellation won't. In fact, the cancellation case will probably
crash with a :exc:`~trio.BrokenResourceError` when it tries to send
the goodbye. Why is this?

The problem is that the call to ``send()`` isn't sufficient on its own to
cause the message to be transmitted. It only places the message into a
channel; nothing will actually be sent until the ``send_messages()`` task
reads from that channel and passes some bytes to ``send_all()``.
Before that can happen, ``send_messages()`` will itself have been cancelled.

The pattern in this example is a common one: some work running in the body
of a nursery is reliant on services provided by background tasks in that
nursery. A normal Trio nursery doesn't draw any distinctions between the
body of the ``async with`` and the background tasks; if the nursery is
cancelled, everything in it will receive that cancellation immediately.
In this case, though, it seems that all of our troubles would be resolved
if only we could somehow ensure that those background tasks stay running
until the body of the ``async with`` has completed.

tricycle's *service nursery* does exactly this.

.. autofunction:: open_service_nursery


If you need to do manipulations of this sort yourself, it can be helpful
to be able to treat multiple cancel scopes as a single unit.

.. autoclass:: MultiCancelScope

   .. automethod:: open_child
   .. automethod:: cancel
   .. autoattribute:: shield
   .. autoattribute:: cancel_called


Scoped objects
--------------

Trio follows the principles of `structured concurrency
<https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/>`__:
its general-purpose APIs for spawning background tasks all require that
the lifetime of each task be bounded by an ``async with`` block
in its parent (represented by the :class:`nursery <trio.Nursery>` object).
Sometimes this can seem rather inconvenient; for example, what if you want
to create a class whose instances spawn tasks that live for the lifetime of
the instance? The traditional approach goes something like this::

    class WebsocketConnection:
        def __init__(self, nursery: trio.Nursery, **etc):
            self._nursery = nursery
            # initialize other members from **etc

        async def connect(self):
            await foo()  # can't be in __init__ because __init__ is synchronous
            self._nursery.start_soon(self._manage_connection)

    @asynccontextmanager
    async def open_websocket_connection(**etc) -> AsyncIterator[WebsocketConnection]:
        async with open_service_nursery() as nursery:
            conn = WebsocketConnection(nursery, **etc)
            await conn.connect()
            yield conn
            nursery.cancel_scope.cancel()

    async def use_websocket():
        async with open_websocket_connection(**etc) as conn:
            await conn.send("Hi!")

tricycle improves on this by providing the ability to define *scoped objects*,
which can only be instantiated as part of an ``async with`` block.
In addition to the usual synchronous ``__init__`` method, their class can
define async methods called ``__open__`` and/or ``__close__`` which run at the
start and end (respectively) of the ``async with`` block. For greater expressive
power, it is also possible to define a ``__wrap__`` method which returns the
entire async context manager to use.

.. autoclass:: ScopedObject

A subclass is provided to handle the common case where a nursery should be
created and remain open for the lifetime of the object:

.. autoclass:: BackgroundObject
   :show-inheritance:

   .. attribute:: nursery

      The nursery that was created for this object. This attribute only
      exists within the scope of the object's ``async with`` block, so
      it cannot be used from ``__init__``, nor after the block has been
      exited.

If made to use :class:`BackgroundObject`, the websocket example above
from above would reduce to::

    class WebsocketConnection(BackgroundObject, daemon=True):
        def __init__(self, **etc):
            # initialize other members from **etc

        async def __open__(self) -> None:
            await foo()
            self.nursery.start_soon(self._manage_connection)

    async def use_websocket():
        async with WebsocketConnection(**etc) as conn:
            await conn.send("Hi!")
