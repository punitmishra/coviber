"""CoViber — a local-first continuous context replica for AI-augmented knowledge work.

Swap the Loader, keep the brain: any source of professional context becomes a
queryable work graph + prioritized obligation queue + semantic memory, exposed
to an LLM locally.
"""
from .record import Record
from .pipeline import Settings, ingest, build_queue
from .workgraph import WorkGraph
from .store import Store
from .loaders import get_loader, register, available

__version__ = "0.1.0"
__all__ = [
    "Record", "Settings", "ingest", "build_queue",
    "WorkGraph", "Store", "get_loader", "register", "available",
]
