# Roadmap

v0.1 shipped a working, tested core; the first merge train (#1–#7) landed the
highest-leverage items on top of it. This file tracks what's next and what's
consciously deferred. Numbers and behavior stay reproducible on the synthetic
corpus.

## Shipped since v0.1 (the #1–#7 merge train)

- ✅ **Real-source loaders**: `mbox` + `imap` (pure stdlib, `password_env`-only
  credentials, read-only fetch) and `slackexport` (workspace export dir).
- ✅ **Persisted embedding index**: vectors cached in `embeddings.json`, only
  deltas encoded per query; `coviber query` and the bench report the backend
  that actually ran.
- ✅ **MCP config parity**: `COVIBER_CONFIG` / `coviber serve --config` — the
  server now honors the same settings file as the CLI, so priority-sender and
  collaborator signals fire over MCP.
- ✅ **Concurrent-writer safety**: advisory file lock across the store's
  read-merge-write cycle (CLI + MCP server can share a data dir).
- ✅ **Timestamp normalization**: ISO-8601 UTC at the Record boundary; correct
  `last_seen` ordering and real ages for email dates.
- ✅ **Honest urgency contract**: `U(r) ∈ [0,14]`, pinned by test.

## v0.2 (near term)

- **De-identified whitepaper.** Re-derive the evaluation on the `demo` corpus
  and publish the full paper (`WHITEPAPER.md` is currently a stub by design).
- **HTML email fallback.** Multipart messages with no `text/plain` part
  currently yield empty text; add a minimal tag-stripping fallback.
- **IMAP integration smoke.** The imap network path is untested by design
  (offline CI); add an optional containerized test (greenmail/dovecot).
- **Server-safe config errors.** `read_config` inherits the CLI's
  `sys.exit` when pyyaml is missing for a YAML config — raise instead, so an
  MCP tool call degrades to an error message rather than killing the server.

## Later

- **Dedup granularity policy.** The content-hash id deliberately excludes
  `ts`/`channel`, so a recurring identical message (a bot's daily "build
  passed") collapses into one record. Right default for re-scrape dedup; wrong
  for audit trails. Make it a per-loader choice.
- **Per-signal urgency weights** exposed in config (the contract test pins the
  ceiling, so weight changes must revisit it deliberately).
- **Corrupt-line quarantine.** Skipped store lines are warned about but then
  dropped on the next rewrite; quarantine to `records.jsonl.bad` instead.
- **Incremental graph updates.** The graph is rebuilt from the full store each
  ingest — O(n) per cycle, fine at 10⁴ records, wasteful at 10⁶.
- **Real vector index format** if stores outgrow the JSON cache (10⁵+ records).
