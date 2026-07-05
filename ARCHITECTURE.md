# Architecture

CoViber is a **loader-agnostic memory engine**. The only pluggable seam is where
context comes from; everything else — graph, triage, memory, MCP — is fixed and
source-independent.

```
  SOURCES                        CORE (loader-agnostic, local-only)                CLIENTS
 ┌──────────────┐   Loader   ┌────────────────────────────────────────────────┐
 │ email / IMAP │──────────▶ │  Record ─▶ Store (dedup, JSONL/parquet)         │
 │ slack export │──────────▶ │     │         └─▶ embeddings + cosine  ◀── recall│
 │ web scrape   │──────────▶ │     ├─▶ WorkGraph (people·projects·tickets)      │──MCP──▶ Claude
 │ jsonl / api  │──────────▶ │     ├─▶ Urgency triage  (U(r) ∈ [0,14])          │       Desktop/Code
 │ demo (synth) │──────────▶ │     └─▶ PersonaEngine (inference-free voice)     │       any MCP client
 └──────────────┘            └────────────────────────────────────────────────┘
                                        all on local disk · no cloud egress
```

## Modules (map 1:1 to the whitepaper)
| File | Role | Paper §|
|------|------|--------|
| `record.py` | Canonical `Record`; content-hash `id` for natural dedup; `ts` normalized to ISO-8601 UTC | 3.2 |
| `loaders/` | `Loader` interface + registry; `demo`/`jsonl`/`webscrape` built-ins | 3.3 |
| `workgraph.py` | Incremental entity extraction + bidirectional links, O(1)/record | 3.4 |
| `urgency.py` | Multi-signal urgency score + skip filter | 3.5 |
| `persona.py` | Statistical, inference-free voice model | 3.6 |
| `store.py` | Dedup persistence (writers serialize on an advisory file lock) + local semantic search | 3.3, 3.7 |
| `vector_stores.py` | Pluggable vector-index backends: `JSONVectorStore` (default) or `QdrantVectorStore` (optional, [qdrant] extra) | 3.7 |
| `pipeline.py` | `ingest()` cycle: load → store → graph → (triage on demand) | 3.3 |
| `mcp_server.py` | MCP tools over stdio (`recall`, `catch_me_up`, `who_is`, …) | 3.8 |

## Design decisions
- **One seam.** New source = new `Loader`, not new core code. Registered via
  `@register` or the `coviber.loaders` entry-point group.
- **Local-first.** Records, graph, and vectors live on disk; the MCP transport is
  stdio to a local process. No network is required for any core operation. When
  Qdrant is configured, it typically runs as a local Docker container — the data
  never leaves your machine unless you point it at a remote URL yourself.
- **Graceful degradation.** Core is standard-library only. `[search]`, `[scrape]`,
  `[qdrant]`, and `[mcp]` are opt-in extras; each degrades to a working fallback
  when absent (keyword search instead of embeddings; JSON vector file instead of
  Qdrant; a clear error instead of a crash).
- **Inference-free voice.** Persona modelling is pure statistics — fast, private,
  and deterministic; no model call to draft in your style.

## Vector backends
The default `JSONVectorStore` writes all vectors to one `embeddings.json` next
to `records.jsonl`. Zero-dep, human-inspectable, fine up to ~10⁵ records. When
that ceiling matters, set `COVIBER_QDRANT_URL` or a `qdrant:` block in the
config file to route persistence and search to a `QdrantVectorStore`. Same
encoder, same cosine metric — Qdrant just handles storage and ANN server-side
so query cost stops growing with the corpus. Model changes invalidate the
index (a sidecar `qdrant.meta.json` tracks the persisted model tag).

## Extending
```python
from coviber import Record, register
from coviber.loaders.base import Loader

@register("myapp")
class MyAppLoader(Loader):
    def load(self):
        for row in fetch(self.config):
            yield Record(source="myapp", from_name=row.author, text=row.body)
```
Then `coviber ingest --loader myapp` and the graph/triage/recall/MCP all light up.

## Configuration reference
The full env-var and config-file surface, in one place. Precedence:
CLI flags → environment → `COVIBER_CONFIG` YAML/JSON → dataclass defaults.

| Env var                     | Config-file key       | Default              | Notes                                                              |
|-----------------------------|-----------------------|----------------------|--------------------------------------------------------------------|
| `COVIBER_CONFIG`            | *(loads the file)*    | *(none)*             | Path to a YAML/JSON settings file, honored by both CLI and MCP.    |
| `COVIBER_DATA_DIR`          | `data_dir`            | `./coviber_data`     | Store root; `~` is expanded from every source.                     |
| `COVIBER_YOU`               | `you`                 | `you`                | Identity for `@you` mentions and self-authored filtering.          |
| `COVIBER_QDRANT_URL`        | `qdrant.url`          | *(none)*             | Set → Qdrant backend; unset → default JSON vector store.           |
| `COVIBER_QDRANT_COLLECTION` | `qdrant.collection`   | `coviber_records`    | Qdrant collection name.                                            |
| `COVIBER_QDRANT_API_KEY`    | `qdrant.api_key`      | *(none)*             | Credentials in env, not config; the YAML parser does no `${VAR}` expansion. |
| *(loader-defined)*          | `loader.password_env` | *(none)*             | The IMAP loader's contract: config names the env var it reads the password from — the secret itself never lives in config. |

## Invariants (accepted design choices)

These are deliberate architectural choices that surfaced in reviews. Documented
here so contributors don't relitigate them on a hunch.

- **Content-hash id excludes `channel`, `ts`, and mutable state** (`replied`,
  `unread`). Re-scraping the same message dedups by design; the tradeoff is
  that a genuinely-recurring identical message (a CI bot's daily "build passed")
  collapses to one record. Per-loader granularity is the escape hatch (issue #17).
- **No lock is held across the full `ingest()` cycle.** The advisory
  `_write_lock` covers each `Store.upsert` / `save_graph` write, not the whole
  load→store→graph pipeline. Two concurrent ingests on the same data_dir will
  interleave safely at the write boundaries; they will *not* observe a
  transactional "all of my records then all of yours" view. Not a bug — a design
  point that keeps ingest latency low.
- **Records are stored verbatim.** `records.jsonl` contains the raw scraped
  and email content with no secret-scanner / PII-redactor pass. This is
  consistent with "local-first, on your machine" — nothing leaves the box —
  but it means an operator sharing their `data_dir` (backup, sync, screen-share)
  is sharing everything in it. Encrypt the volume if that matters.
- **Config is re-read on every MCP tool call.** `_settings()` is invoked at
  the top of every tool function; a `COVIBER_CONFIG` edit takes effect on
  the next call, without a server restart. A broken config file fails the
  individual tool call (via `ConfigError`) — it does not kill the server.
  Don't add a module-level settings cache thinking you're optimizing.
- **Python matrix.** CI tests 3.9 / 3.11 / 3.13 — three points across the
  supported range. 3.10 and 3.12 are supported by pyproject's `>=3.9` floor
  but not tested each PR. Bump manually when a version-specific report comes
  in.
