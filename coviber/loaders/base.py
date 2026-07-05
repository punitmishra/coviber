"""The Loader interface — the swappable seam.

A Loader turns *any* source of professional context (an email inbox, a Slack
export, a web page, a JSONL dump, an API) into a stream of canonical `Record`s.
The rest of CoViber (dedup → WorkGraph → urgency → search) is loader-agnostic.

To add a source, subclass `Loader`, implement `load()`, and register it:

    from coviber.loaders import register

    @register("myapp")
    class MyAppLoader(Loader):
        def load(self):
            for row in fetch_my_app(self.config):
                yield Record(source="myapp", subject=row["title"], text=row["body"])
"""
from __future__ import annotations

from typing import Iterable, Iterator

from ..record import Record


class Loader:
    """Base class for all information loaders.

    `config` is a plain dict (usually a block from the YAML/CLI). Loaders should
    validate what they need in `__init__` and stream records lazily from `load()`.
    """

    #: short, unique name used in config (`loader: <name>`) and the registry.
    name: str = "base"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def load(self) -> Iterable[Record]:  # pragma: no cover - interface
        raise NotImplementedError(f"{type(self).__name__}.load() not implemented")

    def __iter__(self) -> Iterator[Record]:
        return iter(self.load())
