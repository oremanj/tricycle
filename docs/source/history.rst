Release history
===============

.. currentmodule:: tricycle

.. towncrier release notes start

tricycle 0.4.1 (2024-02-02)
---------------------------

* :func:`open_service_nursery` no longer assumes that ``TaskStatus.started()``
  will be called from inside the task that was just started. This restores
  feature parity with regular Trio nurseries, which allow ``started()`` to be
  called anywhere, and fixes
  `trio-asyncio issue #135 <https://github.com/python-trio/trio-asyncio/issues/135>`__. (`#27 <https://github.com/oremanj/tricycle/issues/27>`__)

* tricycle no longer advertises itself as "experimental"; it has been around
  for more than 4 years at this point and is being used in production.


tricycle 0.4.0 (2024-01-11)
---------------------------

* tricycle now requires Python 3.8 and Trio 0.23.0 or greater.

* tricycle no longer depends on the ``trio-typing`` library, since Trio now
  has upstream support for type hints.


tricycle 0.3.0 (2023-06-05)
---------------------------

* Added `tricycle.TreeVar`, which acts like a context variable that is
  inherited at nursery creation time (and then by child tasks of that
  nursery) rather than at task creation time. :ref:`Tree variables
  <tree-variables>` are useful for providing safe 'ambient' access to a
  resource that is tied to an ``async with`` block in the parent task,
  such as an open file or trio-asyncio event loop. (`#18 <https://github.com/oremanj/tricycle/issues/18>`__)


tricycle 0.2.2 (2023-03-01)
---------------------------

* tricycle now explicitly re-exports all names, improving PEP-561 compliance and
  allowing type checkers that enforce export strictness (including mypy with
  ``--no-implicit-reexport``) to check code using tricycle.
  `#14 <https://github.com/oremanj/tricycle/issues/14>`__

tricycle 0.2.1 (2020-09-30)
---------------------------

* Update to support Trio 0.15.0 and later: rename ``trio.hazmat`` references
  to the new ``trio.lowlevel``.

tricycle 0.2.0 (2019-12-12)
---------------------------

* Add MultiCancelScope, open_service_nursery, ScopedObject, BackgroundObject.

tricycle 0.1.0 (2019-05-06)
---------------------------

* Initial release.
