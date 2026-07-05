"""End-to-end tests — run with: python -m pytest (or python tests/test_pipeline.py)."""
import json
import tempfile
from pathlib import Path

from coviber import Record, Settings, ingest, build_queue, available, get_loader
from coviber.cli import build_parser
from coviber.store import Store
from coviber.urgency import Config, score, should_skip, triage
from coviber.workgraph import WorkGraph, DEFAULT_TICKET_RE, MENTION_RE


def test_loaders_registered():
    for name in ("demo", "jsonl", "webscrape"):
        assert name in available()


def test_demo_pipeline_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        s = Settings(loader="demo", data_dir=d, known_projects=["Falcon", "Orbit", "Atlas"],
                     priority_senders=["Grace Hopper"], collaborators=["Ada Byron", "Linus Vega"])
        stats = ingest(s)
        assert stats["loaded"] == 15
        assert stats["graph"]["people"] >= 4
        assert "Falcon" in stats["graph"]["projects_list"]

        queue = build_queue(s)
        assert queue, "expected some urgent items"
        # highest item should be the @mention or the blocking sign-off
        top = queue[0]
        assert top["urgency"] >= 4
        # bot/newsletter/fyi should be filtered out
        senders = {t["record"].from_name for t in queue}
        assert "acme-ci-bot" not in senders
        assert "newsletter@acme.com" not in senders


def test_dedup_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        s = Settings(loader="demo", data_dir=d)
        a = ingest(s); b = ingest(s)
        assert b["new"] == 0 and b["total"] == a["total"]


def test_urgency_signals():
    cfg = Config(you="you", priority_senders={"Grace Hopper"}, collaborators={"Ada Byron"})
    r = Record(source="slack", from_name="Ada Byron", text="@you can you review this? blocked", unread=True)
    u, sig = score(r, cfg)
    assert u >= 6  # mention(3)+action(2)+question(1)+unread(1)+collab(1)
    assert should_skip(Record(source="email", from_name="newsletter@acme.com", subject="Weekly Digest"), cfg)


def test_workgraph_entities():
    g = WorkGraph(known_projects=["Falcon"], you="you")
    g.ingest([Record(source="github", from_name="Margaret Chen",
                     subject="PR #482: Falcon fix", text="review please ATLAS-1290")])
    # Post-L4: keys are lowercased, display form lives on the node.
    assert "margaret chen" in g.people
    assert g.people["margaret chen"]["display_name"] == "Margaret Chen"
    assert "Falcon" in g.projects
    assert any("ATLAS-1290" in t or "PR #482" in t for t in g.tickets)


def test_workgraph_project_match_word_boundary_not_substring():
    """Short/common project names must NOT match as substrings inside
    unrelated words: "Go" doesn't hit "going", "AI" doesn't hit "email"
    or "rail" (audit finding L4/#12)."""
    g = WorkGraph(known_projects=["Go", "AI", "Falcon"], you="you")
    g.ingest([Record(source="s", from_name="Ada", text="Going to the rail conference for email design")])
    # Only false positives possible under the old substring code — all three
    # should be absent from the graph now.
    assert "Go" not in g.projects and "AI" not in g.projects and "Falcon" not in g.projects
    # Positive control: an actual word match still lands.
    g2 = WorkGraph(known_projects=["Go"], you="you")
    g2.ingest([Record(source="s", from_name="Ada", text="Please review the Go migration plan")])
    assert "Go" in g2.projects


def test_workgraph_pr_ticket_canonicalization():
    """`PR #482` and `PR#482` are the same PR — the graph must dedupe them
    into a single ticket node (audit finding L4/#11)."""
    g = WorkGraph(you="you")
    g.ingest([
        Record(source="s", from_name="A", subject="PR #482 review please"),
        Record(source="s", from_name="B", text="fix landing in PR#482"),
        Record(source="s", from_name="C", text="ship PR   #482"),  # extra whitespace
    ])
    pr_tickets = [t for t in g.tickets if "482" in t]
    assert pr_tickets == ["PR #482"]


def test_workgraph_person_identity_case_insensitive():
    """Case-different display names collapse to one node — "Ada Byron",
    "ada byron", and "ADA BYRON" all merge (audit finding L4/#14). The
    graph preserves the mixed-case display form on the node."""
    g = WorkGraph(you="you")
    g.ingest([
        Record(source="email", from_name="Ada Byron", text="hi"),
        Record(source="slack", from_name="ada byron", text="hi again"),
        Record(source="github", from_name="ADA BYRON", text="pr comment"),
    ])
    ada_keys = [k for k in g.people if "ada" in k]
    assert ada_keys == ["ada byron"]
    assert g.people["ada byron"]["interaction_count"] == 3
    assert g.people["ada byron"]["display_name"] == "Ada Byron"  # mixed-case wins


