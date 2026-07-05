"""Email loader tests (mbox + imap) — offline only, synthetic Acme Robotics mail.

Run with: python -m pytest (or python tests/test_email_loaders.py)
"""
import email
import mailbox
import os
import tempfile
from email.message import EmailMessage
from pathlib import Path

from coviber import Settings, available, build_queue, get_loader, ingest
from coviber.loaders.mbox import message_to_record


def _msg(from_, to="you@acme.com", subject="", body="", date=None, status=None,
         message_id=None, references=None):
    m = EmailMessage()
    m["From"] = from_; m["To"] = to; m["Subject"] = subject
    if date: m["Date"] = date
    if status is not None: m["Status"] = status
    if message_id: m["Message-ID"] = message_id
    if references: m["References"] = references
    m.set_content(body)
    return m


def _make_mbox(dirpath) -> str:
    path = str(Path(dirpath) / "acme.mbox")
    box = mailbox.mbox(path)
    box.add(_msg("Grace Hopper <grace.hopper@acme.com>", subject="Falcon launch sign-off",
                 body="Can you review and approve the Falcon release plan today?",
                 date="Thu, 02 Jul 2026 09:15:00 -0700", status="RO",
                 message_id="<falcon-1@acme.com>"))
    m = _msg("Ada Byron <ada.byron@acme.com>", subject="Atlas schema notes",
             body="Attached the Atlas tenant schema notes.",
             date="Fri, 03 Jul 2026 14:00:00 -0700", status="RO", message_id="<atlas-7@acme.com>")
    m.add_attachment(b"fake-bytes", maintype="application", subtype="octet-stream",
                     filename="schema.bin")  # multipart: text/plain + attachment
    box.add(m)
    box.add(_msg("Linus Vega <linus.vega@acme.com>", subject="Re: Orbit staging 500s",
                 body="@you the Orbit staging deploy is failing — can you take a look today?",
                 date="Sat, 04 Jul 2026 08:30:00 -0700",  # no Status header -> unread
                 message_id="<orbit-3@acme.com>", references="<orbit-1@acme.com> <orbit-2@acme.com>"))
    box.add(_msg("margaret.chen@acme.com", subject="Reranker eval results",
                 body="Posted the reranker numbers.", date="Sat, 04 Jul 2026 10:00:00 -0700",
                 status="RO", message_id="<orbit-9@acme.com>"))
    box.flush(); box.close()
    return path


def test_email_loaders_registered():
    for name in ("mbox", "imap"):
        assert name in available()


def test_mbox_loader_maps_fields():
    with tempfile.TemporaryDirectory() as d:
        recs = list(get_loader("mbox", {"path": _make_mbox(d)}).load())
        assert len(recs) == 4
        by_sender = {r.from_name: r for r in recs}
        grace = by_sender["Grace Hopper"]
        assert grace.source == "email" and grace.channel == "inbox"
        assert grace.recipient == "you@acme.com"
        assert grace.ts == "2026-07-02T16:15:00+00:00"  # RFC-2822 Date -> ISO-8601, normalized to UTC
        assert grace.thread_id == "<falcon-1@acme.com>" and not grace.unread
        ada = by_sender["Ada Byron"]
        assert "tenant schema" in ada.text and "fake-bytes" not in ada.text  # attachment skipped
        linus = by_sender["Linus Vega"]
        assert linus.unread  # no Status header -> unread
        assert linus.thread_id == "<orbit-1@acme.com>"  # References root beats Message-ID
        assert by_sender["margaret.chen@acme.com"].subject == "Reranker eval results"  # bare-addr fallback


def test_mbox_limit_takes_newest_first():
    with tempfile.TemporaryDirectory() as d:
        recs = list(get_loader("mbox", {"path": _make_mbox(d), "limit": 2}).load())
        assert [r.from_name for r in recs] == ["margaret.chen@acme.com", "Linus Vega"]


def test_mbox_requires_path():
    try:
        list(get_loader("mbox", {}).load())
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "path" in str(e)


def test_message_to_record_edge_cases():
    raw = ("From: =?utf-8?q?Grace_M=2E_Hopper?= <grace.hopper@acme.com>\n"
           "Subject: =?utf-8?q?Falcon_go=2Fno-go?=\n"
           "Date: not a real date\n\nbody\n")
    r = message_to_record(email.message_from_string(raw))
    assert r.from_name == "Grace M. Hopper"  # RFC-2047 display name decoded
    assert r.subject == "Falcon go/no-go"
    assert r.ts == "not a real date"  # unparseable Date -> raw kept
    assert r.unread  # no Status header

    r2 = message_to_record(email.message_from_string("\nhello\n"), unread=False)
    assert r2.subject == "" and r2.from_name == "" and r2.recipient == "" and r2.thread_id == ""
    assert "hello" in r2.text and not r2.unread


