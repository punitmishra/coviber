"""Pin the documented urgency contract: U(r) ∈ [0,14], 14 = every signal at once."""
import pytest

from coviber import Record
from coviber.urgency import DEFAULT_WEIGHTS, Config, score, should_skip


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


# --- audit L5 findings ---------------------------------------------------


def test_fyi_does_not_match_common_english_words():
    """"fyi" inside "justifying", "notifying", "typify" is a false-positive
    skip that used to silently drop legitimate obligations
    (audit finding L5/#16)."""
    cfg = Config(you="you")
    for word in ("justifying", "notifying", "typify", "modifying"):
        r = Record(source="s", from_name="A", text=f"we are {word} the plan")
        assert should_skip(r, cfg) is None, f"'{word}' should not trigger FYI skip"


def test_fyi_still_matches_the_phrase_itself():
    cfg = Config(you="you")
    for phrase in ("FYI, the deploy is green", "just so you know we shipped",
                   "no action needed here", "no reply needed"):
        r = Record(source="s", from_name="A", text=phrase)
        assert should_skip(r, cfg) == "fyi", f"'{phrase}' should trigger FYI skip"


def test_empty_you_does_not_fire_mention_on_any_at_sign():
    """An empty `cfg.you` used to collapse the mention regex to `@\\b`,
    matching every email address as a mention (audit finding L5/#17)."""
    cfg = Config(you="")
    r = Record(source="s", from_name="A", text="cc bob@example.com and carol@example.com")
    u, signals = score(r, cfg)
    assert "@mention+3" not in signals
    # Same message with a real `you` still fires when the mention matches.
    cfg2 = Config(you="you")
    r2 = Record(source="s", from_name="A", text="cc @you please")
    _, signals2 = score(r2, cfg2)
    assert any(s.startswith("@mention") for s in signals2)


def test_empty_set_opt_out_of_default_skip_lists_and_action_words():
    """Explicit empty sets in Config must opt out of the module defaults
    (audit finding L5/#18). L2's PR already lands the same guard via
    `is not None`; ship the test in the urgency layer where the fix lives."""
    cfg = Config(you="you", action_words=set(), skip_senders=set(), skip_subjects=set())
    assert cfg.action_words == set()
    assert cfg.skip_senders == set()
    assert cfg.skip_subjects == set()
    # Default fallback still works.
    default_cfg = Config(you="you")
    assert default_cfg.action_words and default_cfg.skip_senders and default_cfg.skip_subjects


def test_weight_bad_value_names_the_offending_key():
    """A non-int weight value used to raise a bare `ValueError` with no
    indication of which key was bad — the operator had to scan the whole
    config to find it (audit finding L5/#19)."""
    with pytest.raises(ValueError) as exc:
        Config(you="you", weights={"unread": "not-an-int"})
    msg = str(exc.value)
    assert "unread" in msg and "not-an-int" in msg


def test_weight_unknown_key_emits_warning():
    """A typo like `mentin: 5` used to be silently dropped from the weights
    dict; the operator's tuning had no effect and they got no signal
    (audit finding L5/#20)."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        Config(you="you", weights={"mentin": 5, "mention": 4})  # typo + real key
        matches = [x for x in w if "mentin" in str(x.message)]
        assert matches, f"expected a warning naming 'mentin', got {[str(x.message) for x in w]}"


if __name__ == "__main__":
    test_max_score_is_exactly_14(); test_score_never_exceeds_contract()
    test_default_weights_are_stable(); test_custom_weights_change_score()
    test_zero_weight_disables_signal_and_label()
    test_partial_weights_merge_over_defaults()
    test_dynamic_signal_labels_reflect_weight()
    test_fyi_does_not_match_common_english_words()
    test_fyi_still_matches_the_phrase_itself()
    test_empty_you_does_not_fire_mention_on_any_at_sign()
    test_empty_set_opt_out_of_default_skip_lists_and_action_words()
    print("ok")