def test_workgraph_channel_and_ticket_mentions_are_incremented():
    """Channels and tickets carried dead `mentions=0` counters — after L4/#13
    they tick alongside interaction_count for people."""
    g = WorkGraph(known_projects=["Falcon"], you="you")
    for _ in range(3):
        g.ingest([Record(source="slack", from_name="Ada", channel="#general",
                          subject="Falcon PR #482 review", text="please")])
    assert g.channels["#general"]["mentions"] == 3
    assert g.tickets["PR #482"]["mentions"] == 3


def test_record_id_has_no_field_boundary_collisions():
    a = Record(source="s", text="ab", subject="c")
    b = Record(source="s", text="a", subject="bc")
    assert a.id != b.id


def test_ticket_regex_matches_bare_issue_refs():
    assert DEFAULT_TICKET_RE.findall("see #4567 for details") == ["#4567"]
    assert DEFAULT_TICKET_RE.findall("PR #482 ready") == ["PR #482"]
    assert DEFAULT_TICKET_RE.findall("ATLAS-1290 shipped") == ["ATLAS-1290"]
    assert DEFAULT_TICKET_RE.findall("room #12 x#123") == []  # too short / glued


def test_mention_regex_ignores_emails_and_trailing_punctuation():
    assert MENTION_RE.findall("email bob@example.com please") == []
    assert MENTION_RE.findall("thanks @alice.") == ["alice"]
    assert MENTION_RE.findall("cc @bob.smith and @carol_j") == ["bob.smith", "carol_j"]


def test_workgraph_excludes_you_case_insensitively():
    g = WorkGraph(you="Punit")
    g.ingest([Record(source="slack", from_name="Ada", text="@punit can you check?")])
    assert "punit" not in g.people and "Punit" not in g.people


def test_triage_skips_self_authored():
    cfg = Config(you="you")
    records = [Record(source="slack", from_name="you", text="@you did I ask myself? please review"),
               Record(source="slack", from_name="Ada", text="@you please review this?", unread=True)]
    queue = triage(records, cfg)
    assert [t["record"].from_name for t in queue] == ["Ada"]


def test_skip_senders_respects_token_boundaries():
    cfg = Config(you="you")
    assert should_skip(Record(source="e", from_name="acme-ci-bot", text="x"), cfg) == "skip-sender"
    assert should_skip(Record(source="e", from_name="Abbott", text="x"), cfg) is None


def test_keyword_search_returns_nothing_on_zero_hits():
    with tempfile.TemporaryDirectory() as d:
        ingest(Settings(loader="demo", data_dir=d))
        assert Store(d).search("zzzqqq gibberish") == []


def test_store_survives_corrupt_line():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        store.upsert([Record(source="s", text="good")])
        with store.records_path.open("a", encoding="utf-8") as f:
            f.write("{not json\n")
        assert len(store.all()) == 1
        store.upsert([Record(source="s", text="another")])  # must not raise
        assert len(store.all()) == 2


def test_jsonl_loader_handles_null_source_and_reports_bad_lines():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "in.jsonl"
        p.write_text(json.dumps({"source": None, "text": "hi"}) + "\n", encoding="utf-8")
        recs = list(get_loader("jsonl", {"path": str(p)}).load())
        assert recs[0].source == "jsonl"
        p.write_text("[1, 2]\n", encoding="utf-8")
        try:
            list(get_loader("jsonl", {"path": str(p)}).load())
            raise AssertionError("expected ValueError for non-object line")
        except ValueError as e:
            assert "in.jsonl:1" in str(e)


def test_cli_accepts_data_dir_after_subcommand():
    for argv in (["serve", "--data-dir", "/tmp/x"], ["--data-dir", "/tmp/x", "serve"], ["demo"]):
        args = build_parser().parse_args(argv)
        assert hasattr(args, "data_dir")
    assert build_parser().parse_args(["serve", "--data-dir", "/tmp/x"]).data_dir == "/tmp/x"


_ALL = [test_loaders_registered, test_demo_pipeline_end_to_end, test_dedup_is_idempotent,
        test_urgency_signals, test_workgraph_entities,
        test_workgraph_project_match_word_boundary_not_substring,
        test_workgraph_pr_ticket_canonicalization,
        test_workgraph_person_identity_case_insensitive,
        test_workgraph_channel_and_ticket_mentions_are_incremented,
        test_record_id_has_no_field_boundary_collisions, test_ticket_regex_matches_bare_issue_refs,
        test_mention_regex_ignores_emails_and_trailing_punctuation,
        test_workgraph_excludes_you_case_insensitively, test_triage_skips_self_authored,
        test_skip_senders_respects_token_boundaries, test_keyword_search_returns_nothing_on_zero_hits,
        test_store_survives_corrupt_line, test_jsonl_loader_handles_null_source_and_reports_bad_lines,
        test_cli_accepts_data_dir_after_subcommand]

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
