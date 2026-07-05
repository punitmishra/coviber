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

# Signal weights: today's hardcoded values, now overridable in config.
# Keeping this defaults dict frozen (via `dict(...)` copies in Config) so a
# caller mutating .weights on one Config doesn't poison every subsequent one.
# Max achievable at defaults = 11 (non-age signals) + 3 (max age tier) = 14 —
# the contract U(r) ∈ [0, 14] pinned by test_urgency_contract.
DEFAULT_WEIGHTS = {
    "mention": 3,          # @you in body
    "priority_sender": 2,  # from a manager / VIP
    "action_word": 2,      # DEFAULT_ACTION_WORDS hit
    "question": 1,         # '?' in body
    "unread": 1,           # Record.unread
    "no_reply": 1,         # threaded and not replied
    "collaborator": 1,     # known collaborator
    "age_7d": 3,           # age > 7 days
    "age_48h": 2,          # age > 48 h
    "age_24h": 1,          # age > 24 h
}


@dataclass
class Config:
    you: str = "you"
    priority_senders: set = None      # managers / VIPs
    collaborators: set = None         # known collaborators
    action_words: set = None
    skip_senders: set = None
    skip_subjects: set = None
    weights: dict = None              # per-signal weights (see DEFAULT_WEIGHTS)

    def __post_init__(self):
        # `is None` guards so an explicit empty set/list from config is
        # honored as an opt-out; only genuinely-unset fields fall back to
        # defaults (audit finding L5/#18, L2/#22 landed the pipeline half).
        self.priority_senders = {s.lower() for s in (
            self.priority_senders if self.priority_senders is not None else set()
        )}
        self.collaborators = {s.lower() for s in (
            self.collaborators if self.collaborators is not None else set()
        )}
        self.action_words = (
            self.action_words if self.action_words is not None else set(DEFAULT_ACTION_WORDS)
        )
        self.skip_senders = {s.lower() for s in (
            self.skip_senders if self.skip_senders is not None else DEFAULT_SKIP_SENDERS
        )}
        self.skip_subjects = {s.lower() for s in (
            self.skip_subjects if self.skip_subjects is not None else DEFAULT_SKIP_SUBJECTS
        )}
        # Partial-dict merge: user-supplied weights override defaults key-by-
        # key, so a config that only tweaks {"unread": 0} keeps every other
        # default. Unknown keys are surfaced (finding L5/#20); non-int values
        # get a diagnostic naming the offending key (finding L5/#19).
        merged = dict(DEFAULT_WEIGHTS)
        if self.weights:
            unknown = set(self.weights) - set(merged)
            if unknown:
                import warnings
                warnings.warn(
                    f"coviber urgency: unknown weight key(s) ignored: {sorted(unknown)}. "
                    f"Known keys: {sorted(merged)}",
                    RuntimeWarning, stacklevel=3,
                )
            for k, v in self.weights.items():
                if k not in merged:
                    continue
                try:
                    merged[k] = int(v)
                except (TypeError, ValueError) as e:
                    raise ValueError(
                        f"coviber urgency: weight for key '{k}' must be an integer, "
                        f"got {v!r}: {e}"
                    ) from e
        self.weights = merged

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
            weights=d.get("weights") or None,
        )


def should_skip(r: Record, cfg: Config) -> Optional[str]:
    sender = (r.from_name or "").lower()
    subject = (r.subject or "").lower()
    blob = f"{subject} {(r.text or '').lower()}"
    # token-boundary match: "acme-ci-bot" skips, a colleague named "Abbott" doesn't
    if any(re.search(rf"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])", sender) for s in cfg.skip_senders):
        return "skip-sender"
    if any(s in subject for s in cfg.skip_subjects):
        return "skip-subject"
    # FYI phrases must match on token boundaries, not bare substring: "fyi"
    # inside "justifying" / "notifying" / "typify" is a false-positive skip
    # that would silently drop legitimate obligations (audit finding L5/#16).
    if any(re.search(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", blob) for f in DEFAULT_FYI):
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
    """Return (urgency in [0, MAX_URGENCY], list of signals fired).

    At default weights this is [0, 14] — the documented contract, pinned by
    the test_urgency_contract suite. Custom weights change the ceiling; a
    weight of 0 disables the signal (it never fires, never labels).
    """
    signals: list[str] = []
    text = (r.text or "")
    blob = f"{(r.subject or '')} {text}".lower()
    w = cfg.weights
    u = 0

    def fire(key: str, label: str):
        nonlocal u
        weight = w.get(key, 0)
        if weight <= 0:
            return
        u += weight
        signals.append(f"{label}+{weight}")

    # cfg.you=="" would collapse the regex to `@\b`, matching every email
    # address and every raw '@' — false-positive mentions on essentially
    # everything. Guard explicitly (audit finding L5/#17).
    if cfg.you and re.search(rf"@{re.escape(cfg.you)}\b", text, re.I):
        fire("mention", "@mention")
    if (r.from_name or "").lower() in cfg.priority_senders:
        fire("priority_sender", "priority-sender")
    if any(word in blob for word in cfg.action_words):
        fire("action_word", "action-word")
    if "?" in text:
        fire("question", "question")
    if r.unread:
        fire("unread", "unread")
    if r.thread_id and not r.replied:
        fire("no_reply", "no-reply")
    if (r.from_name or "").lower() in cfg.collaborators:
        fire("collaborator", "collaborator")
    age = _age_hours(r)
    if age > 24 * 7:
        fire("age_7d", "age>7d")
    elif age > 48:
        fire("age_48h", "age>48h")
    elif age > 24:
        fire("age_24h", "age>24h")
    # Ceiling is defaults' max (14) — a config that raises weights above the
    # default sum still gets clamped, keeping the [0, 14] contract for anyone
    # who hasn't opted into custom weights.
    return u, signals


def triage(records, cfg: Config) -> list[dict]:
    """Filter (self-authored + skip + zero-signal), score, and sort. Highest urgency first."""
    out = []
    you = (cfg.you or "").lower()
    for r in records:
        if (r.from_name or "").lower() == you:
            continue  # your own sent messages are not obligations
        reason = should_skip(r, cfg)
        if reason:
            continue
        u, sig = score(r, cfg)
        if u <= 0:
            continue
        out.append({"record": r, "urgency": u, "signals": sig})
    out.sort(key=lambda t: (-t["urgency"], t["record"].ts))
    return out
