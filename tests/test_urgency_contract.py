"""Pin the documented urgency contract: U(r) ∈ [0,14], 14 = every signal at once."""
from coviber import Record
from coviber.urgency import DEFAULT_WEIGHTS, Config, score


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


def test_default_weights_are_stable():
    # Byte-for-byte pin: any weight change is an explicit, reviewed action.
    assert DEFAULT_WEIGHTS == {
        "mention": 3, "priority_sender": 2, "action_word": 2, "question": 1,
        "unread": 1, "no_reply": 1, "collaborator": 1,
        "age_7d": 3, "age_48h": 2, "age_24h": 1,
    }
    # Only one age tier can fire at a time (elif chain), so max achievable is
    # sum(non-age) + max(age tiers) = 11 + 3 = 14 — the documented ceiling.
    non_age = sum(v for k, v in DEFAULT_WEIGHTS.items() if not k.startswith("age_"))
    max_age = max(v for k, v in DEFAULT_WEIGHTS.items() if k.startswith("age_"))
    assert non_age + max_age == 14


def test_custom_weights_change_score():
    r = Record(source="s", from_name="Grace", unread=True, text="@you please review?")
    cfg_default = Config(you="you", priority_senders={"Grace"})
    u_default, _ = score(r, cfg_default)

    cfg_boost = Config(you="you", priority_senders={"Grace"},
                       weights={"mention": 5, "priority_sender": 4})
    u_boost, _ = score(r, cfg_boost)
    assert u_boost > u_default  # boosted signals lift the score


def test_zero_weight_disables_signal_and_label():
    r = Record(source="s", from_name="Bob", unread=True, text="hi")
    cfg = Config(you="you", weights={"unread": 0})
    u, signals = score(r, cfg)
    assert u == 0 and not any(s.startswith("unread") for s in signals)


def test_partial_weights_merge_over_defaults():
    # Config with only one key tweaked keeps every other default.
    cfg = Config(you="you", weights={"unread": 5})
    assert cfg.weights["unread"] == 5
    assert cfg.weights["mention"] == DEFAULT_WEIGHTS["mention"]  # untouched key = default
    assert cfg.weights["age_7d"] == DEFAULT_WEIGHTS["age_7d"]


def test_dynamic_signal_labels_reflect_weight():
    r = Record(source="s", unread=True, text="hi")
    cfg = Config(you="you", weights={"unread": 7})
    _, signals = score(r, cfg)
    assert "unread+7" in signals  # label rendered from the live weight


if __name__ == "__main__":
    test_max_score_is_exactly_14(); test_score_never_exceeds_contract()
    test_default_weights_are_stable(); test_custom_weights_change_score()
    test_zero_weight_disables_signal_and_label()
    test_partial_weights_merge_over_defaults()
    test_dynamic_signal_labels_reflect_weight()
    print("ok")
