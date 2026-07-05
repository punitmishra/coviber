"""IMAP loader — pull recent mail over IMAP4-over-SSL, pure stdlib.

The password never lives in config: set `password_env` to the *name* of an
environment variable holding it. Selects the mailbox read-only and fetches
with BODY.PEEK so nothing gets marked as seen.
"""
from __future__ import annotations

import email
import imaplib
import os
from typing import Iterable

from ..record import Record
from . import register
from .base import Loader
from .mbox import message_to_record


@register("imap")
class ImapLoader(Loader):
    """config: host, username, password_env (required); port=993, mailbox="INBOX",
    limit=200 (newest first), unread_only=False, source="email", timeout=30
    (seconds; wraps every network syscall so a wedged server can't hang the
    thread forever). A limit of 0 or negative is rejected — the loader has no
    meaningful "take newest 0" semantics."""

    def load(self) -> Iterable[Record]:
        cfg = self.config
        if "password" in cfg:
            raise ValueError("imap loader: refusing plaintext 'password' in config — put the password "
                             "in an environment variable and set 'password_env' to its name")
        missing = [k for k in ("host", "username", "password_env") if not cfg.get(k)]
        if missing:
            raise ValueError(f"imap loader missing required config: {', '.join(missing)}")
        password = os.environ.get(cfg["password_env"])
        if not password:
            raise ValueError(f"imap loader: environment variable '{cfg['password_env']}' is empty or unset")

        mbox_name = cfg.get("mailbox", "INBOX")
        # Reject non-positive limits: `limit=-1` used to silently drop the
        # oldest message (via `ids[--1:]` == `ids[1:]`); `limit=0` returned
        # the full corpus via the truthiness fallback. Neither matches
        # "newest N" semantics — fail loud instead.
        limit = int(cfg.get("limit", 200))
        if limit <= 0:
            raise ValueError(f"imap loader: 'limit' must be a positive integer, got {limit}")
        source = cfg.get("source", "email")
        # `timeout` bounds every network syscall (connect, login, SEARCH, FETCH,
        # logout). Without this, a stalled or hostile server hangs the thread
        # forever — MCP servers especially can't tolerate an unbounded wait
        # on a per-tool call. IMAP4_SSL(timeout=) landed in Python 3.9.
        timeout = float(cfg.get("timeout", 30))
        conn = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port", 993)), timeout=timeout)
        try:
            conn.login(cfg["username"], password)
            typ, _ = conn.select(mbox_name, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"imap loader: cannot select mailbox '{mbox_name}'")
            typ, data = conn.search(None, "UNSEEN" if cfg.get("unread_only") else "ALL")
            if typ != "OK":
                raise RuntimeError("imap loader: SEARCH failed")
            ids = data[0].split()
            for num in reversed(ids[-limit:] if limit else ids):  # sequence numbers ascend -> newest first
                typ, parts = conn.fetch(num, "(FLAGS BODY.PEEK[])")
                if typ != "OK":
                    continue
                raw, meta = None, b""  # flags may sit in the tuple head or a trailing bytes item
                for item in parts:
                    if isinstance(item, tuple):
                        meta += item[0]; raw = item[1]
                    elif isinstance(item, bytes):
                        meta += item
                if raw is None:
                    continue
                yield message_to_record(email.message_from_bytes(raw), source=source,
                                        unread=b"\\Seen" not in meta, channel=mbox_name.lower())
        finally:
            try:
                conn.logout()
            except Exception:
                pass
