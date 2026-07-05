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
**`mbox`** / **`imap`** (email, pure stdlib), **`slackexport`** (Slack workspace
export dir, pure stdlib), **`webscrape`** (config-driven CSS selectors — no
per-site code).

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
      "env": { "COVIBER_YOU": "you", "COVIBER_CONFIG": "~/.coviber/config.yaml" }
    }
  }
}
```

`COVIBER_CONFIG` points the server at the same YAML/JSON settings file the CLI
takes, so `catch_me_up` scores with your `priority_senders`, `collaborators`,
`known_projects`, and skip rules — identical to `coviber triage --config`.

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

### Scale past ~10⁵ records with Qdrant (optional)

The default `JSONVectorStore` loads all vectors on every query — fine up to
around 10⁵ records, dominated by load cost past that. When you need more, add
Qdrant as the vector backend without changing anything else:

```bash
docker compose up -d                    # starts qdrant on :6333, data in ./data/qdrant/
pip install -e ".[qdrant,search]"       # qdrant-client + the local embedder
COVIBER_QDRANT_URL=http://localhost:6333 coviber ingest --loader demo
COVIBER_QDRANT_URL=http://localhost:6333 coviber query "your query"
# backend: embeddings (all-MiniLM-L6-v2) via QdrantVectorStore
```

Same result shape, same encoder — Qdrant just handles the vector store and
ANN search server-side, so query cost stops growing with corpus size.
Configuration goes through `qdrant:` in the settings file for reproducibility:

```yaml
qdrant:
  url: http://localhost:6333
  collection: coviber_records   # default
  # api_key: put credentials in COVIBER_QDRANT_API_KEY, not the config file
```

The config parser does not perform shell-style `${VAR}` interpolation —
put credentials in `COVIBER_QDRANT_API_KEY` and leave the YAML clean.
Any non-loopback URL will print a stderr warning at startup so a
copy-pasted managed-cluster URL doesn't silently exfiltrate embeddings.

Delete `./data/qdrant/` (or call `store._vectors.wipe()`) to reset the index.
Switching between backends is safe — model tags are persisted per backend, so
each rebuilds its own index the first time it runs.

### Configuration reference

Every configurable value has one canonical config-file key and, for a few
runtime overrides, an environment variable. Precedence: CLI flags →
env → config file → dataclass defaults.

| Env var                    | Config file key       | Default              | Notes                                                              |
|----------------------------|-----------------------|----------------------|--------------------------------------------------------------------|
| `COVIBER_CONFIG`           | *(loads the file)*    | *(none)*             | Path to a YAML/JSON settings file, honored by both CLI and MCP.    |
| `COVIBER_DATA_DIR`         | `data_dir`            | `./coviber_data`     | Where `records.jsonl` / `embeddings.json` / `workgraph.json` live. |
| `COVIBER_YOU`              | `you`                 | `you`                | The identity `@you` mentions match against and self-authored dedup. |
| `COVIBER_QDRANT_URL`       | `qdrant.url`          | *(none)*             | Set → Qdrant backend; unset → default JSON vector store.           |
| `COVIBER_QDRANT_COLLECTION`| `qdrant.collection`   | `coviber_records`    | Qdrant collection name.                                            |
| `COVIBER_QDRANT_API_KEY`   | `qdrant.api_key`      | *(none)*             | Credentials belong in env; the YAML file does no `${VAR}` expansion. |
| `COVIBER_IMAP_PASSWORD`*   | `loader.password_env` | *(none)*             | *IMAP secrets never live in config: set `password_env` to the env-var name.* |

*The IMAP loader's contract is "the config file names an env var it reads
the password from" — `COVIBER_IMAP_PASSWORD` is the conventional name but
any env var works.

## Use your own data

**Anything → JSONL** (one record per line; any subset of fields):

```bash
coviber ingest --loader jsonl --path examples/acme_demo.jsonl
coviber triage
```

**Email (mbox/IMAP)** — pure stdlib, nothing to install:

```bash
coviber ingest --loader mbox --path ~/mail.mbox
```

```yaml
# imap.yaml — the password stays in the environment, never in config
loader: imap
config:
  host: imap.example.com
  username: you@example.com
  password_env: COVIBER_IMAP_PASSWORD   # name of the env var holding the password
  mailbox: INBOX
  limit: 200
  unread_only: true
