"""Slack export loader — ingest a standard workspace export (the zip, extracted).

Point it at the directory Slack's export unzips to: `users.json` at the root
and one dir per channel holding `YYYY-MM-DD.json` day files. Pure stdlib,
nothing leaves your machine.

    loader: slackexport
    config:
      path: ~/slack-export       # export root (required)
      source: slack              # Record.source (default "slack")
      channels: [general, dev]   # optional channel-name filter
      you: Margaret Chen         # your display name or user id -> replied detection
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..record import Record
from . import register
from .base import Loader

_SKIP_SUBTYPES = {"channel_join", "channel_leave", "bot_message"}
_MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


def _iso(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def _users(root: Path) -> dict:
    path = root / "users.json"
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}  # tolerate a broken users.json: raw ids still work
    out = {}
    for u in entries if isinstance(entries, list) else []:
        if not isinstance(u, dict):
            continue
        prof = u.get("profile") or {}
        name = prof.get("display_name") or prof.get("real_name") or u.get("real_name") or u.get("name")
        if u.get("id") and name:
            out[u["id"]] = name
    return out


def _day(path: Path) -> list:
    try:
        msgs = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: invalid JSON: {e}") from e
    if not isinstance(msgs, list):
        raise ValueError(f"{path}: expected an array of messages")
    return [m for m in msgs if isinstance(m, dict)]


@register("slackexport")
class SlackExportLoader(Loader):
    """config: {"path": export root, "source", "channels": [names], "you": display name or user id}"""

    def load(self) -> Iterable[Record]:
        root = Path(self.config.get("path", "")).expanduser()
        if not root.is_dir():
            raise FileNotFoundError(f"slackexport loader: no export directory at {root}")
        source = self.config.get("source", "slack")
        wanted = {c.lstrip("#") for c in self.config.get("channels") or []}
        users = _users(root)
        you = self.config.get("you", "")
        you_ids = ({you} | {uid for uid, name in users.items() if name == you}) if you else set()

        for chan in sorted(p for p in root.iterdir() if p.is_dir()):
            if wanted and chan.name not in wanted:
                continue
            msgs = [m for day in sorted(chan.glob("*.json")) for m in _day(day)]
            replied = {m["thread_ts"] for m in msgs if m.get("thread_ts") and m.get("user") in you_ids}
            for m in msgs:
                if m.get("subtype") in _SKIP_SUBTYPES:
                    continue
                text = _MENTION_RE.sub(lambda mt: "@" + users.get(mt.group(1), mt.group(1)), m.get("text") or "")
                if not text.strip():
                    continue
                uid = m.get("user") or ""
                thread = m.get("thread_ts") or ""
                yield Record(source=source, text=text, from_name=users.get(uid, uid),
                             channel=f"#{chan.name}", ts=_iso(m.get("ts")),
                             thread_id=thread, replied=thread in replied)
