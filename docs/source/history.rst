Release history
===============

.. currentmodule:: tricycle

.. towncrier release notes start

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
