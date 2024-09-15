from __future__ import annotations

import attrs
import contextvars
import trio
import weakref
import threading
from contextlib import contextmanager
from typing import (
    TypeVar,
    Generic,
    Any,
    Iterator,
    MutableMapping,
    Optional,
    Union,
    overload,
)

T = TypeVar("T")
U = TypeVar("U")


class SyncContextTask:
    """We treat sync context in a thread as a single trio-task-like task.
    Every thread will have at most 1 `SyncContextTask` object.
    """

    def __init__(self, is_trio_thread: bool) -> None:
        self.is_trio_thread = is_trio_thread
        # Dummy properties expected for a dummy task
        self.parent_nursery = None
        self.eventual_parent_nursery = None
        self.child_nurseries: list[trio.Nursery] = []
        self.context = contextvars.copy_context()

    @property
    def name(self) -> str:
        return self.__repr__()


TaskLike = Union[trio.lowlevel.Task, SyncContextTask]

# Use threading.local instead of contextvars because
# contextvars behave differently for trio-created threads and kernel threads
data_per_thread = threading.local()

__all__ = ["TreeVar", "TreeVarToken", "SyncContextTask"]


MISSING: Any = contextvars.Token.MISSING


@attrs.define(eq=False)
class _TreeVarState(Generic[T]):
    """The value associated with the inner contextvar of a TreeVar."""

    # Weakref to the task for which this state is valid; used to notice
    # when a TreeVar has been inherited across start_soon() and recompute
    # its value via tree-based inheritance.
    task_ref: weakref.ref[TaskLike]

    # Value accessed by TreeVar.get() and TreeVar.set() within that task.
    value_for_task: T = MISSING

    # Value that will be inherited by children of the given nursery within
    # that task. Used to avoid having modifications after a nursery
    # was opened affect child tasks of that nursery.
    value_for_children: MutableMapping[trio.Nursery, T] = attrs.Factory(
        weakref.WeakKeyDictionary
    )

    def save_current_for_children(self) -> None:
        """Associate the current value_for_task as the value_for_children
        of all this task's child nurseries that were not already being tracked.
        Call this before modifying the value_for_task.
        """
        task = self.task_ref()
        if task is None:  # pragma: no cover
            return
        for nursery in task.child_nurseries:
            self.value_for_children.setdefault(nursery, self.value_for_task)


@attrs.frozen
class TreeVarToken(Generic[T]):
    var: TreeVar[T]
    old_value: T
    _context: contextvars.Context = attrs.field(repr=False)