```

```bash
COVIBER_IMAP_PASSWORD=... coviber ingest --config imap.yaml
```

**Slack workspace export** (the zip Slack gives you, extracted):

```bash
coviber ingest --loader slackexport --path ~/slack-export   # YAML config adds: channels: [...], you: "your name"
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

@register("mycrm")
class MyCrmLoader(Loader):
    def load(self):
        for note in fetch_crm(self.config):        # your source
            yield Record(source="crm", from_name=note.author,
                         subject=note.title, text=note.body, unread=note.unread)
```

Register it in your package's entry points and `coviber ingest --loader mycrm` just works:

```toml
[project.entry-points."coviber.loaders"]
mycrm = "my_pkg.crm:MyCrmLoader"
```

## How it works (the four pieces, from the paper)

| Component | What it does |
|-----------|--------------|
| **Loader** | Source → canonical `Record` stream. The swappable seam. |
| **WorkGraph** | Incremental entity extraction (people/projects/channels/tickets) with bidirectional links — O(1) per record. |
| **Urgency** | `U(r) ∈ [0,14]` from @mentions, priority senders, action words, questions, unread, no-reply, collaborators, and age; plus a skip filter for bots/newsletters/FYI. |
| **Store** | Content-hash dedup (re-ingest = update, not duplicate) + local embeddings/cosine search. |

## Benchmarks (reproducible on the synthetic corpus)

`python bench/run.py --scales 1000,10000,100000` — median of repeats,
single core, JSON persistence, keyword search backend:

| scale | ingest + dedup | graph build | urgency triage | search (cold / warm) |
|------:|---------------:|------------:|---------------:|---------------------:|
| 1 000    | 32 ms   | 12 ms   | 11 ms  | 8 ms / 7 ms |
| 10 000   | 194 ms  | 124 ms  | 103 ms | 73 ms / 71 ms |
| 100 000  | 1 848 ms | 1 327 ms | 1 076 ms | 739 ms / 760 ms |

`python bench/run.py --scales 1000,10000 --search-mode auto` — with the
`[search]` extra installed (sentence-transformers `all-MiniLM-L6-v2`,
384-dim, JSONVectorStore backend):

| scale | search cold | search warm |
|------:|------------:|------------:|
| 1 000  | 27 s* | 196 ms |
| 10 000 | 6.6 s | 1.3 s |

\* first cold call downloads the encoder model — subtract that. Warm
numbers are what a real user sees.

Every number above is written to `bench/results/*.json` alongside a git
sha and hardware fingerprint, so releases can bisect regressions. See
[bench/run.py](bench/run.py) for the harness and [DATASHEET](DATASHEET.md)
for the corpus. Reproduce yours with:

```bash
python bench/run.py --scales 1000,10000,100000 --output bench/results/mine.json
```

The 100 000-record graph rebuild at 1.3 s per ingest is the source of
issue [#18](https://github.com/punitmishra/coviber/issues/18)
(incremental updates) — the numbers exist to be improved.

## Design principles
- **Local-first** — records, graph, and vectors stay on disk. No data leaves your machine.
- **Privacy-preserving** — no cloud egress, no telemetry, no account.
- **Loader-agnostic core** — one seam to extend; the brain never changes.
- **Degrades gracefully** — core is stdlib-only; search/scrape/MCP are opt-in extras.
- **MCP-native** — exposes context to an LLM via the Model Context Protocol.

## Docs
[Architecture](ARCHITECTURE.md) · [Whitepaper](WHITEPAPER.md) · [Datasheet](DATASHEET.md) · [Contributing](CONTRIBUTING.md)

## Status & license
v0.5 — a clean-room build on 100% synthetic data (see [DATASHEET](DATASHEET.md)).
Apache-2.0. Contributions of new loaders welcome — see [CONTRIBUTING](CONTRIBUTING.md).
