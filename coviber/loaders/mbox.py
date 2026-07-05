"""Mbox loader — ingest a local Unix mbox file, pure stdlib.

Also home of `message_to_record`, the shared email.message.Message → Record
mapping used by both the mbox and imap loaders.
"""
from __future__ import annotations

import html
import mailbox
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional

from ..record import Record
from . import register
from .base import Loader


class _HTMLTextExtractor(HTMLParser):
    """Minimal stdlib HTML→text stripper for the html-only email fallback.

    Drops <script>/<style> contents entirely; turns block-ending tags into
    newlines so paragraphs don't run together. Not a general-purpose renderer —
    just enough that graph/urgency/search see readable text.
    """
    _BLOCK = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        return html.unescape("".join(self._parts)).strip()


def _html_to_text(raw: str) -> str:
    p = _HTMLTextExtractor()
    try:
        p.feed(raw); p.close()
    except Exception:
        return raw  # malformed HTML — better to keep the raw bytes than lose the record
    return p.get_text()


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _name_or_addr(value: Optional[str]) -> str:
    name, addr = parseaddr(value or "")
    return _decode(name) or addr


def _iso_ts(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError):  # TypeError on 3.9, ValueError on 3.10+
        return raw


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        payload = (part.get_payload() or "").encode("utf-8", "replace")
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _body(msg: Message) -> str:
    html_fallback = None  # first non-attachment text/html, used only if no text/plain wins
    for part in msg.walk():  # walk() on a single-part message yields just itself
        if "attachment" in (part.get("Content-Disposition") or ""):
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            return _decode_part(part)
        if ctype == "text/html" and html_fallback is None:
            html_fallback = _decode_part(part)
    return _html_to_text(html_fallback) if html_fallback else ""


def message_to_record(msg: Message, source: str = "email", unread: Optional[bool] = None,
                      channel: str = "inbox") -> Record:
    """Shared Message → Record mapping. `unread=None` derives read state from
    the mbox `Status` header ("R" = read); imap passes it explicitly."""
    if unread is None:
        unread = "R" not in (msg.get("Status") or "")
    refs = (msg.get("References") or "").split()
    return Record(source=source, channel=channel, unread=bool(unread),
                  from_name=_name_or_addr(msg.get("From")),
                  recipient=_name_or_addr(msg.get("To")),
                  subject=_decode(msg.get("Subject")),
                  text=_body(msg),
                  ts=_iso_ts(msg.get("Date")),
                  thread_id=refs[0] if refs else (msg.get("Message-ID") or "").strip())


@register("mbox")
class MboxLoader(Loader):
    """config: {"path": "~/mail.mbox", "source": "email", "limit": N}  (limit = newest N)"""

    def load(self) -> Iterable[Record]:
        raw = self.config.get("path")
        if not raw:
            raise ValueError("mbox loader needs 'path' in config")
        path = Path(raw).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"mbox loader: no file at {path}")
        source = self.config.get("source", "email")
        limit = self.config.get("limit")
        # Reject non-positive limits so `limit: -1` in YAML doesn't silently
        # drop the newest message (via `msgs[--1:]` == `msgs[1:]`, keeping
        # everything except the last). The loader has no coherent
        # "newest 0" or "newest negative-N" semantics, so fail loud.
        if limit is not None:
            limit = int(limit)
            if limit <= 0:
                raise ValueError(
                    f"mbox loader: 'limit' must be a positive integer, got {limit}"
                )
        box = mailbox.mbox(str(path))
        try:
            msgs = list(box)
        finally:
            box.close()
        if limit:
            msgs = msgs[-limit:]
        for msg in reversed(msgs):  # mbox appends chronologically -> newest first
            yield message_to_record(msg, source=source)
