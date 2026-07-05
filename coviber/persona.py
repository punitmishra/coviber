"""PersonaEngine — inference-free statistical voice modelling (Whitepaper §3.6).

Learns *your* writing voice from *your own* sent messages using plain statistics —
no LLM, no training, no cloud. Produces a compact voice profile and a system
prompt an MCP client can use to draft in your style.

Everything here operates on text you provide (your sent messages). It never
uploads anything and needs no inference.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

_GREETING = re.compile(r"^\s*(hi|hey|hello|dear|good morning|good afternoon|thanks|thank you|team)\b", re.I)
_CLOSING = re.compile(r"\b(thanks|thank you|best|regards|cheers|sincerely|talk soon|thx)\b[\s,!.]*$", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_STOP = set("the a an and or but to of in on for with is are be i you we it this that at as by from your my our".split())
# Extended emoji regex: keeps original supplementary + dingbats coverage,
# and adds the Miscellaneous-Technical / Box-Drawing / Geometric-Shapes
# blocks (U+2300–U+25FF) that carry clock, watch, and simple-shape emoji
# many people use in professional writing (audit finding L6/#30).
_EMOJI = re.compile("[\U0001F300-\U0001FAFF⌀-➿]")


@dataclass
class VoiceProfile:
    n_messages: int = 0
    avg_words: float = 0.0
    formality: float = 0.0          # 0 casual … 1 formal
    emoji_rate: float = 0.0         # emojis per message
    question_rate: float = 0.0
    exclaim_rate: float = 0.0
    top_openers: list = field(default_factory=list)
    top_closers: list = field(default_factory=list)
    vocabulary: list = field(default_factory=list)  # signature words

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def system_prompt(self, name: str = "the user") -> str:
        # Empty-corpus sentinel: refuse to fabricate a "formal ~0 words per
        # message" prompt that would mislead callers into thinking the
        # profile is real. If nothing was learned, say so and defer to the
        # caller's own default voice (audit finding L6/#29).
        if self.n_messages == 0:
            return (
                f"No self-authored writing samples were found for {name}. "
                f"No voice profile learned — draft in your own default voice."
            )
        reg = "formal" if self.formality > 0.6 else "casual" if self.formality < 0.35 else "neutral"
        op = self.top_openers[0][0] if self.top_openers else "Hi"
        cl = self.top_closers[0][0] if self.top_closers else "Thanks"
        emoji = "occasionally uses emoji" if self.emoji_rate > 0.15 else "rarely uses emoji"
        return (
            f"Write as {name}. Voice: {reg}, ~{round(self.avg_words)} words per message, "
            f"{emoji}. Typically opens with \"{op}\" and closes with \"{cl}\". "
            f"Signature vocabulary: {', '.join(w for w, _ in self.vocabulary[:12])}. "
            f"Match this tone and length; do not over-explain."
        )


def learn(messages: Iterable[str]) -> VoiceProfile:
    msgs = [m for m in messages if m and m.strip()]
    if not msgs:
        return VoiceProfile()
    openers, closers, vocab = Counter(), Counter(), Counter()
    words_total = q = ex = emoji = formal_hits = 0
    formal_markers = ("please", "kindly", "regards", "sincerely", "would you", "could you", "i would")
    casual_markers = ("hey", "yeah", "gonna", "lol", "thx", "cool", "sure thing", "np")
    for m in msgs:
        stripped_lines = [line for line in m.strip().splitlines() if line.strip()]
        first = stripped_lines[0] if stripped_lines else ""
        # A single-line message is not a "letter" — it has an opener OR a
        # closer, not both. Counting both on the same line double-counts
        # openers/closers when the greeting keyword ("Thanks", "Cheers") is
        # ambiguous (audit finding L6/#26).
        last = stripped_lines[-1] if len(stripped_lines) > 1 else ""
        go = _GREETING.match(first)
        if go:
            openers[go.group(1).title()] += 1
        if last:
            gc = _CLOSING.search(last)
            if gc:
                closers[gc.group(1).title()] += 1
        toks = _WORD.findall(m.lower())
        words_total += len(toks)
        for t in toks:
            # Contractions ("don't", "I'll", "we're") aren't signature
            # vocabulary — everyone uses them. Skip anything with an
            # apostrophe (audit finding L6/#28).
            if t not in _STOP and len(t) > 3 and "'" not in t:
                vocab[t] += 1
        q += m.count("?")
        ex += m.count("!")
        emoji += len(_EMOJI.findall(m))
        ml = m.lower()
        formal_hits += sum(ml.count(k) for k in formal_markers) - sum(ml.count(k) for k in casual_markers)
    n = len(msgs)
    formality = max(0.0, min(1.0, 0.5 + formal_hits / (n * 4)))
    return VoiceProfile(
        n_messages=n,
        avg_words=round(words_total / n, 1),
        formality=round(formality, 2),
        emoji_rate=round(emoji / n, 2),
        question_rate=round(q / n, 2),
        exclaim_rate=round(ex / n, 2),
        top_openers=openers.most_common(3),
        top_closers=closers.most_common(3),
        vocabulary=vocab.most_common(20),
    )
