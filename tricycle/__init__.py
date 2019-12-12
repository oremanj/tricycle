from ._version import __version__

from ._rwlock import RWLock
from ._streams import BufferedReceiveStream, TextReceiveStream
from ._multi_cancel import MultiCancelScope
from ._service_nursery import open_service_nursery
from ._meta import ScopedObject, BackgroundObject

# watch this space...

_export = None
for _export in globals().values():
    if hasattr(_export, "__module__"):
        _export.__module__ = __name__
del _export
