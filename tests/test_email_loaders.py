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
        test_mbox_end_to_end_pipeline]

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
