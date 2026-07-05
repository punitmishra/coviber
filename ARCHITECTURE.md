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
 │ jsonl / api  │──────────▶ │     ├─▶ Urgency triage  (U(r) ∈ [0,15])          │       Desktop/Code
 │ demo (synth) │──────────▶ │     └─▶ PersonaEngine (inference-free voice)     │       any MCP client
 └──────────────┘            └────────────────────────────────────────────────┘
                                        all on local disk · no cloud egress
```

## Modules (map 1:1 to the whitepaper)
| File | Role | Paper §|
|------|------|--------|
| `record.py` | Canonical `Record`; content-hash `id` for natural dedup | 3.2 |
| `loaders/` | `Loader` interface + registry; `demo`/`jsonl`/`webscrape` built-ins | 3.3 |
| `workgraph.py` | Incremental entity extraction + bidirectional links, O(1)/record | 3.4 |
| `urgency.py` | Multi-signal urgency score + skip filter | 3.5 |
| `persona.py` | Statistical, inference-free voice model | 3.6 |
| `store.py` | Dedup persistence + local semantic search | 3.3, 3.7 |
| `pipeline.py` | `ingest()` cycle: load → store → graph → (triage on demand) | 3.3 |
| `mcp_server.py` | MCP tools over stdio (`recall`, `catch_me_up`, `who_is`, …) | 3.8 |

## Design decisions
- **One seam.** New source = new `Loader`, not new core code. Registered via
  `@register` or the `coviber.loaders` entry-point group.
- **Local-first.** Records, graph, and vectors live on disk; the MCP transport is
  stdio to a local process. No network is required for any core operation.
- **Graceful degradation.** Core is standard-library only. `[search]`, `[scrape]`,
  and `[mcp]` are opt-in extras; each degrades to a working fallback when absent
  (keyword search instead of embeddings; a clear error instead of a crash).
- **Inference-free voice.** Persona modelling is pure statistics — fast, private,
  and deterministic; no model call to draft in your style.

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
