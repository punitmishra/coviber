# CoViber — Claude Code / contributor operating guide

**CoViber — a local-first, privacy-preserving memory engine that gives any LLM
continuous personal context via MCP. Your data stays on your machine.**

This is a clean-room open-source project, developed and published in public.
Read this file first every session.

## 🚦 The gate — read before doing anything that could go public

This repo must stay a **clean-room build**: a local memory engine on
**synthetic / the user's own data only**. **Zero** proprietary code, data,
names, customers, internal hosts, or internal benchmarks — from any employer
or third party. If anything proprietary is present, it does not ship.

Before `git push`, publishing, or pasting repo content anywhere public:

```bash
./.gate-scan.sh     # local-only and gitignored; MUST print PASS
```

`.gate-scan.sh` greps the tracked tree for a private token list (names that
must never appear here) plus generic secret/PII patterns. It is intentionally
**gitignored** so the token list never becomes a public trace. If the file is
missing, ask the maintainer to restore it — never inline the tokens into a
committed file.

- The synthetic corpus (`coviber/loaders/demo.py`, `examples/`) is the
  substrate for **all** demos, tests, and published numbers. Never replace it
  with real data.
- `WHITEPAPER.md` is a **stub**: the public evaluation must be re-derived on
  the `demo` corpus before the full paper lands here (see [ROADMAP](ROADMAP.md)).
- Provenance: the *architecture* was generalized from a private production
  system by the author; **no source or data from that system is in this
  repo** — that is the whole reason the synthetic corpus exists.

## What this is (positioning)

Local-first + privacy-preserving + MCP-native is the differentiator: cloud
memory layers fix LLM amnesia by uploading your life; CoViber keeps the memory
on your machine and serves it to the model over MCP.

## Architecture (one seam: the Loader)

A `Loader` turns any source → canonical `Record`s. Everything downstream is
loader-agnostic. Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

| module | role |
|--------|------|
| `coviber/record.py` | canonical `Record` (content-hash id → dedup; ts normalized to ISO UTC) |
| `coviber/loaders/` | `Loader` interface + registry; built-ins: `demo`, `jsonl`, `webscrape`, `mbox`, `imap`, `slackexport` |
| `coviber/workgraph.py` | people·projects·channels·tickets graph (O(1)/record) |
| `coviber/urgency.py` | multi-signal urgency score `U(r) ∈ [0,14]` + skip filter |
| `coviber/persona.py` | inference-free statistical voice model |
| `coviber/store.py` | dedup JSONL (atomic rewrite, write-locked) + persisted embedding cache / cosine search |
| `coviber/config.py` | shared YAML/JSON settings parsing (CLI + MCP server) |
| `coviber/pipeline.py` | `ingest()` cycle |
| `coviber/mcp_server.py` | MCP tools over stdio (7 tools) |
| `coviber/cli.py` | `coviber demo/ingest/triage/query/graph/serve/loaders` |

## Dev commands

```bash
pip install -e ".[all,dev]"        # core is dependency-free; extras: scrape, search, mcp
python -m pytest                   # 59 tests, keep green (mcp-gated ones skip without the extra)
ruff check .                       # lint — config in pyproject.toml, must stay clean
python bench/run.py --scale 2000   # reproducible benchmark (real numbers only)
coviber demo                       # end-to-end on synthetic data
coviber serve                      # local MCP server (stdio)
```

CI (`.github/workflows/ci.yml`) runs lint, the test matrix (3.9/3.11/3.13), a
zero-dependency core job, and an MCP tool-registration smoke test. All must
stay green; they are the required checks for merging to `main`.

## Conventions (do not break)

- **Local-first / graceful degradation.** No feature may require cloud egress
  or telemetry. Heavy deps go behind an extra in `pyproject.toml` and are
  imported **lazily** inside the module that needs them; degrade to a working
  fallback when absent.
- **`mcp_server.py` must NOT use `from __future__ import annotations`.**
  FastMCP introspects real annotation classes; stringized annotations break
  tool registration. (CI's mcp job guards this.)
- **Adding a source = a new Loader**, never core changes. Subclass `Loader`,
  `@register("name")`, yield `Record`s, add a test, add a README line.
  Third-party loaders register via the `coviber.loaders` entry-point group.
- **Benchmarks must be reproducible** on the synthetic corpus — no
  unverifiable numbers, and the reported search backend must be the one that
  actually ran. State caveats (e.g. search re-encodes per query = upper bound).
- **License:** Apache-2.0. New files inherit it; keep `NOTICE` accurate.
- Match the existing terse, comment-light-but-purposeful style (ruff is
  configured to allow the one-line `x; y` idiom deliberately).
- Python floor is **3.9** (`requires-python`); no 3.10+ syntax or
  stdlib-API-without-shim outside the `[mcp]`-gated module.

## Status (2026-07 — v0.4.0, post two adversarial audit passes)

Built & verified: Record (ISO-UTC ts) + 6 loaders (demo/jsonl/webscrape/mbox/
imap/slackexport), WorkGraph (case-insensitive person identity, word-boundary
project matching), urgency triage (`[0, 14]` at defaults, custom weights raise
the ceiling with the caller's eyes open), persona engine (empty-corpus sentinel,
contraction filter), store (atomic dedup + advisory write lock + persisted
embedding cache, PID+uuid-tagged tmp files, corrupt-line quarantine), optional
Qdrant backend via the `[qdrant]` extra + `docker-compose.yml`, pipeline, CLI,
MCP server (7 tools, `COVIBER_CONFIG` parity, torn-graph defensive reads),
130+ tests green, reproducible bench, CI (3.9/3.11/3.13 + zero-dep core + mcp
name-set smoke), Apache-2.0 + NOTICE + CITATION + DATASHEET + ARCHITECTURE
+ CONTRIBUTING + SECURITY + issue templates + PR template.

Two adversarial audit passes have landed on this codebase:
- **v0.4 layer audit** (142 agents, 45 → 35 findings, 7 layer PRs).
- **v0.5 architect audit** (175 agents, 55 → 34 findings, docs/DX/contract PRs +
  12 tracked issues + accepted-invariants section in `ARCHITECTURE.md`).

## What's next → see [ROADMAP.md](ROADMAP.md)

## Git / check-in workflow

- `main` is the default branch and is protected (PR + green CI required; the
  ruleset lives at `.github/rulesets/main-branch-protection.json`).
- For a feature, branch: `git checkout -b feat/<x>`. Commit in logical units;
  run tests + the gate scan before committing.
- **Never** commit real data, secrets, or `coviber_data/` (gitignored).
- Only push when the user asks. On any public push, run the gate scan first.
