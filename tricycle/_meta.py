import abc
import functools
from async_generator import asynccontextmanager
from trio import Nursery
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    ClassVar,
    Dict,
    Optional,
    Type,
    TypeVar,
    TYPE_CHECKING,
)
from ._service_nursery import open_service_nursery


T = TypeVar("T")


class ScopedObjectMeta(abc.ABCMeta):
    # Metaclass that provides the ScopedObject magic. See ScopedObject
    # for the docs.
    def __new__(
        mcls, clsname: str, bases: Any, dct: Dict[str, Any], **kwargs: Any
    ) -> "ScopedObjectMeta":
        if "__open__" in dct or "__close__" in dct:
            if "__wrap__" in dct:
                raise TypeError(
                    "ScopedObjects can define __open__/__close__, or __wrap__, "
                    "but not both"
                )

            async def noop(self: Any) -> None:
                pass

            _open_: Callable[[Any], Awaitable[None]] = dct.get("__open__", noop)
            _close_: Callable[[Any], Awaitable[None]] = dct.get("__close__", noop)

            @asynccontextmanager
            async def wrap(self: Any) -> AsyncIterator[None]:
                async with super(cls, self).__wrap__():  # type: ignore
                    await _open_(self)
                    try:
                        yield
                    finally:
                        await _close_(self)

            wrap.__name__ = "__wrap__"
            wrap.__qualname__ = dct["__qualname__"] + ".__wrap__"
            dct["__wrap__"] = wrap

        # NB: wrap() closes over this 'cls' variable
        cls: ScopedObjectMeta = super().__new__(  # type: ignore
            mcls, clsname, bases, dct, **kwargs
        )
        return cls

    @asynccontextmanager
    async def __call__(cls: Type[T], *args: Any, **kwds: Any) -> AsyncIterator[T]:
        self: T = super().__call__(*args, **kwds)  # type: ignore
        async with self.__wrap__():  # type: ignore
            yield self


class ScopedObject(metaclass=ScopedObjectMeta):
    """An object whose lifetime must be bound to an ``async with`` block.

    Suppose that ``Foo`` is a :class:`ScopedObject` subclass. Then if
    you say ``Foo(*args)``, you won't actually get a ``Foo`` object;
    instead, you'll get an async context manager that evaluates to a
    ``Foo`` object.  So you would need to say::

        async with Foo(*args) as my_foo:
            # do stuff with my_foo

    This allows ``Foo`` to have reliable control of its lifetime, so
    it can spawn background tasks, deterministically execute cleanup
    code, and so on.

    If you want to implement such an object, inherit from :class:`ScopedObject`
    and indicate what should happen on entry and exit of the context.
    This should be done in one of the following two ways:

    * Define async ``__open__`` and/or ``__close__`` methods, which will
      be called from the context ``__aenter__`` and ``__aexit__`` respectively,
      taking no arguments and returning ``None``.
      ``__close__`` will be called no matter whether the context exits
      normally or due to an exception. (It can tell whether there is an
      active exception by using :func:`sys.exc_info`, but cannot suppress
      it.) If you use this approach, :class:`ScopedObject` takes care of
      invoking any initialization and finalization logic
      supplied by your base classes.

    * Define a ``__wrap__`` method that returns an async context
      manager.  This gives you more flexibility than implementing
      ``__open__`` and ``__close__``, because you can run some code
      outside of your base classes' scope and can swallow exceptions,
      but means you have to enter the base classes' scope yourself.

    It is an error to define both ``__wrap__`` and (``__open__`` or
    ``__close__``). If you don't define ``__wrap__``,
    :class:`ScopedObject` generates it for you in terms of
    ``__open__`` and ``__close__``, with semantics equivalent to the
    following::

        @asynccontextmanager
        async def __wrap__(self):
            async with super().__wrap__():
                if hasattr(self, "__open__"):
                    await self.__open__()
                try:
                    yield
                finally:
                    if hasattr(self, "__close__"):
                        await self.__close__()

    """

    __slots__ = ("__weakref__",)

    @asynccontextmanager
    async def __wrap__(self) -> AsyncIterator[None]:
        yield

    if TYPE_CHECKING:
        # These are necessary to placate mypy, which doesn't understand
        # the asynccontextmanager metaclass __call__. They should never
        # actually get called.
        async def __aenter__(self: T) -> T:
            raise AssertionError

        async def __aexit__(self, *exc: object) -> None:
            raise AssertionError


class BackgroundObject(ScopedObject):
    """A :class:`ScopedObject` that automatically creates a
    :func:`service nursery <open_service_nursery>` for running background tasks.

    If you pass ``daemon=True`` when inheriting from :class:`BackgroundObject`,
    like so::

        class MyObject(BackgroundObject, daemon=True):
            ...

    then the tasks spawned in the nursery will automatically be cancelled
    when the ``async with MyObject(...) as obj:`` block exits.
    Otherwise, the parent waits for the children to exit normally, like
    the default Trio nursery behavior.

    """

    __slots__ = ("nursery",)
    __daemon: ClassVar[bool]

    def __init_subclass__(cls, *, daemon: bool = False, **kwargs: Any):
        cls.__daemon = daemon
        super().__init_subclass__(**kwargs)  # type: ignore

    @asynccontextmanager
    async def __wrap__(self) -> AsyncIterator[None]:
        async with super().__wrap__():
            try:
                async with open_service_nursery() as nursery:
                    self.nursery = nursery
                    yield
                    if type(self).__daemon:
                        nursery.cancel_scope.cancel()
            finally:
                try:
                    del self.nursery
                except AttributeError:
                    pass