def test_imap_rejects_plaintext_password():
    cfg = {"host": "imap.example.com", "username": "you@example.com", "password": "hunter2"}
    try:
        list(get_loader("imap", cfg).load())
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "password_env" in str(e)


def test_imap_lists_missing_config():
    try:
        list(get_loader("imap", {"host": "imap.example.com"}).load())
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "username" in str(e) and "password_env" in str(e) and "host" not in str(e)


def test_imap_requires_env_var_to_be_set():
    os.environ.pop("COVIBER_TEST_IMAP_PW", None)
    cfg = {"host": "imap.example.com", "username": "grace.hopper@example.com",
           "password_env": "COVIBER_TEST_IMAP_PW"}
    try:
        list(get_loader("imap", cfg).load())
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "COVIBER_TEST_IMAP_PW" in str(e)


# ---------------------------------------------------------------------------
# IMAP protocol-fake tests (#15): monkeypatch imaplib.IMAP4_SSL with a fake
# that speaks the exact response shapes real servers produce. Offline; no
# network; exercises everything below the TLS socket.
# ---------------------------------------------------------------------------


class _FakeIMAP:
    """Records every method call in order + emits the response shapes real
    servers do. FETCH toggles between the two variants Python's stdlib docs
    call out: `[(meta, raw), b')']` and `[(meta_head, raw), b'flags-trail)']`."""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.calls: list[tuple] = []
        self.login_ok = True
        self.select_ok = True
        self.search_ids: list[bytes] = []
        self.fetch_ok_by_id: dict[bytes, bool] = {}
        self.messages: dict[bytes, tuple[bytes, bytes]] = {}
        self._fetch_variant = 0
        self.logged_out = False

    def login(self, user, pw):
        self.calls.append(("login", user, pw))
        return ("OK", [b"logged in"]) if self.login_ok else ("NO", [b"nope"])

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return ("OK", [b"1"]) if self.select_ok else ("NO", [b"nope"])

    def search(self, charset, *criteria):
        self.calls.append(("search", charset, criteria))
        return "OK", [b" ".join(self.search_ids)] if self.search_ids else [b""]

    def fetch(self, num, spec):
        self.calls.append(("fetch", num, spec))
        if not self.fetch_ok_by_id.get(num, True):
            return "NO", [b"fetch failed"]
        meta, raw = self.messages[num]
        # Alternate the two documented shapes so the loader is exercised on both.
        variant = self._fetch_variant
        self._fetch_variant ^= 1
        if variant == 0:
            return "OK", [(b"1 (FLAGS (" + meta + b") BODY[] {" + str(len(raw)).encode() + b"}", raw), b")"]
        # Variant with FLAGS in a trailing bytes item (some servers do this).
        return "OK", [(b"1 (BODY[] {" + str(len(raw)).encode() + b"}", raw),
                      b" FLAGS (" + meta + b"))"]

    def logout(self):
        self.calls.append(("logout",))
        self.logged_out = True
        return "BYE", [b"logged out"]


def _rfc822(from_, subject, body, message_id):
    return (f"From: {from_}\nTo: you@acme.com\nSubject: {subject}\n"
            f"Message-ID: {message_id}\nDate: Thu, 02 Jul 2026 09:15:00 -0700\n\n"
            f"{body}\n").encode("utf-8")


def _wire_fake(monkeypatch, ids, messages, *, login_ok=True, select_ok=True,
               fetch_ok=None):
    """Install a fresh _FakeIMAP for a single test; return it for assertions."""
    holder = {}
    def factory(host, port):
        fake = _FakeIMAP(host, port)
        fake.login_ok = login_ok
        fake.select_ok = select_ok
        fake.search_ids = ids
        fake.messages = messages
        fake.fetch_ok_by_id = fetch_ok or {}
        holder["fake"] = fake
        return fake
    monkeypatch.setattr("coviber.loaders.imap.imaplib.IMAP4_SSL", factory)
    return holder


