"""Pin the documented urgency contract: U(r) ∈ [0,14], 14 = every signal at once."""
from coviber import Record
from coviber.urgency import Config, score


def test_max_score_is_exactly_14():
    cfg = Config(you="you", priority_senders={"Grace Hopper"}, collaborators={"Grace Hopper"})
    r = Record(source="email", from_name="Grace Hopper", unread=True,
               thread_id="t1", replied=False, ts="2020-01-01T00:00:00+00:00",
               text="@you can you review this?")
    u, signals = score(r, cfg)
    assert u == 14, signals
    assert len(signals) == 8  # every signal fired exactly once


def test_score_never_exceeds_contract():
    cfg = Config(you="you")
    u, _ = score(Record(source="s", text="hi"), cfg)
    assert 0 <= u <= 14


if __name__ == "__main__":
    test_max_score_is_exactly_14(); test_score_never_exceeds_contract()
    print("ok")
