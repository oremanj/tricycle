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
