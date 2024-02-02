tricycle: miscellaneous extensions for Trio
===========================================

.. image:: https://img.shields.io/pypi/v/tricycle.svg
   :target: https://pypi.org/project/tricycle
   :alt: Latest PyPI version

.. image:: https://github.com/oremanj/tricycle/actions/workflows/ci.yml/badge.svg
   :target: https://github.com/oremanj/tricycle/actions/workflows/ci.yml
   :alt: Automated test status

.. image:: https://img.shields.io/badge/docs-read%20now-blue.svg
   :target: https://tricycle.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation status

.. image:: https://codecov.io/gh/oremanj/tricycle/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/oremanj/tricycle
   :alt: Test coverage

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/ambv/black
   :alt: Code style: black

.. image:: http://www.mypy-lang.org/static/mypy_badge.svg
   :target: http://www.mypy-lang.org/
   :alt: Checked with mypy


This is a library of extensions to `Trio
<https://github.com/python-trio/trio>`__, the friendly Python library
for async concurrency and I/O.

Currently we have:

* a readers-writer lock (``tricycle.RWLock``)
* slightly higher-level stream wrappers (``tricycle.BufferedReceiveStream``
  and ``tricycle.TextReceiveStream``)
* some tools for managing cancellation (``tricycle.open_service_nursery()``
  and ``tricycle.MultiCancelScope``)
* a way to make objects that want to keep background tasks running during the
  object's lifetime (``tricycle.BackgroundObject`` and the more general
  ``tricycle.ScopedObject``)
* an analog of ``ContextVar`` that is inherited through the task tree rather
  than across ``start_soon()`` calls, and thus provides more safety for
  accessing a resource that is being managed by a parent task
  (``tricycle.TreeVar``)

While we won't release known-broken code, and we strive for
cleanliness and good test coverage, please be advised that
``tricycle`` is mostly one person's box of tools and has not necessarily
been reviewed or tested to Trio's standards. It *is* being used in
production, and API churn has been minimal thus far although we're not
making any firm stability guarantees. If you find that it doesn't meet
your needs, feel free to `let us know
<https://github.com/oremanj/tricycle/issues>`__ and we'll endeavor to
improve things.

tricycle is tested on Linux, Windows, and macOS, on CPython versions 3.8
through 3.12. It will probably work on PyPy as well.


License and history
~~~~~~~~~~~~~~~~~~~

``tricycle`` is licensed under your choice of the MIT or Apache 2.0 license.
See `LICENSE <https://github.com/oremanj/tricycle/blob/master/LICENSE>`__
for details.

This library has its origins in a package of utilities that the author
wrote at `Hudson River Trading <http://www.hudson-trading.com/>`__
while building things for them with Trio. Many thanks to HRT for
supporting open source in this way!
