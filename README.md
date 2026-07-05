# CoViber

**Local-first memory for LLMs.** Give Claude (or any MCP client) continuous,
personal context — persona, priorities, history — without sending your data to
the cloud.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
&nbsp;Local-first · Privacy-preserving · MCP-native · No telemetry

## Why
LLMs forget everything between sessions. Cloud memory tools fix that by uploading
your life. CoViber keeps memory **on your machine**, exposes it over the Model
Context Protocol, and models your voice + urgency with fast, inference-free
statistics.

CoViber keeps a live, incrementally-updated model of your professional
context — who you work with, what projects and tickets are in flight, and what
actually needs your attention right now — and exposes it to an LLM locally. No
cloud egress; everything runs on your machine.

Unlike RAG over static documents or single-shot agent frameworks, CoViber
maintains a **continuously-updated** view across every source you plug in, and
turns it into three things:

- a **work graph** — people ↔ projects ↔ channels ↔ tickets, cross-linked automatically;
- a **triage queue** — a multi-signal urgency score over the raw stream, so the important stuff surfaces;
- a **semantic memory** — local embeddings for "what did I miss about X?".

> 📄 Design & evaluation: see [`WHITEPAPER`](./WHITEPAPER.md) — *Continuous Context Replication for AI-Augmented Knowledge Work*.

---

## The idea: swap the loader, keep the brain

The one thing that differs between people and companies is **where the context
comes from**. So that's the only thing CoViber makes pluggable. A `Loader` turns
*any* source — an email inbox, a Slack export, a web page, a JSONL dump, an
internal API — into canonical records. Everything downstream (dedup → graph →
urgency → search → MCP) is loader-agnostic.

```
   your sources                    the brain (loader-agnostic)
 ┌───────────────┐   Loader   ┌──────────────────────────────────────┐
 │ email / IMAP  │──────────▶ │  dedup ─▶ WorkGraph ─▶ urgency triage │
 │ Slack export  │──────────▶ │            └─▶ semantic search        │──▶ LLM (MCP)
 │ web scrape    │──────────▶ │                                        │
 │ JSONL / API   │──────────▶ │  local disk · no cloud egress          │
 └───────────────┘            └──────────────────────────────────────┘
```

Built-in loaders: **`demo`** (synthetic, zero-setup), **`jsonl`** (universal),
**`webscrape`** (config-driven CSS selectors — no per-site code).

## Quickstart (30 seconds)

```bash
pip install -e ".[mcp,search]"   # core is dependency-free; extras add MCP + local embeddings
coviber demo                     # ingest synthetic data → show graph + triage
coviber serve                    # start the local MCP server (stdio)
```

Point your MCP client at the local server — done. No account, no cloud, no telemetry.

**Claude Desktop** (`claude_desktop_config.json`) / **Claude Code** (`.mcp.json`):

```json
{
  "mcpServers": {
    "coviber": {
      "command": "coviber",
      "args": ["serve", "--data-dir", "~/.coviber"],
      "env": { "COVIBER_YOU": "you" }
    }
  }
}
```

MCP tools exposed: `recall` (semantic search), `catch_me_up` (urgency queue),
`who_is` / `project_status` / `graph_summary` (work graph), `voice_profile`
(inference-free style prompt), `refresh` (ingest via any loader).

### Or just try it (zero setup)

```bash
pip install -e .          # core has no dependencies
coviber demo              # ingest synthetic data → show graph + triage
```

```
loader=demo  loaded=15  new=15  total=15
graph: 7 people · 3 projects · 8 channels · 4 tickets
projects: Atlas, Falcon, Orbit

# Triage — 8 actionable item(s)
1. [ 6] 🔴🔴🔴🔴🔴🔴  Grace Hopper · email/inbox
     Re: Falcon launch sign-off needed
     signals: priority-sender+2, action-word+2, question+1, unread+1
2. [ 5] 🔴🔴🔴🔴🔴  Linus Vega · slack/dm
     DM: Linus Vega
     signals: @mention+3, question+1, collaborator+1
...
```

Add semantic search (local embeddings, still offline):

```bash
pip install -e ".[search]"
coviber query "GPU fallback for embeddings"
# [0.582] Ada Byron · email/inbox — Question about the Orbit embedding router
```

## Use your own data

**Anything → JSONL** (one record per line; any subset of fields):

```bash
coviber ingest --loader jsonl --path examples/acme_demo.jsonl
coviber triage
```

**Scrape a page** (structure lives in config, not code):

```bash
pip install -e ".[scrape]"
coviber ingest --config examples/scrape_config.example.yaml
```

## Write your own loader (≈10 lines)

```python
from coviber import Record, register
from coviber.loaders.base import Loader

@register("imap")
class ImapLoader(Loader):
    def load(self):
        for msg in fetch_imap(self.config):        # your source
            yield Record(source="email", from_name=msg.sender,
                         subject=msg.subject, text=msg.body, unread=msg.unread)
```

Register it in your package's entry points and `coviber ingest --loader imap` just works:

```toml
[project.entry-points."coviber.loaders"]
imap = "my_pkg.imap:ImapLoader"
```

## How it works (the four pieces, from the paper)

| Component | What it does |
|-----------|--------------|
| **Loader** | Source → canonical `Record` stream. The swappable seam. |
| **WorkGraph** | Incremental entity extraction (people/projects/channels/tickets) with bidirectional links — O(1) per record. |
| **Urgency** | `U(r) ∈ [0,15]` from @mentions, priority senders, action words, questions, unread, no-reply, collaborators, and age; plus a skip filter for bots/newsletters/FYI. |
| **Store** | Content-hash dedup (re-ingest = update, not duplicate) + local embeddings/cosine search. |

## Benchmarks (reproducible on the synthetic corpus)

`python bench/run.py --scale 2000` — median of repeats, single core:

| stage | latency | throughput |
|-------|--------:|-----------:|
| ingest + dedup | 42 ms | 47,000 rec/s |
| work-graph build | 8 ms | 262,000 rec/s |
| urgency triage (full scan) | 7 ms | 298,000 rec/s |
| semantic search (top-8) | ~900 ms* | — |

\* the zero-dependency store re-encodes records per query (upper bound); a
persisted embedding index removes this. Numbers scale with `--scale` and
hardware — reproduce them yourself, no unverifiable claims. See [DATASHEET](DATASHEET.md).

## Design principles
- **Local-first** — records, graph, and vectors stay on disk. No data leaves your machine.
- **Privacy-preserving** — no cloud egress, no telemetry, no account.
- **Loader-agnostic core** — one seam to extend; the brain never changes.
- **Degrades gracefully** — core is stdlib-only; search/scrape/MCP are opt-in extras.
- **MCP-native** — exposes context to an LLM via the Model Context Protocol.

## Docs
[Architecture](ARCHITECTURE.md) · [Whitepaper](WHITEPAPER.md) · [Datasheet](DATASHEET.md) · [Contributing](CONTRIBUTING.md)

## Status & license
v0.1 — a clean-room build on 100% synthetic data (see [DATASHEET](DATASHEET.md)).
Apache-2.0. Contributions of new loaders welcome — see [CONTRIBUTING](CONTRIBUTING.md).
