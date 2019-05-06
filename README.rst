tricycle: experimental extensions for Trio
==========================================

This is a library of interesting-but-maybe-not-yet-fully-proven extensions to
`Trio <https://github.com/python-trio/trio>`__, the Pythonic async I/O library
(for humans and snake people).

While we won't release known-broken code, and we strive for
cleanliness and good test coverage, please be advised that
``tricycle`` is mostly one person's box of tools that seemed like a
good idea at the time, and should be treated with according skepticism
if you're contemplating using it in production. It hasn't necessarily
been reviewed or tested to Trio's standards, it supports at minimum
Python 3.6, and some features might not be available on PyPy or on
Windows.

* If you find that it meets your needs, you're welcome to use it. We'll
  endeavor to provide a (short) deprecation period on API changes, but
  no guarantees on that yet.

* If you find that it doesn't meet your needs, feel free to `let us know
  <https://github.com/oremanj/tricycle/issues>`__, but don't say you
  weren't warned. :-)

Currently we have:

* a readers-writer lock (`tricycle.RWLock`)
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