class TreeVar(Generic[T]):
    """A "tree variable": like a context variable except that its value
    in a new task is inherited from the new task's parent nursery rather
    than from the new task's spawner.

    `TreeVar` objects support all the same methods and attributes as
    `~contextvars.ContextVar` objects
    (:meth:`~contextvars.ContextVar.get`,
    :meth:`~contextvars.ContextVar.set`,
    :meth:`~contextvars.ContextVar.reset`, and
    `~contextvars.ContextVar.name`), and they are constructed the same
    way. They also provide the additional methods :meth:`being` and
    :meth:`get_in`, documented below.

    .. note:: `TreeVar` values are not directly stored in the
       `contextvars.Context`, so you can't use `Context.get()
       <contextvars.Context.get>` to access them. If you need the value
       in a context other than your own, use :meth:`get_in`.

    """

    __slots__ = ("_cvar", "_default")

    _cvar: contextvars.ContextVar[_TreeVarState[T]]
    _default: T

    def __init__(self, name: str, *, default: T = MISSING):
        self._cvar = contextvars.ContextVar(name)
        self._default = default

    def __repr__(self) -> str:
        dflt = ""
        if self._default is not MISSING:
            dflt = f" default={self._default!r}"
        return (
            f"<tricycle.TreeVar name={self._cvar.name!r}{dflt} at {id(self._cvar):#x}>"
        )

    @property
    def name(self) -> str:
        return self._cvar.name

    def _fetch(
        self,
        for_task: TaskLike,
        current_task: Optional[TaskLike],
    ) -> _TreeVarState[T]:
        """Return the _TreeVarState associated with *for_task*, inheriting
        it from a parent nursery if necessary.
        """
        try:
            current_state = for_task.context[self._cvar]
            set_in_task = current_state.task_ref()
        except KeyError:
            set_in_task = None
        if set_in_task is for_task:
            return current_state

        # This TreeVar hasn't yet been used in the current task.
        # Initialize it based on the value it had when any of our
        # enclosing nurseries were opened, nearest first.
        nursery = for_task.eventual_parent_nursery or for_task.parent_nursery
        inherited_value: T
        if nursery is None:
            if isinstance(for_task, SyncContextTask):
                if for_task.is_trio_thread:
                    # If it's a trio thread, we want to inherit the
                    # value from the task that started the thread
                    inherited_value = trio.from_thread.run_sync(self.get)
                else:
                    # If it's a kernel thread, there's no inherited value
                    # because a thread always have an empty context object.
                    inherited_value = MISSING
            else:
                # root trio task doesn't have a parent nursery
                # root "init" task doesn't have a parent nursery
                try:
                    # Try to get the latest state from the sync context
                    sync_context_state = self.get_current_sync_context_task().context[
                        self._cvar
                    ]
                    # There's no notion of 'value_for_children' in sync context.
                    # Whatever value is set for the sync task is the value
                    # that needs to be inherited to the async context.
                    inherited_value = sync_context_state.value_for_task
                except (KeyError, LookupError):
                    # This TreeVar hasn't yet been used in the sync context.
                    # Initialize it to MISSING.
                    inherited_value = MISSING
        else:
            parent_state = self._fetch(nursery.parent_task, current_task)
            inherited_value = parent_state.value_for_children.get(
                nursery, parent_state.value_for_task
            )
        new_state = _TreeVarState[T](weakref.ref(for_task), inherited_value)
        if current_task is None:
            # If no current_task was provided, then we're being called
            # from get_in() and should not cache the intermediate
            # values in case we're in a different thread where
            # context.run() might fail.
            pass
        elif isinstance(for_task, SyncContextTask):
            for_task.context.run(self._cvar.set, new_state)
        else:
            if for_task.context is current_task.context:
                self._cvar.set(new_state)
            else:
                for_task.context.run(self._cvar.set, new_state)
        return new_state

    def get_current_sync_context_task(self) -> SyncContextTask:
        """Get the 'task' for the current sync context."""
        non_trio_thread_message = (
            "this thread wasn't created by Trio, pass kwarg trio_token=..."
        )
        sync_context_task: SyncContextTask
        try:
            # Try calling from_thread
            trio.from_thread.run_sync(lambda: None)
        except RuntimeError as exc:
            if str(exc) == non_trio_thread_message:
                # If it fails, we're in a non-trio thread
                try:
                    # Try to get the previously-set sync context task for this thread
                    sync_context_task = data_per_thread.sync_context_task
                except AttributeError:
                    # If we get an AttributeError, this is the first time
                    # sync context task is retrieved for this thread
                    data_per_thread.sync_context_task = SyncContextTask(
                        is_trio_thread=False
                    )
                    sync_context_task = data_per_thread.sync_context_task
            else:
                raise exc
        else:
            try:
                # Try to get the previously-set sync context task for this thread
                sync_context_task = data_per_thread.sync_context_task
            except AttributeError:
                # If we get an AttributeError, this is the first time
                # sync context task is retrieved for this thread
                data_per_thread.sync_context_task = SyncContextTask(is_trio_thread=True)
                sync_context_task = data_per_thread.sync_context_task
        return sync_context_task

    def get_current_task(self) -> TaskLike:
        sync_context_error_message = "must be called from async context"
        try:
            trio.current_time()
        except RuntimeError as e:
            # If this fails, we're in a fully sync context
            if str(e) == sync_context_error_message:
                return self.get_current_sync_context_task()
            raise e
        else:
            try:
                current_task = trio.lowlevel.current_task()
            except RuntimeError as e:
                # If trio.current_time works but current_task fails,
                # there is an active run but no active task.
                # This state is observable primarily in instruments,
                # end-of-run async generator finalizers, and some abort_fn callbacks.
                if str(e) == sync_context_error_message:
                    root_task = trio.lowlevel.current_root_task()
                    assert root_task
                    return root_task
                raise e
            else:
                # If both works, we're in a normal async context
                return current_task

    @overload
    def get(self) -> T:
        ...

    @overload
    def get(self, default: U) -> Union[T, U]:
        ...

    def get(self, default: U = MISSING) -> Union[T, U]:
        this_task = self.get_current_task()
        state = self._fetch(this_task, this_task)
        if state.value_for_task is not MISSING:
            return state.value_for_task
        elif default is not MISSING:
            return default
        elif self._default is not MISSING:
            return self._default
        else:
            raise LookupError(self)

    def set(self, value: T) -> TreeVarToken[T]:
        this_task = self.get_current_task()
        state = self._fetch(this_task, this_task)
        state.save_current_for_children()
        prev_value, state.value_for_task = state.value_for_task, value
        return TreeVarToken(self, prev_value, this_task.context)

    def reset(self, token: TreeVarToken[T]) -> None:
        this_task = self.get_current_task()
        if token._context is not this_task.context:
            raise ValueError(f"{token!r} was created in a different Context")
        state = self._fetch(this_task, this_task)
        state.save_current_for_children()
        state.value_for_task = token.old_value

    @contextmanager
    def being(self, value: T) -> Iterator[None]:
        """Returns a context manager which sets the value of this `TreeVar` to
        *value* upon entry and restores its previous value upon exit.
        """
        token = self.set(value)
        try:
            yield
        finally:
            self.reset(token)

    @overload
    def get_in(self, task_or_nursery: Union[trio.lowlevel.Task, trio.Nursery]) -> T:
        ...

    @overload
    def get_in(
        self, task_or_nursery: Union[trio.lowlevel.Task, trio.Nursery], default: U
    ) -> Union[T, U]:
        ...

    def get_in(
        self,
        task_or_nursery: Union[trio.lowlevel.Task, trio.Nursery],
        default: U = MISSING,
    ) -> Union[T, U]:
        """Gets the value of this `TreeVar` in the given
        `trio.lowlevel.Task` or `~trio.Nursery`.

        The value in a task is the value that would be returned by a
        call to :meth:`~contextvars.ContextVar.get` in that task. The
        value in a nursery is the value that would be returned by
        :meth:`~contextvars.ContextVar.get` at the beginning of a new
        child task started in that nursery. The *default* argument has
        the same semantics as it does for :meth:`~contextvars.ContextVar.get`.
        """
        task: TaskLike
        if isinstance(task_or_nursery, trio.Nursery):
            task = task_or_nursery.parent_task
        else:
            task = task_or_nursery
        state = self._fetch(for_task=task, current_task=None)
        if task is task_or_nursery:
            result = state.value_for_task
        else:
            assert isinstance(task_or_nursery, trio.Nursery)
            result = state.value_for_children.get(task_or_nursery, state.value_for_task)
        if result is not MISSING:
            return result
        elif default is not MISSING:
            return default
        elif self._default is not MISSING:
            return self._default
        else:
            raise LookupError(self)
