"""End-to-end tests — run with: python -m pytest (or python tests/test_pipeline.py)."""
import tempfile

from coviber import Record, Settings, ingest, build_queue, available
from coviber.urgency import Config, score, should_skip
from coviber.workgraph import WorkGraph


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
    assert "Margaret Chen" in g.people
    assert "Falcon" in g.projects
    assert any("ATLAS-1290" in t or "PR #482" in t for t in g.tickets)


if __name__ == "__main__":
    for fn in [test_loaders_registered, test_demo_pipeline_end_to_end, test_dedup_is_idempotent,
               test_urgency_signals, test_workgraph_entities]:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
