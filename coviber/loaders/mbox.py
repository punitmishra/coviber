"""Mbox loader — ingest a local Unix mbox file, pure stdlib.

Also home of `message_to_record`, the shared email.message.Message → Record
mapping used by both the mbox and imap loaders.
"""
from __future__ import annotations

import mailbox
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Optional

from ..record import Record
from . import register
from .base import Loader


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


def _body(msg: Message) -> str:
    for part in msg.walk():  # walk() on a single-part message yields just itself
        if part.get_content_type() != "text/plain" or "attachment" in (part.get("Content-Disposition") or ""):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = (part.get_payload() or "").encode("utf-8", "replace")
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


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
        box = mailbox.mbox(str(path))
        try:
            msgs = list(box)
        finally:
            box.close()
        if limit:
            msgs = msgs[-int(limit):]
        for msg in reversed(msgs):  # mbox appends chronologically -> newest first
            yield message_to_record(msg, source=source)
