# CoViber — Whitepaper

**Continuous Context Replication for AI-Augmented Knowledge Work**

Full LaTeX source lives under [`paper/`](./paper/); build the PDF with
`cd paper && make`. First-draft status — 4 of 12 sections verified clean
against the shipped code, 8 have specific factual corrections queued (see
[`paper/README.md`](./paper/README.md)). Every eval number and every
citation still to be filled is tracked in
[`paper/UNRESOLVED.md`](./paper/UNRESOLVED.md).

## Contributions (formalised in the paper)

1. A loader-agnostic ingestion architecture (§3.2–3.3): the only
   source-specific code is a small `Loader` that emits canonical
   `Record`s — email, chat exports, web pages, and internal APIs flow
   through the same downstream pipeline.
2. A cross-source `WorkGraph` (§3.4): incremental entity extraction
   over people, projects, channels, and tickets, with bidirectional
   links, in O(1) per record.
3. An inference-free statistical persona model (§3.6): produces a
   drafting system prompt from a user's own sent messages without ever
   invoking an LLM.
4. A configurable multi-signal urgency function `U(r)` (§3.5): weighted
   over 10 signals (`@mention`, priority-sender, action-word, question,
   unread, no-reply, collaborator, and three mutually-exclusive age
   tiers), with a token-boundary skip filter.

All four are exposed through 7 MCP tools over stdio (§3.8) — no cloud
egress, no telemetry.

## Reproducibility

Everything runs on the synthetic `demo` corpus that ships with the
package. Every published number regenerates with `python bench/run.py`.
See [`bench/results/`](./bench/results/) for the JSON snapshots that
back the paper's tables.

## Related tracked work

- [Issue #16](https://github.com/punitmishra/coviber/issues/16) — full
  de-identified whitepaper; this scaffold is the first half of that.
- [Issue #48](https://github.com/punitmishra/coviber/issues/48) — real
  bench at 10⁵ records; results already in `bench/results/`.
