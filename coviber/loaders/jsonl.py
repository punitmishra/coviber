"""JSONL loader — the universal escape hatch.

Point it at a `.jsonl` file where each line is an object with any subset of the
Record fields. Dump your Slack export, an email mbox conversion, a CSV→json, a
DB query — anything — into JSONL and CoViber ingests it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..record import Record
from . import register
from .base import Loader


@register("jsonl")
class JsonlLoader(Loader):
    """config: {"path": "data.jsonl", "source": "optional override"}"""

    def load(self) -> Iterable[Record]:
        path = Path(self.config.get("path", "")).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"jsonl loader: no file at {path}")
        default_source = self.config.get("source", "jsonl")
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                obj.setdefault("source", default_source)
                yield Record.from_dict(obj)
