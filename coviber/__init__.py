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

# Read the version from installed package metadata so it always tracks
# pyproject.toml. Falls back to "0+unknown" for editable / not-installed
# use cases (running tests from a fresh checkout without `pip install -e .`).
# Single source of truth: pyproject.toml.
try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    try:
        __version__ = _pkg_version("coviber")
    except PackageNotFoundError:
        __version__ = "0+unknown"
except ImportError:  # 3.7 backport, not exercised at our 3.9+ floor but harmless
    __version__ = "0+unknown"

__all__ = [
    "Record", "Settings", "ingest", "build_queue",
    "WorkGraph", "Store", "get_loader", "register", "available",
]
