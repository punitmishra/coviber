# Roadmap

Every release stays reproducible on the synthetic corpus. Numbers and behavior
below refer only to the demo/JSONL loaders on synthetic data.

## Shipped

### v0.1
The initial clean-room build: `Record` + `Store` + `WorkGraph` + `Urgency` +
`Persona` + the MCP server, all local-first, zero-dep core. Demo corpus,
reproducible benchmarks, and the first merge train (#1–#7) — email/slack
loaders, persisted embedding index, MCP config parity, atomic-write
concurrency, ISO-8601 timestamps, the `U(r) ∈ [0, 14]` urgency contract.

### v0.2
Server-safe `ConfigError` replaces `sys.exit` (#12); HTML-only email fallback
via stdlib `html.parser` (#11); corrupt-line quarantine to `records.jsonl.bad`
(#13); configurable per-signal urgency weights (#14).

### v0.3
IMAP protocol-fake test coverage (#15) — six tests exercise login/select/
search/fetch/logout via `imaplib` monkeypatch, including both documented
FETCH response shapes. Optional **Qdrant** vector backend (partially #19) —
new `[qdrant]` extra, pluggable `VectorStore` protocol with `JSONVectorStore`
(default) and `QdrantVectorStore`, `docker-compose.yml` for local Docker.

### v0.4
Adversarial layer audit — 142 agents, 45 raw findings → 35 confirmed → all 35
landed as seven layer-scoped PRs (#24–#30). Highlights:
- **Store**: crash-on-nonstring-ts, atomic `save_graph`, `embeddings.json.tmp`
  race, float32 vector persistence.
- **Pipeline/Config/CLI**: empty-list-in-config honored as opt-out end-to-end,
  single `store.all()` read per ingest, `Settings.from_dict` passthrough tests.
- **Loaders**: reject non-positive `limit`, IMAP socket timeout, webscrape
  `is_file()` inline-vs-path detection, JSONL numeric-ts survival.
- **WorkGraph**: word-boundary project matching, PR ticket dedup, case-
  insensitive person identity with `display_name`, live channel/ticket counters.
- **Urgency**: FYI word-boundary, empty `cfg.you` guard, weight-key typos warn.
- **Persona**: opener/closer dedup for single-line messages, contractions out
  of vocab, empty-corpus sentinel prompt, extended emoji range, MCP name plumbing.
- **MCP**: torn-graph read defense, `graph_summary` KeyError-proofing,
  `refresh` error messages, case-insensitive `who_is`, coverage for the five
  previously-untested tools.

### v0.5 (this release)
Architect audit — 175 agents, 55 raw findings → 34 confirmed → 18 fix-now
landed here, 12 tracked as GitHub issues, 4 documented as invariants in
`ARCHITECTURE.md`. Highlights: dynamic `__version__` from installed metadata,
entry-point loader failures observable via `warnings.warn`, README/ARCHITECTURE
env-var reference table, remote-Qdrant URL warning, `Record.from_dict` warns
on unknown fields, tilde expansion consistent across every config source,
CLI `graph` gets the same defensive read as the MCP tools, urgency `clamped`
comment lie fixed, MCP tool-registration smoke test uses a name-set instead
of a magic count.

## v0.6 (next)

- **De-identified whitepaper** (#16). Re-derive the evaluation on the `demo`
  corpus and publish the full paper (`WHITEPAPER.md` is currently a stub).
- **Per-loader dedup granularity** (#17). The content-hash id deliberately
  excludes `ts`/`channel` so re-scrapes dedup naturally — but this collapses
  genuinely-recurring identical messages (a bot's daily "build passed") into
  one record, wrong for audit-trail sources. Make ts/channel inclusion a
  per-loader knob.
- **Incremental graph updates** (#18). `pipeline.ingest` rebuilds the whole
  `WorkGraph` from the full store each cycle — O(n) per ingest. Persist graph
  state and apply only new records (dedup makes "new" well-defined via
  `Store.upsert`'s return).
- **Real vector index format** (#19). `embeddings.json` is human-debuggable
  and fine at ~10⁵ records; past that the load-per-query cost dominates.
  Options: memory-mapped `.npy` for the JSON backend; document Qdrant as the
  scale answer.

## Later / open questions

- Alias resolution for the WorkGraph — `Ada Byron` from email vs `@ada` from
  Slack still fragment into two nodes even after v0.4's case-insensitive fix.
- Streaming/incremental MCP tools — every tool reads from disk end-to-end.
  Fine at 10⁴ records but not 10⁶.
- Persona voice-profile extensibility — one hardcoded engine; no way to swap
  in a per-user override.
- Test property coverage — the suite is implementation-heavy; a
  Hypothesis-based `records.jsonl` round-trip contract would find shape
  regressions the current tests miss.
