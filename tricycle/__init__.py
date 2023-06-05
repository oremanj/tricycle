from ._version import __version__

from ._rwlock import RWLock as RWLock
from ._streams import (
    BufferedReceiveStream as BufferedReceiveStream,
    TextReceiveStream as TextReceiveStream,
)
from ._multi_cancel import MultiCancelScope as MultiCancelScope
from ._service_nursery import open_service_nursery as open_service_nursery
from ._meta import ScopedObject as ScopedObject, BackgroundObject as BackgroundObject
from ._tree_var import TreeVar as TreeVar, TreeVarToken as TreeVarToken

# watch this space...

_export = None
for _export in globals().values():
    if hasattr(_export, "__module__"):
        _export.__module__ = __name__
del _export
