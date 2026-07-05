"""Multi-signal urgency scoring + skip filter (Whitepaper §3.5, Definition 4).

De-proprietized: the priority senders, action words, and skip rules are all
config-driven — nothing about any specific company is baked in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .record import Record

DEFAULT_ACTION_WORDS = {
    "please", "can you", "could you", "need", "review", "approve", "sign-off",
    "sign off", "blocked", "blocker", "decision", "decide", "deadline", "asap",
    "urgent", "waiting on", "action required", "todo", "follow up", "confirm",
}
DEFAULT_SKIP_SENDERS = {"noreply", "no-reply", "newsletter", "notifications", "alerts", "bot"}
DEFAULT_SKIP_SUBJECTS = {"weekly digest", "status update", "[internal]", "out of office"}
DEFAULT_FYI = {"fyi", "no action needed", "no reply needed", "just so you know"}


@dataclass
class Config:
    you: str = "you"
    priority_senders: set = None      # managers / VIPs -> +2
    collaborators: set = None         # known collaborators -> +1
    action_words: set = None
    skip_senders: set = None
    skip_subjects: set = None

    def __post_init__(self):
        self.priority_senders = {s.lower() for s in (self.priority_senders or set())}
        self.collaborators = {s.lower() for s in (self.collaborators or set())}
        self.action_words = self.action_words or set(DEFAULT_ACTION_WORDS)
        self.skip_senders = {s.lower() for s in (self.skip_senders or DEFAULT_SKIP_SENDERS)}
        self.skip_subjects = {s.lower() for s in (self.skip_subjects or DEFAULT_SKIP_SUBJECTS)}

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        d = d or {}
        return cls(
            you=d.get("you", "you"),
            priority_senders=set(d.get("priority_senders", [])),
            collaborators=set(d.get("collaborators", [])),
            action_words=set(d["action_words"]) if d.get("action_words") else None,
            skip_senders=set(d["skip_senders"]) if d.get("skip_senders") else None,
            skip_subjects=set(d["skip_subjects"]) if d.get("skip_subjects") else None,
        )


def should_skip(r: Record, cfg: Config) -> Optional[str]:
    sender = (r.from_name or "").lower()
    subject = (r.subject or "").lower()
    blob = f"{subject} {(r.text or '').lower()}"
    if any(s in sender for s in cfg.skip_senders):
        return "skip-sender"
    if any(s in subject for s in cfg.skip_subjects):
        return "skip-subject"
    if any(f in blob for f in DEFAULT_FYI):
        return "fyi"
    return None


def _age_hours(r: Record) -> float:
    try:
        t = datetime.fromisoformat(r.ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return 0.0


def score(r: Record, cfg: Config) -> tuple[int, list[str]]:
    """Return (urgency in [0,15], list of signals fired)."""
    signals: list[str] = []
    text = (r.text or "")
    blob = f"{(r.subject or '')} {text}".lower()
    u = 0
    if re.search(rf"@{re.escape(cfg.you)}\b", text, re.I):
        u += 3; signals.append("@mention+3")
    if (r.from_name or "").lower() in cfg.priority_senders:
        u += 2; signals.append("priority-sender+2")
    if any(w in blob for w in cfg.action_words):
        u += 2; signals.append("action-word+2")
    if "?" in text:
        u += 1; signals.append("question+1")
    if r.unread:
        u += 1; signals.append("unread+1")
    if r.thread_id and not r.replied:
        u += 1; signals.append("no-reply+1")
    if (r.from_name or "").lower() in cfg.collaborators:
        u += 1; signals.append("collaborator+1")
    age = _age_hours(r)
    if age > 24 * 7:
        u += 3; signals.append("age>7d+3")
    elif age > 48:
        u += 2; signals.append("age>48h+2")
    elif age > 24:
        u += 1; signals.append("age>24h+1")
    return min(u, 15), signals


def triage(records, cfg: Config) -> list[dict]:
    """Filter (skip + zero-signal), score, and sort. Highest urgency first."""
    out = []
    for r in records:
        reason = should_skip(r, cfg)
        if reason:
            continue
        u, sig = score(r, cfg)
        if u <= 0:
            continue
        out.append({"record": r, "urgency": u, "signals": sig})
    out.sort(key=lambda t: (-t["urgency"], t["record"].ts))
    return out
