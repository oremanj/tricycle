import attr
import trio
from async_generator import asynccontextmanager
from collections import OrderedDict
from typing import (
    AsyncIterator,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Set,
    TYPE_CHECKING,
)


@attr.s(auto_attribs=True)
class _RWLockStatistics:
    locked: str
    readers: FrozenSet[trio.lowlevel.Task]
    writer: Optional[trio.lowlevel.Task]
    readers_waiting: int
    writers_waiting: int


@attr.s(eq=False, repr=False)
class RWLock:
    """A `readers-writer lock
    <https://en.wikipedia.org/wiki/Readers%E2%80%93writer_lock>`__.

    Each acquisition of the lock specifies whether it is a "reader" or
    a "writer". At any given time, the lock may be held by one writer
    and no readers, by many readers and no writer, or by no one.

    This implementation is fair by default: if task A tried to acquire
    the lock before task B did, task B won't get it first. This
    implies that new readers can't acquire a reader-held lock after a
    writer has started waiting to acquire it, which helps avoid
    starvation of writers by readers. (The Wikipedia article linked
    above calls this "write-preferring".) If you want different behavior,
    see the :attr:`read_biased` attribute.

    Attributes:
      read_biased (bool): Whether new readers should be able to
          immediately acquire a readers-held lock even after some
          writers have started waiting for it. (The Wikipedia article
          linked above calls this "weakly read-preferring".) Note that
          setting :attr:`read_biased` to :data:`True` can result in
          indefinite starvation of writers if the read workload is
          busy enough.  Changing this attribute to :data:`True` will
          immediately wake up all waiting readers to grant them the
          lock if it is currently readers-held with writers waiting.

    """

    _writer: Optional[trio.lowlevel.Task] = attr.ib(default=None, init=False)
    _readers: Set[trio.lowlevel.Task] = attr.ib(factory=set, init=False)
    _waiting: "OrderedDict[trio.lowlevel.Task, bool]" = attr.ib(
        factory=OrderedDict, init=False
    )
    _waiting_writers_count: int = attr.ib(default=0, init=False)
    _read_biased: bool = attr.ib(default=False, kw_only=True)

    def __repr__(self) -> str:
        state = (
            "write-locked"
            if self._writer
            else "read-locked"
            if self._readers
            else "unlocked"
        )
        if self._read_biased:
            state += " read-biased"
        if self._waiting:
            waiters_descs: List[str] = []
            if self._waiting_writers_count:
                waiters_descs.append(f"{self._waiting_writers_count} writers")
            readers_count = len(self._waiting) - self._waiting_writers_count
            if readers_count:
                waiters_descs.append(f"{readers_count} readers")
            waiters = ", {} waiting".format(" and ".join(waiters_descs))
        else:
            waiters = ""
        return f"<{state} RWLock object at {id(self):#x}{waiters}>"

    def locked(self) -> str:
        """Check whether the lock is currently held.

        Returns:
          ``"read"`` if the lock is held by reader(s), ``"write"``
          if the lock is held by a writer, or ``""`` (which tests
          as false) if the lock is not held.
        """
        return "read" if self._readers else "write" if self._writer else ""

    @trio.lowlevel.enable_ki_protection
    def acquire_nowait(self, *, for_write: bool) -> None:
        """Attempt to acquire the lock, without blocking.

        Args:
          for_write: If True, attempt to acquire the lock in write mode,
              which provides exclusive access. If False, attempt to acquire the
              lock in read mode, which permits other readers to also hold it.

        Raises:
          trio.WouldBlock: if the lock cannot be acquired without blocking
          RuntimeError: if the current task already holds the lock (in either
              read or write mode)
        """
        task = trio.lowlevel.current_task()
        if self._writer is task or task in self._readers:
            raise RuntimeError("attempt to re-acquire an already held RWLock")
        if self._writer is not None:
            raise trio.WouldBlock

        if for_write and not self._readers:
            self._writer = task
        elif not for_write and (self._read_biased or not self._waiting_writers_count):
            self._readers.add(task)
        else:
            raise trio.WouldBlock

    @trio.lowlevel.enable_ki_protection
    async def acquire(self, *, for_write: bool) -> None:
        """Acquire the lock, blocking if necessary.

        Args:
          for_write: If True, acquire the lock in write mode,
              which provides exclusive access. If False, acquire the
              lock in read mode, which permits other readers to also hold it.

        Raises:
          RuntimeError: if the current task already holds the lock (in either
              read or write mode)
        """
        await trio.lowlevel.checkpoint_if_cancelled()
        try:
            self.acquire_nowait(for_write=for_write)
        except trio.WouldBlock:
            task = trio.lowlevel.current_task()
            self._waiting[task] = for_write
            self._waiting_writers_count += for_write

            def abort_fn(_: object) -> trio.lowlevel.Abort:
                del self._waiting[task]
                self._waiting_writers_count -= for_write
                return trio.lowlevel.Abort.SUCCEEDED

            await trio.lowlevel.wait_task_rescheduled(abort_fn)
        else:
            await trio.lowlevel.cancel_shielded_checkpoint()

    @trio.lowlevel.enable_ki_protection
    def release(self) -> None:
        """Release the lock.

        Raises:
          RuntimeError: if the current task does not hold the lock (in either
              read or write mode)
        """
        task = trio.lowlevel.current_task()
        if task is self._writer:
            self._writer = None
        elif task in self._readers:
            self._readers.remove(task)
            if self._readers:
                return
        else:
            raise RuntimeError("can't release a RWLock you don't own")

        while self._writer is None and self._waiting:
            task, for_write = self._waiting.popitem(last=False)
            if not for_write:
                # Next task is a reader: since we haven't woken
                # a writer yet, we can wake it,
                self._readers.add(task)
                trio.lowlevel.reschedule(task)
                # In read-biased mode we can continue to wake
                # all other readers.
                if self._read_biased:
                    self._wake_all_readers()
                    return
                # In fair mode we can only wake the readers that
                # arrived before the next writer, so keep iterating
                # through self._waiting.
            elif not self._readers:
                # Next task is a writer and there are no readers;
                # wake the writer and we're done.
                self._writer = task
                self._waiting_writers_count -= 1
                trio.lowlevel.reschedule(task)
                break
            else:
                # Next task is a writer, but can't be woken because
                # there are readers. Put it back at the front of the
                # line.
                self._waiting[task] = for_write
                self._waiting.move_to_end(task, last=False)
                break

    def _wake_all_readers(self) -> None:
        for task, for_write in list(self._waiting.items()):
            if not for_write:
                del self._waiting[task]
                self._readers.add(task)
                trio.lowlevel.reschedule(task)

    # https://github.com/python/mypy/issues/1362: mypy doesn't support
    # decorated properties yet
    if TYPE_CHECKING:
        read_biased: bool
    else:

        @property
        def read_biased(self) -> bool:
            return self._read_biased

        @read_biased.setter
        @trio.lowlevel.enable_ki_protection
        def read_biased(self, new_value: bool) -> None:
            if new_value and not self._read_biased:
                self._wake_all_readers()
            self._read_biased = new_value

    def acquire_read_nowait(self) -> None:
        """Equivalent to ``acquire_nowait(for_write=False)``."""
        return self.acquire_nowait(for_write=False)

    def acquire_write_nowait(self) -> None:
        """Equivalent to ``acquire_nowait(for_write=True)``."""
        return self.acquire_nowait(for_write=True)

    async def acquire_read(self) -> None:
        """Equivalent to ``acquire(for_write=False)``."""
        return await self.acquire(for_write=False)

    async def acquire_write(self) -> None:
        """Equivalent to ``acquire(for_write=True)``."""
        return await self.acquire(for_write=True)

    @trio.lowlevel.enable_ki_protection
    @asynccontextmanager
    async def read_locked(self) -> AsyncIterator[None]:
        """Returns an async context manager whose ``__aenter__`` blocks
        to acquire the lock in read mode, and whose ``__aexit__``
        synchronously releases it.
        """
        await self.acquire(for_write=False)
        try:
            yield
        finally:
            self.release()

    @trio.lowlevel.enable_ki_protection
    @asynccontextmanager
    async def write_locked(self) -> AsyncIterator[None]:
        """Returns an async context manager whose ``__aenter__`` blocks
        to acquire the lock in write mode, and whose ``__aexit__``
        synchronously releases it.
        """
        await self.acquire(for_write=True)
        try:
            yield
        finally:
            self.release()

    def statistics(self) -> _RWLockStatistics:
        r"""Return an object containing debugging information.

        Currently the following fields are defined:

        * ``locked``: boolean indicating whether the lock is held by anyone
        * ``state``: string with one of the values ``"read"`` (held by one
          or more readers), ``"write"`` (held by one writer),
          or ``"unlocked"`` (held by no one)
        * ``readers``: a frozenset of the :class:`~trio.lowlevel.Task`\s
          currently holding the lock in read mode (may be empty)
        * ``writer``: the :class:`trio.lowlevel.Task` currently holding
          the lock in write mode, or None if the lock is not held in write mode
        * ``readers_waiting``: the number of tasks blocked waiting to acquire
          the lock in read mode
        * ``writers_waiting``: the number of tasks blocked waiting to acquire
          the lock in write mode

        """
        return _RWLockStatistics(
            locked=self.locked(),
            readers=frozenset(self._readers),
            writer=self._writer,
            readers_waiting=len(self._waiting) - self._waiting_writers_count,
            writers_waiting=self._waiting_writers_count,
        )
