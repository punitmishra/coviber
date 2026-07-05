"""Canonical record schema — the one shape every loader produces."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(*parts: str) -> str:
    # \x1f separator keeps field boundaries unambiguous ("ab"+"c" != "a"+"bc");
    # usedforsecurity=False keeps FIPS-mode Pythons happy (md5 is only a dedup key).
    data = "\x1f".join(p or "" for p in parts).encode("utf-8")
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


@dataclass
class Record:
    """A single unit of context, produced by any Loader.

    Only `text` or `subject` is really needed; everything else enriches the
    knowledge graph and urgency scoring. `id` is content-derived so re-loading
    the same item de-dupes naturally (see Store.upsert).
    """
    source: str                       # loader name / platform, e.g. "email", "slack", "demo"
    text: str = ""                    # message body / content
    subject: str = ""                 # title / subject line
    from_name: str = ""               # sender display name
    recipient: str = ""               # primary recipient (usually "you")
    channel: str = ""                 # sub-view: dm, mentions, inbox, #general, repo, ...
    url: str = ""                     # deep link if available
    ts: str = ""                      # event timestamp (ISO8601 if known)
    unread: bool = False
    thread_id: str = ""               # for no-reply detection
    replied: bool = False             # has the user replied in this thread?
    scraped_at: str = field(default_factory=_now)
    id: str = ""                      # content hash; minted if empty

    def __post_init__(self):
        if not self.id:
            self.id = _hash(self.text, self.subject, self.from_name, self.source)
        if not self.ts:
            self.ts = self.scraped_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})
