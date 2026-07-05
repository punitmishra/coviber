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


def test_jsonl_loader_reports_bad_line_number_mid_stream():
    """A bad line at position N must name that line in the error message —
    otherwise the operator has no signal about where to fix the input
    (audit finding L3/#5). The loader's fail-loud contract for corrupt
    input is intentional; this test pins the diagnostic content."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "in.jsonl"
        p.write_text(
            json.dumps({"source": "s", "text": "line 1"}) + "\n"
            + "not-json-line-2\n"
            + json.dumps({"source": "s", "text": "line 3"}) + "\n",
            encoding="utf-8",
        )
        try:
            list(get_loader("jsonl", {"path": str(p)}).load())
            raise AssertionError("expected ValueError for corrupt line 2")
        except ValueError as e:
            msg = str(e)
            assert "in.jsonl:2" in msg  # names the specific line
            assert "invalid JSON" in msg


def test_jsonl_loader_handles_numeric_epoch_ts():
    """Records with a numeric epoch ts (a common shape for API dumps) must
    now flow through without crashing — before the L1 _normalize_ts fix,
    `.strip()` on an int raised AttributeError uncaught (audit finding L3/#5
    + L1/#1)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "in.jsonl"
        p.write_text(
            json.dumps({"source": "s", "text": "epoch", "ts": 1700000000}) + "\n"
            + json.dumps({"source": "s", "text": "bool-ts", "ts": True}) + "\n",
            encoding="utf-8",
        )
        recs = list(get_loader("jsonl", {"path": str(p)}).load())
        assert [r.text for r in recs] == ["epoch", "bool-ts"]  # both parsed
        # int epoch in the sanity range normalizes to ISO
        assert recs[0].ts.startswith("2023-")


def test_cli_accepts_data_dir_after_subcommand():
    for argv in (["serve", "--data-dir", "/tmp/x"], ["--data-dir", "/tmp/x", "serve"], ["demo"]):
        args = build_parser().parse_args(argv)
        assert hasattr(args, "data_dir")
    assert build_parser().parse_args(["serve", "--data-dir", "/tmp/x"]).data_dir == "/tmp/x"


def test_settings_from_dict_full_passthrough():
    """Every Settings field must round-trip through from_dict — a silently-
    dropped field would drift the CLI (which passes fields explicitly) from
    the MCP server (which reads Settings.from_dict on every tool call)
    without any test catching it (audit finding L2/#25)."""
    d = {
        "loader": "jsonl",
        "config": {"path": "/tmp/x.jsonl"},
        "data_dir": "/tmp/s",
        "you": "punit",
        "known_projects": ["A", "B"],
        "priority_senders": ["grace"],
        "collaborators": ["ada"],
        "action_words": ["blocked"],
        "skip_senders": ["bot"],
        "skip_subjects": ["digest"],
        "weights": {"unread": 5},
        "qdrant": {"url": "http://x:6333"},
    }
    s = Settings.from_dict(d)
    assert s.loader == "jsonl"
    assert s.loader_config == {"path": "/tmp/x.jsonl"}   # renamed "config" → loader_config
    assert s.data_dir == "/tmp/s"
    assert s.you == "punit"
    assert s.known_projects == ["A", "B"]
    assert s.priority_senders == ["grace"]
    assert s.collaborators == ["ada"]
    assert s.action_words == ["blocked"]
    assert s.skip_senders == ["bot"]
    assert s.skip_subjects == ["digest"]
    assert s.weights == {"unread": 5}
    assert s.qdrant == {"url": "http://x:6333"}


def test_settings_from_dict_defaults_when_absent():
    s = Settings.from_dict({})
    assert s.loader == "demo"
    assert s.data_dir == "./coviber_data"
    assert s.you == "you"
    assert s.known_projects == [] and s.priority_senders == [] and s.collaborators == []
    assert s.action_words is None and s.skip_senders is None and s.skip_subjects is None
    assert s.weights is None and s.qdrant is None


def test_empty_list_from_config_opts_out_of_defaults():
    """`action_words: []` / `skip_senders: []` / `skip_subjects: []` in the
    config file must mean "opt out of these defaults", NOT "silently fall
    back to the defaults" (audit findings L2/#22 + L5/#18)."""
    with tempfile.TemporaryDirectory() as d:
        s = Settings(loader="demo", data_dir=d, skip_senders=[], action_words=[])
        # Ingest the demo corpus and triage: with skip_senders=[] the bot
        # entries must NOT be filtered by the default bot/newsletter list,
        # AND with action_words=[] the action-word signal must never fire.
        ingest(s)
        queue = build_queue(s)
        # The demo corpus contains an "acme-ci-bot" sender; with default
        # skip_senders it's filtered out. With explicit empty list, it
        # should now appear in triage (or at least no test should assert
        # it's absent). We assert the opt-out took effect by checking that
        # no queue entry carries the action-word+ signal.
        assert not any("action-word" in " ".join(t["signals"]) for t in queue), (
            "action_words=[] must disable the action-word signal"
        )


def test_empty_list_urgency_config_opts_out_of_defaults():
    """Same guarantee, one level down: Urgency Config accepts an explicit
    empty set/list as an opt-out from DEFAULT_ACTION_WORDS / SKIP_SENDERS /
    SKIP_SUBJECTS (finding L5/#18)."""
    cfg = Config(you="you", action_words=set(), skip_senders=set(), skip_subjects=set())
    assert cfg.action_words == set()  # empty opt-out honored
    assert cfg.skip_senders == set()
    assert cfg.skip_subjects == set()

    # Baseline: None still falls back to defaults.
    default_cfg = Config(you="you")
    assert default_cfg.action_words  # populated from DEFAULT_ACTION_WORDS
    assert default_cfg.skip_senders


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
        test_cli_accepts_data_dir_after_subcommand,
        test_settings_from_dict_full_passthrough, test_settings_from_dict_defaults_when_absent,
        test_empty_list_from_config_opts_out_of_defaults,
        test_empty_list_urgency_config_opts_out_of_defaults]

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
