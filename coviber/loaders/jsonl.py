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
        with path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from e
                if not isinstance(obj, dict):
                    raise ValueError(f"{path}:{lineno}: expected a JSON object, got {type(obj).__name__}")
                obj["source"] = obj.get("source") or default_source  # also catches explicit null
                yield Record.from_dict(obj)
