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


.. _tree-variables:

Tree variables
--------------

When you start a new Trio task, the initial values of its `context variables
<https://trio.readthedocs.io/en/stable/reference-core.html#task-local-storage>`__
(`contextvars.ContextVar`) are inherited from the environment of the
`~trio.Nursery.start_soon` or `~trio.Nursery.start` call that
started the new task. For example, this code:

.. code-block:: python3

   some_cvar = contextvars.ContextVar()

   async def print_in_child(tag):
       print("In child", tag, "some_cvar has value", some_cvar.get())

   some_cvar.set(1)
   async with trio.open_nursery() as nursery:
       nursery.start_soon(print_in_child, 1)
       some_cvar.set(2)
       nursery.start_soon(print_in_child, 2)
       some_cvar.set(3)
       print("In parent some_cvar has value", some_cvar.get())

will produce output like::

    In parent some_cvar has value 3
    In child 1 some_cvar has value 1
    In child 2 some_cvar has value 2

(If you run it yourself, you might find that the "child 2" line comes
before "child 1", but it will still be the case that child 1 sees value 1
while child 2 sees value 2.)

You might wonder why this differs from the behavior of cancel scopes,
which only apply to a new task if they surround the new task's entire
nursery (as explained in the Trio documentation about
`child tasks and cancellation <https://trio.readthedocs.io/en/stable/reference-core.html#child-tasks-and-cancellation>`__). The difference is that a cancel
scope has a limited lifetime (it can't cancel anything once you exit
its ``with`` block), while a context variable's value is just a value
(request #42 can keep being request #42 for as long as it likes,
without any cooperation from the task that created it).

In specialized cases, you might want to provide a task-local value
that's inherited only from the parent nursery, like cancel scopes are.
For example, maybe you're trying to provide child tasks with access to
a limited-lifetime resource such as a nursery or network connection,
and you only want a task to be able to use the resource if it's going
to remain available for the task's entire lifetime. You can support
this use case using `TreeVar`, which is like `contextvars.ContextVar`
except for the way that it's inherited by new tasks. (It's a "tree"
variable because it's inherited along the parent-child links that form
the Trio task tree.)

If the above example used `TreeVar`, then its output would be:

.. code-block:: none
   :emphasize-lines: 3

   In parent some_cvar has value 3
   In child 1 some_cvar has value 1
   In child 2 some_cvar has value 1

because child 2 would inherit the value from its parent nursery, rather than
from the environment of the ``start_soon()`` call that creates it.

.. autoclass:: tricycle.TreeVar(name, [*, default])

   .. automethod:: being
      :with:
   .. automethod:: get_in(task_or_nursery, [default])
