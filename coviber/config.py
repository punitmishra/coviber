"""Shared settings-file parsing — one parser for the CLI and the MCP server.

Kept dependency-free: YAML support piggybacks on pyyaml only when the file is
actually YAML (any extra that needs it, e.g. [scrape], pulls it in).
"""
from __future__ import annotations

import json
from pathlib import Path


class ConfigError(Exception):
    """Raised on unreadable / unparseable / missing-dep settings files.

    The CLI catches this and exits with a friendly message; the MCP server
    lets it propagate so FastMCP converts it into a per-tool error instead
    of killing the whole server on a bad config.
    """


def read_config(path: str) -> dict:
    """Read a YAML/JSON settings file into a plain dict (`~` is expanded).

    Raises ConfigError with the path in the message on any failure.
    """
    p = Path(path).expanduser()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"config file {p}: {e}") from e
    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ConfigError(
                f"config file {p}: YAML support needs pyyaml (pip install pyyaml)"
            ) from e
        try:
            return yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"config file {p}: invalid YAML: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file {p}: invalid JSON: {e}") from e