def test_imap_happy_path_maps_messages_and_flags(monkeypatch):
    # Two messages: one \Seen (read), one unseen (unread). Both fetched.
    ids = [b"1", b"2"]
    messages = {
        b"1": (b"\\Seen", _rfc822("Grace <grace@acme.com>", "Falcon", "sign-off please", "<f-1@acme.com>")),
        b"2": (b"",       _rfc822("Ada <ada@acme.com>",     "Orbit",  "@you review?",    "<o-1@acme.com>")),
    }
    holder = _wire_fake(monkeypatch, ids, messages)
    monkeypatch.setenv("COVIBER_TEST_IMAP_PW", "hunter2")
    cfg = {"host": "imap.example.com", "username": "you@acme.com",
           "password_env": "COVIBER_TEST_IMAP_PW", "mailbox": "INBOX"}
    recs = list(get_loader("imap", cfg).load())
    fake = holder["fake"]
    # Order: reversed(ids) → newest first → id=2 (Ada) before id=1 (Grace).
    assert [r.from_name for r in recs] == ["Ada", "Grace"]
    assert recs[0].unread is True   # id=2 has no \Seen
    assert recs[1].unread is False  # id=1 has \Seen
    assert all(r.channel == "inbox" for r in recs)
    # Protocol steps in order:
    step_names = [c[0] for c in fake.calls]
    assert step_names[0] == "login"
    assert step_names[1] == "select"
    assert step_names[2] == "search"
    assert step_names[-1] == "logout"
    # SELECT was readonly (BODY.PEEK guarantees no state change either way).
    assert fake.calls[1] == ("select", "INBOX", True)


def test_imap_unread_only_uses_UNSEEN_search(monkeypatch):
    holder = _wire_fake(monkeypatch, [b"7"], {
        b"7": (b"", _rfc822("Bob <bob@acme.com>", "hi", "hello", "<7@acme.com>")),
    })
    monkeypatch.setenv("COVIBER_TEST_IMAP_PW", "hunter2")
    cfg = {"host": "imap.example.com", "username": "you@acme.com",
           "password_env": "COVIBER_TEST_IMAP_PW", "unread_only": True}
    list(get_loader("imap", cfg).load())
    search_call = next(c for c in holder["fake"].calls if c[0] == "search")
    assert search_call[2] == ("UNSEEN",)


def test_imap_limit_takes_newest_first(monkeypatch):
    ids = [b"1", b"2", b"3", b"4", b"5"]
    messages = {i: (b"\\Seen", _rfc822("bob@acme.com", f"m{i.decode()}", "x", f"<{i.decode()}@a>"))
                for i in ids}
    holder = _wire_fake(monkeypatch, ids, messages)
    monkeypatch.setenv("COVIBER_TEST_IMAP_PW", "hunter2")
    cfg = {"host": "imap.example.com", "username": "you@acme.com",
           "password_env": "COVIBER_TEST_IMAP_PW", "limit": 2}
    recs = list(get_loader("imap", cfg).load())
    # limit=2 keeps newest two ids: [4,5], then reverses → [5,4].
    subjects = [r.subject for r in recs]
    assert subjects == ["m5", "m4"]
    fetched = [c[1] for c in holder["fake"].calls if c[0] == "fetch"]
    assert fetched == [b"5", b"4"]


def test_imap_select_failure_still_logs_out(monkeypatch):
    holder = _wire_fake(monkeypatch, [], {}, select_ok=False)
    monkeypatch.setenv("COVIBER_TEST_IMAP_PW", "hunter2")
    cfg = {"host": "imap.example.com", "username": "you@acme.com",
           "password_env": "COVIBER_TEST_IMAP_PW", "mailbox": "junk"}
    try:
        list(get_loader("imap", cfg).load())
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "junk" in str(e)
    assert holder["fake"].logged_out is True  # finally-block ran


def test_imap_skips_fetch_failures_and_continues(monkeypatch):
    ids = [b"1", b"2"]
    messages = {
        b"1": (b"\\Seen", _rfc822("Grace <grace@acme.com>", "Falcon", "sign-off", "<f-1@acme.com>")),
        b"2": (b"",       _rfc822("Ada <ada@acme.com>",     "Orbit",  "review?",   "<o-1@acme.com>")),
    }
    holder = _wire_fake(monkeypatch, ids, messages, fetch_ok={b"1": True, b"2": False})
    monkeypatch.setenv("COVIBER_TEST_IMAP_PW", "hunter2")
    cfg = {"host": "imap.example.com", "username": "you@acme.com",
           "password_env": "COVIBER_TEST_IMAP_PW"}
    recs = list(get_loader("imap", cfg).load())
    # id=2 (Ada) fails → skipped; id=1 (Grace) still returned.
    assert [r.from_name for r in recs] == ["Grace"]
    assert holder["fake"].logged_out is True  # clean logout after mid-loop skip


