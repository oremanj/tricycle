tricycle: experimental extensions for Trio
==========================================

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


This is a library of interesting-but-maybe-not-yet-fully-proven extensions to
`Trio <https://github.com/python-trio/trio>`__, the friendly Python library
for async concurrency and I/O.

While we won't release known-broken code, and we strive for
cleanliness and good test coverage, please be advised that
``tricycle`` is mostly one person's box of tools that seemed like a
good idea at the time, and should be treated with according skepticism
if you're contemplating using it in production. It hasn't necessarily
been reviewed or tested to Trio's standards, it supports at minimum
Python 3.8, and some features might not be available on PyPy or on
Windows.

* If you find that it meets your needs, you're welcome to use it. We'll
  endeavor to provide a (short) deprecation period on API changes, but
  no guarantees on that yet.

* If you find that it doesn't meet your needs, feel free to `let us know
  <https://github.com/oremanj/tricycle/issues>`__, but don't say you
  weren't warned. :-)

Currently we have:

* a readers-writer lock (``tricycle.RWLock``)
* slightly higher-level stream wrappers (``tricycle.BufferedReceiveStream``
  and ``tricycle.TextReceiveStream``)
* some tools for managing cancellation (``tricycle.open_service_nursery()``
  and ``tricycle.MultiCancelScope``)
* a way to make objects that want to keep background tasks running during the
  object's lifetime (``tricycle.BackgroundObject`` and the more general
  ``tricycle.ScopedObject``)
* [watch this space!]


License and history
~~~~~~~~~~~~~~~~~~~

``tricycle`` is licensed under your choice of the MIT or Apache 2.0 license.
See `LICENSE <https://github.com/oremanj/tricycle/blob/master/LICENSE>`__
for details.

This library has its origins in a package of utilities that the author
wrote at `Hudson River Trading <http://www.hudson-trading.com/>`__
while building things for them with Trio. Many thanks to HRT for
supporting open source in this way!
