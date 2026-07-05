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
        # Pre-compile a word-boundary regex per known project so we don't
        # rebuild on every record. `\b` catches the natural token edges
        # (whitespace, punctuation); re.escape handles projects like "C++"
        # or ".NET". Short/common names (Go, AI, ML) previously matched as
        # substrings inside unrelated words ("going", "rail", "email") —
        # this is the whole point of audit finding L4/#12.
        self._project_patterns = [
            (p, re.compile(rf"\b{re.escape(p.lower())}\b"))
            for p in self.known_projects
        ]
        # Case-preserving display: store canonical (lowercase) key → best
        # display we've seen. `people` iteration returns the lowercase key,
        # but callers that want a pretty label can pull `display_name` off
        # the node dict.
        self.people: dict[str, dict] = defaultdict(lambda: _node(["platforms", "projects", "channels"]))
        self.projects: dict[str, dict] = defaultdict(lambda: _node(["people", "channels", "tickets"]))
        self.channels: dict[str, dict] = defaultdict(lambda: _node(["people", "projects"]))
        self.tickets: dict[str, dict] = defaultdict(lambda: _node(["people", "projects"]))

    def ingest(self, records: Iterable[Record]):
        for r in records:
            self._ingest_one(r)

    def _ingest_one(self, r: Record):
        blob = f"{r.subject} {r.text}"
        blob_lower = blob.lower()
        you = self.you.lower()

        # Person identity: normalize keys to lowercase so "Ada Byron" and
        # "ada byron" collapse to one node. This does NOT resolve display
        # name vs. mention handle (e.g. "Ada Byron" from email vs "@ada"
        # from Slack) — that would need an alias table — but it fixes the
        # trivial case-difference fragmentation (audit finding L4/#14).
        raw_people = set(filter(None, [r.from_name, r.recipient]))
        raw_people |= set(MENTION_RE.findall(r.text))
        # Map lowercase key → display form. Rule: the first non-lowercase
        # form we see wins ("Ada Byron" beats "ada byron"), but later forms
        # don't replace it ("ADA BYRON" doesn't overwrite "Ada Byron"). The
        # lowercase-only form is a fallback used only until a better form
        # arrives.
        people: dict[str, str] = {}
        for p in raw_people:
            k = p.lower()
            if k == you:
                continue
            prev = people.get(k)
            if prev is None or (prev == k and p != k):
                people[k] = p

        projects = {p for p, pat in self._project_patterns if pat.search(blob_lower)}
        channels = {r.channel} if r.channel else set()

        # Ticket normalization: collapse "PR #482" / "PR#482" / "PR  #482"
        # to a single canonical form so re-scrapes of the same PR don't
        # produce two graph nodes (audit finding L4/#11).
        raw_tickets = self.ticket_re.findall(f"{blob} {r.url}")
        tickets = set()
        for m in raw_tickets:
            token = m if isinstance(m, str) else m[0]
            tickets.add(re.sub(r"PR\s*#\s*", "PR #", token))

        person_keys = set(people.keys())
        for key, display in people.items():
            n = self.people[key]
            # Preserve the best display we've seen across records: don't
            # replace a mixed-case form with a lowercase-only one, and don't
            # let a later "ADA BYRON" clobber an earlier "Ada Byron".
            prev_display = n.get("display_name") or ""
            if not prev_display or (prev_display == key and display != key):
                n["display_name"] = display
            n["platforms"].add(r.source)
            n["projects"] |= projects
            n["channels"] |= channels
            n["interaction_count"] += 1
            # Record normalizes parseable ts to ISO UTC, so max() is chronological;
            # skip non-ISO strays so garbage never overwrites a real last_seen.
            if r.ts[:1].isdigit() and "T" in r.ts:
                n["last_seen"] = max(n.get("last_seen", ""), r.ts)
        for project in projects:
            n = self.projects[project]
            n["people"] |= person_keys
            n["channels"] |= channels
            n["tickets"] |= tickets
            n["mentions"] += 1
        # Channels and tickets: also count the interaction so the counters
        # aren't dead zeros in the serialised graph (audit finding L4/#13).
        for ch in channels:
            n = self.channels[ch]
            n["people"] |= person_keys
            n["projects"] |= projects
            n["mentions"] += 1
        for tk in tickets:
            n = self.tickets[tk]
            n["people"] |= person_keys
            n["projects"] |= projects
            n["mentions"] += 1

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
    d["interaction_count"] = 0  # only ticked for people
    d["mentions"] = 0            # ticked for projects, channels, and tickets
    d["last_seen"] = ""
    d["display_name"] = ""      # populated for people; canonicalized-case form
    return d


def _serialize(node: dict) -> dict:
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in node.items()}