def test_imap_fetch_response_variants_both_parsed(monkeypatch):
    # The _FakeIMAP alternates variants automatically — with 4 ids we exercise
    # both shapes twice and confirm all four records materialize.
    ids = [b"1", b"2", b"3", b"4"]
    messages = {i: (b"\\Seen" if int(i) % 2 else b"",
                    _rfc822(f"user{i.decode()}@acme.com", f"s{i.decode()}", "body", f"<{i.decode()}@a>"))
                for i in ids}
    _wire_fake(monkeypatch, ids, messages)
    monkeypatch.setenv("COVIBER_TEST_IMAP_PW", "hunter2")
    cfg = {"host": "imap.example.com", "username": "you@acme.com",
           "password_env": "COVIBER_TEST_IMAP_PW"}
    recs = list(get_loader("imap", cfg).load())
    assert len(recs) == 4
    # Even ids had no \Seen → unread=True; odd ids had \Seen → unread=False.
    by_id = {r.subject: r for r in recs}
    assert by_id["s2"].unread is True and by_id["s4"].unread is True
    assert by_id["s1"].unread is False and by_id["s3"].unread is False


def test_message_to_record_html_only_fallback():
    # html-only email (increasingly common) — must yield readable text, not "".
    raw = ("From: bot@acme.com\nSubject: Falcon dashboard\n"
           "Content-Type: text/html; charset=utf-8\n\n"
           "<html><head><style>p{color:red}</style>"
           "<script>alert('x')</script></head>"
           "<body><h1>Falcon</h1><p>Deploy is <b>green</b> &amp; ready.</p>"
           "<p>See <a href='/x'>dashboard</a>.</p></body></html>\n")
    r = message_to_record(email.message_from_string(raw))
    assert "Falcon" in r.text and "green & ready" in r.text and "dashboard" in r.text
    assert "alert" not in r.text and "color:red" not in r.text  # script/style stripped
    assert "<" not in r.text and "&amp;" not in r.text  # tags gone, entities unescaped


def test_message_to_record_multipart_alternative_prefers_plain():
    # multipart/alternative with both text/plain and text/html — plain wins.
    m = EmailMessage()
    m["From"] = "grace@acme.com"; m["Subject"] = "Falcon plan"
    m.set_content("Plain-text body wins.")
    m.add_alternative("<p>HTML body loses.</p>", subtype="html")
    r = message_to_record(m)
    assert "Plain-text body wins" in r.text
    assert "HTML" not in r.text and "<p>" not in r.text


def test_message_to_record_html_malformed_keeps_raw():
    # Broken HTML shouldn't drop the record; keep something searchable.
    raw = ("From: bot@acme.com\nContent-Type: text/html\n\n"
           "<p>unterminated <b>bold text\n")
    r = message_to_record(email.message_from_string(raw))
    assert "bold text" in r.text  # tags stripped best-effort


def test_mbox_end_to_end_pipeline():
    with tempfile.TemporaryDirectory() as d:
        s = Settings(loader="mbox", loader_config={"path": _make_mbox(d)},
                     data_dir=str(Path(d) / "data"),
                     known_projects=["Falcon", "Orbit", "Atlas"],
                     collaborators=["Linus Vega", "Ada Byron"])
        stats = ingest(s)
        assert stats["loaded"] == 4 and stats["new"] == 4
        assert stats["graph"]["people"] >= 3
        assert {"Falcon", "Orbit", "Atlas"} <= set(stats["graph"]["projects_list"])
        queue = build_queue(s)
        assert queue
        assert queue[0]["record"].from_name == "Linus Vega"  # unread @mention question ranks top


_ALL = [test_email_loaders_registered, test_mbox_loader_maps_fields,
        test_mbox_limit_takes_newest_first, test_mbox_requires_path,
        test_message_to_record_edge_cases, test_imap_rejects_plaintext_password,
        test_imap_lists_missing_config, test_imap_requires_env_var_to_be_set,
        test_message_to_record_html_only_fallback,
        test_message_to_record_multipart_alternative_prefers_plain,
        test_message_to_record_html_malformed_keeps_raw,
        test_mbox_end_to_end_pipeline]
# The IMAP protocol-fake tests use pytest's monkeypatch fixture — they can't
# be invoked from __main__; run them with `python -m pytest tests/test_email_loaders.py`.

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
