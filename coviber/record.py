"""Canonical record schema — the one shape every loader produces."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ts(s: str) -> str:
    """Best-effort ts → ISO-8601 UTC, so lexicographic order == chronological.

    Tries ISO (with the 'Z' shim — 3.9's fromisoformat can't parse 'Z'), then
    RFC-2822 (email Date:), then epoch seconds (sanity range ~1990–2100).
    Naive datetimes are assumed UTC; aware ones converted via astimezone so
    mixed-offset inputs still order correctly. Unparseable input passes through.

    Non-string inputs (int/float epoch, bool, None) are coerced via str() —
    the JSONL loader and hand-edited records.jsonl can both produce these,
    and a raw AttributeError from `.strip()` would brick the whole store on
    the next read.
    """
    s = str(s or "").strip()
    if not s:
        return s
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(s)  # TypeError pre-3.10 on bad input
        except (TypeError, ValueError):
            try:
                epoch = float(s)
                if 631152000 <= epoch <= 4102444800:  # 1990-01-01 .. 2100-01-01
                    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            except ValueError:
                pass
    if dt is None:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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
        self.ts = _normalize_ts(self.ts)  # not part of the id hash

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})
