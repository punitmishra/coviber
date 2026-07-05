"""WorkGraph — cross-source entity graph (Whitepaper §3.4, Algorithm 4).

Unifies people, projects, channels, and tickets from the record stream into a
queryable structure. `known_projects` and the ticket regex are config-driven, so
nothing company-specific is hardcoded.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from .record import Record

# Generic ticket / PR / issue identifiers: ABC-1234, PR #12, #4567
# (the bare-# branch needs a lookbehind — \b can't sit between whitespace and '#')
DEFAULT_TICKET_RE = re.compile(r"(\b[A-Z][A-Z0-9]+-\d+\b|\bPR\s*#\d+\b|(?<![\w#])#\d{3,}\b)")
# lookbehind rejects email addresses; the tail can't end in '.' or '-'
MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?)")


class WorkGraph:
    def __init__(self, known_projects: Iterable[str] | None = None, ticket_re=None, you: str = "you"):
        self.known_projects = [p for p in (known_projects or [])]
        self.ticket_re = ticket_re or DEFAULT_TICKET_RE
        self.you = you
        self.people: dict[str, dict] = defaultdict(lambda: _node(["platforms", "projects", "channels"]))
        self.projects: dict[str, dict] = defaultdict(lambda: _node(["people", "channels", "tickets"]))
        self.channels: dict[str, dict] = defaultdict(lambda: _node(["people", "projects"]))
        self.tickets: dict[str, dict] = defaultdict(lambda: _node(["people", "projects"]))

    def ingest(self, records: Iterable[Record]):
        for r in records:
            self._ingest_one(r)

    def _ingest_one(self, r: Record):
        blob = f"{r.subject} {r.text}"
        you = self.you.lower()
        people = set(filter(None, [r.from_name, r.recipient]))
        people |= set(MENTION_RE.findall(r.text))
        people = {p for p in people if p.lower() != you}
        projects = {p for p in self.known_projects if p.lower() in blob.lower()}
        channels = {r.channel} if r.channel else set()
        tickets = {m if isinstance(m, str) else m[0] for m in self.ticket_re.findall(f"{blob} {r.url}")}

        for person in people:
            n = self.people[person]
            n["platforms"].add(r.source)
            n["projects"] |= projects
            n["channels"] |= channels
            n["interaction_count"] += 1
            n["last_seen"] = max(n.get("last_seen", ""), r.ts)
        for project in projects:
            n = self.projects[project]
            n["people"] |= people
            n["channels"] |= channels
            n["tickets"] |= tickets
            n["mentions"] += 1
        for ch in channels:
            self.channels[ch]["people"] |= people
            self.channels[ch]["projects"] |= projects
        for tk in tickets:
            self.tickets[tk]["people"] |= people
            self.tickets[tk]["projects"] |= projects

    # --- queries ---
    def person(self, name: str) -> dict:
        return _serialize(self.people.get(name, {}))

    def project(self, name: str) -> dict:
        return _serialize(self.projects.get(name, {}))

    def summary(self) -> dict:
        return {
            "people": len(self.people), "projects": len(self.projects),
            "channels": len(self.channels), "tickets": len(self.tickets),
            "top_people": sorted(self.people, key=lambda p: -self.people[p]["interaction_count"])[:10],
            "projects_list": sorted(self.projects),
        }

    def to_dict(self) -> dict:
        return {
            "people": {k: _serialize(v) for k, v in self.people.items()},
            "projects": {k: _serialize(v) for k, v in self.projects.items()},
            "channels": {k: _serialize(v) for k, v in self.channels.items()},
            "tickets": {k: _serialize(v) for k, v in self.tickets.items()},
        }


def _node(set_fields):
    d = {f: set() for f in set_fields}
    d["interaction_count"] = 0
    d["mentions"] = 0
    d["last_seen"] = ""
    return d


def _serialize(node: dict) -> dict:
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in node.items()}
