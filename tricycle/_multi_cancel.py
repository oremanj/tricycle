import attr
import trio
import weakref
from typing import Iterator, MutableSet, Optional


@attr.s(eq=False, repr=False)
class MultiCancelScope:
    r"""Manages a dynamic set of :class:`trio.CancelScope`\s that can be
    shielded and cancelled as a unit.

    New cancel scopes are added to the managed set using
    :meth:`open_child`, which returns the child scope so you can enter
    it with a ``with`` statement. Calls to :meth:`cancel` and changes
    to :attr:`shield` apply to all existing children and set the
    initial state for future children. Each child scope has its own
    :attr:`~trio.CancelScope.deadline` and :attr:`~trio.CancelScope.shield`
    attributes; changes to these do not modify the parent.

    There is no :attr:`~trio.CancelScope.cancelled_caught` attribute
    on :class:`MultiCancelScope` because it would be ambiguous; some
    of the child scopes might exit via a :exc:`trio.Cancelled`
    exception and others not. Look at the child :class:`trio.CancelScope`
    if you want to see whether it was cancelled or not.
    """

    _child_scopes: MutableSet[trio.CancelScope] = attr.ib(
        factory=weakref.WeakSet, init=False
    )
    _shield: bool = attr.ib(default=False, kw_only=True)
    _cancel_called: bool = attr.ib(default=False, kw_only=True)

    def __repr__(self) -> str:
        descr = ["MultiCancelScope"]
        if self._shield:
            descr.append(" shielded")
        if self._cancel_called:
            descr.append(" cancelled")
        return f"<{''.join(descr)}: {list(self._child_scopes)}>"

    @property
    def cancel_called(self) -> bool:
        """Returns true if :meth:`cancel` has been called."""
        return self._cancel_called

    @property
    def shield(self) -> bool:
        """The overall shielding state for this :class:`MultiCancelScope`.

        Setting this attribute sets the :attr:`~trio.CancelScope.shield`
        attribute of all children, as well as the default initial shielding
        for future children. Individual children may modify their
        shield state to be different from the parent value, but further
        changes to the parent :attr:`MultiCancelScope.shield` will override
        their local choice.
        """
        return self._shield

    @shield.setter
    def shield(self, new_value: bool) -> None:
        self._shield = new_value
        for scope in self._child_scopes:
            scope.shield = new_value

    def cancel(self) -> None:
        """Cancel all child cancel scopes.

        Additional children created after a call to :meth:`cancel` will
        start out in the cancelled state.
        """
        if not self._cancel_called:
            for scope in self._child_scopes:
                scope.cancel()
            self._cancel_called = True

    def open_child(self, *, shield: Optional[bool] = None) -> trio.CancelScope:
        """Return a new child cancel scope.

        The child will start out cancelled if the parent
        :meth:`cancel` method has been called. Its initial shield state
        is given by the ``shield`` argument, or by the parent's
        :attr:`shield` attribute if the ``shield`` argument is not specified.
        """
        if shield is None:
            shield = self._shield
        new_scope = trio.CancelScope(shield=shield)
        if self._cancel_called:
            new_scope.cancel()
        self._child_scopes.add(new_scope)
        return new_scope
