# Changelog

All notable changes to `coviber` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every entry links to its PR and every listed issue. Behavior changes to
the public API (`from coviber import ...`) are called out under
**Changed** / **Breaking**; internal refactors under **Fixed** /
**Internal**.

## [Unreleased]

Tracked for v0.6: scale-honesty bucket (real bench at 10⁵ records,
`JSONVectorStore` per-search parse caching, `QdrantVectorStore.known_ids`
caching, incremental `WorkGraph` updates) + CI job for the `[search]` /
`[qdrant]` extras. See [ROADMAP.md](ROADMAP.md).

## [0.5.0] — 2026-07-05

Second adversarial audit — architecture-level. 175 agents across 10 lenses
(API, data model, concurrency, config, error handling, performance,
security/privacy, docs/release, test strategy, DX). 55 raw → 34 confirmed
findings after 3-skeptic verification.

### Added
- Dynamic `__version__` via `importlib.metadata.version("coviber")` —
  `pyproject.toml` is the single source of truth; `coviber.__version__`
  tracks it automatically ([#32](https://github.com/punitmishra/coviber/pull/32)).
- Configuration reference tables in `README.md` + `ARCHITECTURE.md`
  documenting every env var, config-file key, default, and precedence.
- Invariants section in `ARCHITECTURE.md`: id excludes ts/channel by
  design; no lock across full ingest cycle; records stored verbatim
  without PII redaction; config re-read per MCP call.
- `Store.load_graph()` — shared defensive-read helper collocated with
  `Store.save_graph()` ([#33](https://github.com/punitmishra/coviber/pull/33)).
- New tests: `test_custom_weights_change_ceiling_without_clamp`,
  `test_bad_config_raises_config_error_per_tool_not_server_crash`,
  `test_embedding_search_always_returns_hits_up_to_limit`.

### Changed
- Entry-point loader failures now emit `RuntimeWarning` naming the
  entry-point + exception (was: silent swallow) — third-party plugin
  breakage is now observable ([#32](https://github.com/punitmishra/coviber/pull/32)).
- `resolve()` in `vector_stores.py` prints a stderr warning when the
  Qdrant URL is not a loopback hostname — local-first boundary explicit.
- CI's MCP smoke test uses a name-set assertion instead of a magic
  count of 7. Renaming or dropping a tool now shows in the diff.
- `urgency.score()` docstring: honest about the loosened contract
  ("bounded by sum of fired weights") — the "clamped" comment lie is gone.
- `Record.from_dict` now warns (deduped) on unknown fields — a downgrade
  or shared-store user sees when their data carries fields this coviber
  can't represent ([#33](https://github.com/punitmishra/coviber/pull/33)).
- `Store.upsert` tmp filenames are PID+uuid-tagged, matching the
  `JSONVectorStore._persist` / `save_graph` pattern.
- `Path(data_dir).expanduser()` at the single `Store.__init__` choke
  point — CLI, env, YAML, and direct construction now behave identically
  when the path contains `~`.
- CLI `graph` subcommand uses `Store.load_graph()` — same defensive read
  semantics as the MCP tools.
- MCP `who_is` lookup is case-insensitive at the tool boundary (v0.4
  lowercased keys; v0.5 makes lookups accept either form).

### Fixed
- The pre-existing failing test that survived v0.4 is fixed
  ([#25](https://github.com/punitmishra/coviber/issues/25)/audit): the
  `Store.search('...') == []` assertion is now split into two backend-
  forced tests (`no_embedder()` for the keyword path,
  `fake_embedder()` for the embedding path). **133 pass, 0 failures.**

### Filed (tracked for future releases)
- 12 audit findings tracked as
  [#34](https://github.com/punitmishra/coviber/issues/34)–[#45](https://github.com/punitmishra/coviber/issues/45).
- 5 structurally-missing items tracked as
  [#47](https://github.com/punitmishra/coviber/issues/47)–[#51](https://github.com/punitmishra/coviber/issues/51)
  (property tests, real bench at scale, alias resolution, `SECURITY.md`,
  streaming MCP tools).
- 2 core-design coverage items tracked as
  [#52](https://github.com/punitmishra/coviber/issues/52) (draft-response
  orchestration) and
  [#53](https://github.com/punitmishra/coviber/issues/53) (brain memory).

## [0.4.0] — 2026-07-05

First adversarial audit — line-level. 142 agents across 7 layers of code.
45 raw → 35 confirmed findings after 3-skeptic verification. All 35 landed.

### Added
- `test_persona.py` — first coverage for the persona module (9 tests).
- `tests/test_webscrape_loader.py` — 3 tests, gated on `bs4` via
  `importorskip`.
- 5 IMAP protocol-fake tests: happy-path mapping, `unread_only`, `limit`
  newest-first, select-failure logout, fetch-failure skip.
- `Store.load_graph()` defensive reads; `_load_graph` helper for MCP
  tools; new tests for `graph_summary` KeyError-proofing and
  `refresh()` error strings.

### Changed
- `Record._normalize_ts` coerces non-string ts values via `str(...)` —
  an int-epoch or bool ts in `records.jsonl` no longer crashes the store
  on read.
- `Store.save_graph` writes atomically (write-tmp-then-rename), matching
  `upsert`'s pattern. A SIGINT mid-write no longer leaves a torn
  `workgraph.json`.
- `JSONVectorStore._persist` uses PID+uuid-tagged tmp filenames — two
  concurrent `search()` callers on the same data_dir can't stomp on a
  shared `.json.tmp`.
- `Store.search()` narrows the bare-except to `ImportError`; other
  exceptions (CUDA OOM, HF hub failures, corrupt cache) log +
  `warnings.warn` and set `last_search_backend =
  "keyword (embedding failed)"` so operators can tell "extras missing"
  from "extras broken".
- Vectors persist at float32 precision (halves JSON size vs the float64
  upcast at no meaningful signal loss).
- `Mbox` and `Imap` loaders reject non-positive `limit` values (were
  silent selection corruption).
- `Imap` loader passes a `timeout` (default 30s) to `IMAP4_SSL` — no
  more indefinite hangs on a wedged server.
- `WebScrape` html-vs-filepath detection uses `Path.is_file()` — inline
  HTML no longer misfires as a path; any file extension works.
- `WorkGraph`: word-boundary project matching; PR ticket canonicalization
  (`PR #482` / `PR#482` / `PR   #482` → single node);
  case-insensitive person identity with `display_name` preservation;
  live `mentions` counters for channels + tickets.
- `Urgency`: FYI phrase matching by token boundary (fixes
  false-positive skips on words like "justifying"); empty `cfg.you`
  guards `@mention` regex; weight-key typos emit a `RuntimeWarning`;
  weight-value errors name the offending key.
- `Persona`: single-line messages don't double-count as opener + closer;
  contractions filtered from signature vocabulary; empty-corpus
  `system_prompt()` returns a sentinel instead of fabricated guidance;
  emoji regex covers `U+2300-U+25FF` (clock, watch, shapes); MCP
  `voice_profile` passes `s.you` to `system_prompt`.
- `MCP`: `_load_graph` catches JSONDecodeError/OSError → readable
  string; `graph_summary` uses `.get()` everywhere; `refresh` wraps
  loader errors; `who_is` is case-insensitive at the tool boundary.

### Fixed
- `pipeline.build_queue` and `urgency.Config.__post_init__` now use
  `is not None` guards — an explicit `action_words: []` in config is
  honored as an opt-out rather than silently reverting to defaults.
- `Store._read_all` broadened to catch corrupt lines with non-string ts.
- `ingest()` reads `store.all()` once instead of twice.
- `Settings.from_dict` field-passthrough tests added.

## [0.3.0] — 2026-07-05

### Added
- IMAP protocol-fake test coverage
  ([#15](https://github.com/punitmishra/coviber/issues/15)) — 6 tests via
  `imaplib` monkeypatch, both documented FETCH response shapes.
- Optional Qdrant vector backend
  ([partial #19](https://github.com/punitmishra/coviber/issues/19)) — new
  `[qdrant]` extra + pluggable `VectorStore` protocol
  (`JSONVectorStore` default, `QdrantVectorStore` opt-in) +
  `docker-compose.yml` for local Qdrant + 12 new tests.

## [0.2.0] — 2026-07-05

### Fixed
- Server-safe config errors ([#12](https://github.com/punitmishra/coviber/issues/12)):
  `ConfigError` replaces `sys.exit` in `read_config` so the MCP server
  survives a bad settings file.
- HTML-only email fallback
  ([#11](https://github.com/punitmishra/coviber/issues/11)): stdlib
  `html.parser` extraction when no `text/plain` part; scripts/styles
  dropped, entities unescaped, `multipart/alternative` still prefers
  plain.
- Corrupt-line quarantine
  ([#13](https://github.com/punitmishra/coviber/issues/13)): skipped
  JSONL lines append to `records.jsonl.bad` before rewrite instead of
  being silently dropped.

### Added
- Configurable per-signal urgency weights
  ([#14](https://github.com/punitmishra/coviber/issues/14)): `Config.weights`
  with `DEFAULT_WEIGHTS`; partial-dict merge; zero disables the signal;
  labels render dynamically from the live weight.

## [0.1.0] — 2026-07-04

Initial clean-room build on 100% synthetic data.

- `Record` with content-hash id + ISO-8601-UTC ts normalization.
- Six loaders: `demo`, `jsonl`, `mbox`, `imap`, `slackexport`,
  `webscrape` — pure stdlib except `webscrape` (`[scrape]` extra).
- `Store` with dedup persistence + atomic write-then-rename + advisory
  file lock; local semantic search via `[search]` extra
  (sentence-transformers) with keyword fallback.
- `WorkGraph` incremental entity extraction (people / projects /
  channels / tickets) with bidirectional links.
- `Urgency` multi-signal triage: `U(r) ∈ [0, 14]`, test-pinned.
- `Persona` inference-free voice profile → system prompt.
- MCP server (stdio) with 7 tools:
  `recall`, `catch_me_up`, `who_is`, `project_status`, `graph_summary`,
  `voice_profile`, `refresh`.
- Merge train ([#1–#7](https://github.com/punitmishra/coviber/pulls?q=is%3Apr+is%3Aclosed+base%3Amain))
  landing timestamp normalization, atomic file lock, honest urgency
  contract, persisted embedding index, slackexport loader, MCP config
  parity, email loaders.

Apache-2.0. See [DATASHEET](DATASHEET.md), [ARCHITECTURE](ARCHITECTURE.md),
[ROADMAP](ROADMAP.md), [WHITEPAPER](WHITEPAPER.md).

[Unreleased]: https://github.com/punitmishra/coviber/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/punitmishra/coviber/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/punitmishra/coviber/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/punitmishra/coviber/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/punitmishra/coviber/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/punitmishra/coviber/releases/tag/v0.1.0
