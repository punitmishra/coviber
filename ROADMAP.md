# Roadmap

v0.1 is a working, tested core: loaders → dedup store → work graph → urgency
triage → persona → MCP. This file tracks what's next and what's consciously
deferred. Numbers and behavior stay reproducible on the synthetic corpus.

## v0.2 (near term)

- **Persisted embedding index.** The zero-dependency store re-encodes every
  record per query (the README's ~900 ms caveat). Persist vectors alongside
  `records.jsonl` and only encode deltas; report the active backend in
  `coviber query` output the way `bench/run.py` now does.
- **MCP server configurability.** `coviber serve` only reads `COVIBER_DATA_DIR`
  / `COVIBER_YOU`, so `catch_me_up` can never fire the priority-sender or
  collaborator signals. Add `COVIBER_CONFIG` pointing at the same YAML/JSON
  file the CLI accepts.
- **De-identified whitepaper.** Re-derive the evaluation on the `demo` corpus
  and publish the full paper (`WHITEPAPER.md` is currently a stub by design).
- **More loaders.** IMAP/mbox and Slack-export-directory loaders — the two most
  requested real sources; both fit the existing 10-line `Loader` pattern.

## Later

- **Concurrent-writer safety.** `Store.upsert` is read-merge-rewrite (now
  atomic via temp file + rename, but last-writer-wins). A lock file around the
  cycle makes CLI + long-running MCP server safe on the same data dir.
- **Timestamp normalization.** `last_seen` compares raw ts strings, which is
  only correct for uniform ISO-8601 input; normalize on ingest.
- **Dedup granularity policy.** The content-hash id deliberately excludes
  `ts`/`channel`, so a recurring identical message (a bot's daily "build
  passed") collapses into one record. Right default for re-scrape dedup; wrong
  for audit trails. Make it a per-loader choice.
- **Urgency calibration.** The documented ceiling is 15 but the summed signal
  weights max out at 14; either make 15 reachable or re-document the contract.
  Expose per-signal weights in config.
- **Incremental graph updates.** The graph is rebuilt from the full store each
  ingest — O(n) per cycle, fine at 10⁴ records, wasteful at 10⁶.
