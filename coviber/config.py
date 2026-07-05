"""Shared settings-file parsing — one parser for the CLI and the MCP server.

Kept dependency-free: YAML support piggybacks on pyyaml only when the file is
actually YAML (any extra that needs it, e.g. [scrape], pulls it in).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def read_config(path: str) -> dict:
    """Read a YAML/JSON settings file into a plain dict (`~` is expanded)."""
    p = Path(path).expanduser()
    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            sys.exit("YAML config needs pyyaml: pip install pyyaml")
        return yaml.safe_load(text) or {}
    return json.loads(text)
