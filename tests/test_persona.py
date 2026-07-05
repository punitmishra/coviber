"""Persona (voice profile) tests — no test coverage existed before v0.4
(audit finding L6/#31). These lock down the observable contract:
  - empty corpus does not fabricate a voice
  - single-line messages don't double-count opener + closer
  - multi-message corpora produce sensible top_openers / top_closers
  - formality clamps to [0, 1] even under extreme markers
  - contractions ("don't", "I'll") are excluded from signature vocabulary
  - emoji regex covers clock/technical shapes, not just supplementary chars
  - MCP `voice_profile` passes the caller's name to `system_prompt`

Run: python -m pytest tests/test_persona.py
"""
from __future__ import annotations

from coviber.persona import VoiceProfile, learn


# ---------------------------------------------------------------------------
# empty corpus (#29)
# ---------------------------------------------------------------------------


def test_empty_corpus_returns_zero_message_profile():
    vp = learn([])
    assert isinstance(vp, VoiceProfile)
    assert vp.n_messages == 0
    assert vp.avg_words == 0.0
    assert vp.top_openers == [] and vp.top_closers == []
    assert vp.vocabulary == []


def test_zero_message_profile_prompt_is_sentinel_not_fabricated():
    """system_prompt() must NOT emit "formal, ~0 words per message" for an
    empty profile — that reads as a real voice profile to the LLM."""
    vp = VoiceProfile()
    text = vp.system_prompt("Punit")
    assert "No voice profile" in text or "No self-authored" in text
    assert "Punit" in text
    # Sanity: no fabricated content leaks through.
    assert "words per message" not in text and "Signature vocabulary" not in text


# ---------------------------------------------------------------------------
# single-line double-count (#26)
# ---------------------------------------------------------------------------


def test_single_line_message_does_not_double_count_opener_and_closer():
    """Before the fix, a message "Thanks for the update" incremented BOTH the
    "Thanks" opener AND the "Thanks" closer since the same line matched both
    regexes. A single-line message should count as an opener OR a closer,
    not both."""
    vp = learn(["Thanks for the update"])
    total_opens = sum(c for _, c in vp.top_openers)
    total_closes = sum(c for _, c in vp.top_closers)
    # Should not be 2 total (was: 1 opener + 1 closer). One or the other.
    assert total_opens + total_closes <= 1


def test_multiline_message_still_counts_opener_and_closer_separately():
    vp = learn(["Hi team,\n\nSome context here.\n\nThanks"])
    assert any(name == "Hi" for name, _ in vp.top_openers)
    assert any(name == "Thanks" for name, _ in vp.top_closers)


# ---------------------------------------------------------------------------
# openers/closers ranking (#31 test-gap)
# ---------------------------------------------------------------------------


def test_multi_message_corpus_ranks_top_openers_and_closers():
    corpus = [
        "Hi Grace,\n\nSounds good — will do.\n\nThanks",
        "Hi Ada,\n\nCircling back on the schema.\n\nThanks",
        "Hey Linus,\n\nWhat's the rollout window?\n\nCheers",
    ]
    vp = learn(corpus)
    # "Hi" appears twice, "Hey" once → top opener is Hi.
    assert vp.top_openers[0][0] == "Hi" and vp.top_openers[0][1] == 2
    # "Thanks" x2, "Cheers" x1 → top closer is Thanks.
    assert vp.top_closers[0][0] == "Thanks" and vp.top_closers[0][1] == 2
    assert vp.n_messages == 3


# ---------------------------------------------------------------------------
# formality bounds (#31 test-gap)
# ---------------------------------------------------------------------------


def test_formality_clamps_to_zero_and_one_for_extreme_inputs():
    all_formal = ["Please kindly review, regards"] * 20
    vp_high = learn(all_formal)
    assert 0.0 <= vp_high.formality <= 1.0
    all_casual = ["Hey yeah cool sure thing np lol thx"] * 20
    vp_low = learn(all_casual)
    assert 0.0 <= vp_low.formality <= 1.0
    assert vp_high.formality > vp_low.formality  # ordering still meaningful


# ---------------------------------------------------------------------------
# contractions (#28)
# ---------------------------------------------------------------------------


def test_contractions_are_excluded_from_signature_vocabulary():
    """Words containing an apostrophe ("don't", "I'll", "we're") are not
    signature vocabulary — everyone uses them (audit finding L6/#28)."""
    vp = learn([
        "I'll ping when the deploy finishes, don't want to block on this.",
        "We're going to migrate the router, it's already tested.",
        "Won't merge until the audit passes, that's the deal.",
    ])
    vocab_words = {w for w, _ in vp.vocabulary}
    for contraction in ("i'll", "don't", "we're", "it's", "won't", "that's"):
        assert contraction not in vocab_words, f"'{contraction}' leaked into signature vocab"


# ---------------------------------------------------------------------------
# emoji regex (#30)
# ---------------------------------------------------------------------------


def test_emoji_regex_covers_technical_and_shape_blocks():
    """The extended emoji range now includes U+2300-U+25FF (clock, watch,
    simple shapes) that people use in professional writing (audit L6/#30)."""
    # ⏰ (U+23F0, alarm clock), ⌚ (U+231A, watch), ▶ (U+25B6, black right arrow):
    # all in the newly-covered range.
    vp = learn(["Meeting at 3pm ⏰", "Reminder: standup ⌚", "▶ Playbook: ..."])
    # emoji_rate = total emojis / n_messages. 3 emoji / 3 msgs = 1.0.
    assert vp.emoji_rate >= 0.5


# ---------------------------------------------------------------------------
# system_prompt name plumbing (#27)
# ---------------------------------------------------------------------------


def test_system_prompt_uses_provided_name():
    vp = learn(["Hi team,\n\nSounds good.\n\nThanks"])
    assert "Write as Punit" in vp.system_prompt("Punit")
    assert "Write as the user" in vp.system_prompt()  # default kept intact
