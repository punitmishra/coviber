# Unresolved items — whitepaper first draft

## Citations to fill in

- `[abstract-intro]` TODO-rag-lewis-2020: Lewis et al., Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks, NeurIPS 2020 --- or an equivalent survey/canonical RAG reference.
- `[abstract-intro]` TODO-privacy-llm-2024: A recent survey or position paper on privacy risks of hosted LLM memory / personal-data leakage. Could be a Stanford HAI, ACM FAccT, or USENIX Security piece.
- `[abstract-intro]` TODO-mcp-spec: The Model Context Protocol specification (Anthropic, 2024). Likely https://modelcontextprotocol.io/specification or the corresponding announcement post.
- `[related-work]` TODO-rag-lewis-2020 — Lewis et al., 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks', NeurIPS 2020
- `[related-work]` TODO-dense-passage-retrieval — Karpukhin et al., 'Dense Passage Retrieval for Open-Domain Question Answering', EMNLP 2020
- `[related-work]` TODO-langchain-memory — LangChain documentation on Memory modules (BufferMemory, VectorStoreMemory, etc.)
- `[related-work]` TODO-llamaindex — LlamaIndex framework paper or documentation (Liu, 2022)
- `[related-work]` TODO-langgraph — LangGraph project (LangChain, 2024) — stateful multi-actor LLM applications
- `[related-work]` TODO-mem0 — mem0 memory layer for LLMs (mem0.ai) — paper or repo citation
- `[related-work]` TODO-zep — Zep long-term memory service — technical report or repo citation
- `[related-work]` TODO-rewind — Rewind AI — desktop recording + local indexing product citation
- `[related-work]` TODO-mem-ai — Mem.ai — personal knowledge base with LLM-driven organization
- `[related-work]` TODO-karpathy-persona — Andrej Karpathy's tweet/note on statistical persona prompts (informal citation, may need web archive URL)
- `[related-work]` TODO-glean — Glean enterprise search — product/technical citation
- `[related-work]` TODO-copilot-memory — Microsoft 365 Copilot memory/context feature — official documentation
- `[related-work]` TODO-react-yao-2022 — Yao et al., 'ReAct: Synergizing Reasoning and Acting in Language Models', ICLR 2023
- `[related-work]` TODO-toolformer — Schick et al., 'Toolformer: Language Models Can Teach Themselves to Use Tools', NeurIPS 2023
- `[related-work]` TODO-mcp-spec — Anthropic, 'Model Context Protocol Specification' (modelcontextprotocol.io)
- `[related-work]` TODO-stylometry-koppel — Koppel, Schler, Argamon, 'Computational Methods in Authorship Attribution', JASIST 2009
- `[related-work]` TODO-stamatatos-survey — Stamatatos, 'A Survey of Modern Authorship Attribution Methods', JASIST 2009
- `[related-work]` TODO-style-transfer-lample — Lample et al., 'Multiple-Attribute Text Rewriting', ICLR 2019 (or similar style-transfer reference)
- `[related-work]` TODO-controllable-generation — Keskar et al., 'CTRL: A Conditional Transformer Language Model for Controllable Generation', 2019
- `[architecture]` TODO-mcp-spec: Model Context Protocol specification (Anthropic, 2024). Cite the official MCP spec or announcement URL.
- `[architecture]` TODO-crash-consistency: A reference for the write-then-rename crash-consistency pattern on POSIX (e.g. Pillai et al., OSDI 2014 'All File Systems Are Not Created Equal', or the SQLite atomic commit doc).
- `[record-loader]` TODO-coviber-architecture-md — self-cite of the shipped ARCHITECTURE.md invariants section; should resolve to a repository URL or an appendix reference in the final paper
- `[record-loader]` TODO-coviber-issue-17 — GitHub issue #17 on per-loader granularity for the channel-collapse escape hatch; cite as an artifact URL
- `[workgraph]` TODO-issue-18: issue tracker link for the incremental-WorkGraph work item ("issue #18" in the prompt) — resolve to the actual GitHub issue URL in the coviber-oss repo when the bibliography is compiled.
- `[urgency]` TODO-horvitz-priorities — Horvitz et al., "Priorities: A Bayesian User Model for Attention-Sensitive Notification" (or equivalent seminal work on learned inbox prioritisation, e.g. Aberdeen et al. Google Priority Inbox, LREC/CIKM); pick one canonical rule-vs-learned baseline.
- `[store-vectors]` TODO-qdrant — Qdrant vector database: cite the official Qdrant paper or the project's technical documentation (https://qdrant.tech)
- `[store-vectors]` TODO-hnsw — Malkov \& Yashunin, 'Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs', IEEE TPAMI 2020 (arXiv:1603.09320) — cited as the ANN algorithm backing Qdrant's server-side search
- `[mcp-interface]` TODO-mcp-spec — the Model Context Protocol specification (Anthropic, 2024); if a formal spec citation is not available, cite the modelcontextprotocol.io reference and/or the initial Anthropic announcement blog post.
- `[discussion]` TODO-mcp-spec: canonical citation for the Model Context Protocol specification (used implicitly wherever MCP is referenced; the assembler should ensure this appears in the earlier §3.8 bibliography rather than duplicated here)
- `[discussion]` TODO-hypothesis: David MacIver et al., Hypothesis property-based testing library --- cite in the property-based tests paragraph if the assembler wants a footnote
- `[discussion]` TODO-qdrant: Qdrant vector database --- may already be cited in §3.7; if not, add here where Qdrant is named as the scale answer
- `[appendix]` TODO-mcp-spec: Anthropic Model Context Protocol specification, https://spec.modelcontextprotocol.io/
- `[appendix]` TODO-minilm: Wang et al., MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers, NeurIPS 2020 (all-MiniLM-L6-v2 sentence encoder used by the [search] extra)
- `[appendix]` TODO-sentence-transformers: Reimers and Gurevych, Sentence-BERT / sentence-transformers library, EMNLP 2019
- `[appendix]` TODO-qdrant: Qdrant vector database, https://qdrant.tech/documentation/
- `[appendix]` TODO-hnsw: Malkov and Yashunin, Hierarchical Navigable Small World graphs, TPAMI 2020 (ANN index used by Qdrant backend)
- `[appendix]` TODO-jsonl: JSON Lines specification, https://jsonlines.org/
- `[appendix]` TODO-md5: Rivest, RFC 1321 — The MD5 Message-Digest Algorithm (Record.id uses MD5 with usedforsecurity=False as a non-cryptographic dedup key; the paper body states this correctly)
- `[appendix]` TODO-uuid5: RFC 4122 Section 4.3, name-based UUID (used for vector-store point ids in the brain layer)
- `[appendix]` TODO-fcntl-posix: POSIX.1 fcntl advisory locking (used by Store's writer lock)
- `[appendix]` TODO-arxiv-style: arXiv style guide / arxiv.sty template
- `[appendix]` TODO-datasheets: Gebru et al., Datasheets for Datasets, CACM 2021 (motivates DATASHEET.md)
- `[appendix]` TODO-model-cards: Mitchell et al., Model Cards for Model Reporting, FAT* 2019 (companion to datasheet framing for the persona module)
- `[appendix]` TODO-atomic-rename: POSIX rename(2) atomicity semantics (relied on by Store.upsert for crash-safe rewrites)
- `[appendix]` TODO-slack-export-format: Slack workspace export JSON format documentation (used by slackexport loader)
- `[appendix]` TODO-mbox-rfc4155: RFC 4155, The application/mbox Media Type (used by mbox loader)
- `[appendix]` TODO-imap-rfc9051: RFC 9051, Internet Message Access Protocol Version 4rev2 (used by imap loader)

## Eval placeholders (fill from bench/results/)

- `[abstract-intro]` Abstract: ingest throughput in records/second on the synthetic demo corpus (bench/run.py --scale N).
- `[abstract-intro]` Abstract: warm semantic-search latency at 10^5 records (from bench/run.py after the persisted embedding index landed). README currently lists ~900 ms cold-start; a warm number is not yet published.
- `[workgraph]` \SI{XXX}{\milli\second} in \S3.4 Complexity: wall-clock time to rebuild the full WorkGraph on the reference machine at |R| = 10^5 records. Should be produced by bench/run.py running the synthetic demo corpus scaled to 10^5 records, measuring WorkGraph.ingest wall time only (not upsert, not save_graph).
- `[evaluation]` tab:latency — ingest+dedup latency at N=2000, 10^4, 10^5 (JSONL, JSON vector backend). Run: python bench/run.py --scale 2000 / 10000 / 100000. Read 'ingest + dedup (JSONL)' row from stdout.
- `[evaluation]` tab:latency — work-graph build latency at N=2000, 10^4, 10^5. Same runs; read 'work-graph build' row.
- `[evaluation]` tab:latency — urgency triage full-scan latency at N=2000, 10^4, 10^5. Same runs; read 'urgency triage (full scan)' row.
- `[evaluation]` tab:latency — semantic search top-8 warm latency at N=2000, 10^4, 10^5, JSON backend. Same runs; read 'semantic search (top-8)' row. Requires the [search] extra installed (sentence-transformers) — otherwise the row reports keyword-fallback timing, which is not what tab:latency claims.
- `[evaluation]` tab:jsonvsqdrant — JSON cold+warm and Qdrant cold+warm top-8 latency at N=10^3, 10^4, 10^5. Requires a second bench mode (currently only warm-median is emitted). Suggested harness change: bench/run.py --scale N --backend {json,qdrant} --emit-cold, first repeat separated. Qdrant requires local Docker via docker-compose.yml plus the [qdrant] extra installed.
- `[evaluation]` tab:workgraph-truth — the values in Extracted/Precision/Recall columns are inline (3/7/4 and 1.00) rather than XXX placeholders because they follow deterministically from the code and the demo corpus. Verify by asserting `WorkGraph(known_projects=['Falcon','Orbit','Atlas']).ingest(_DATA).summary()` returns {people: 7, projects: 3, tickets: 4} — a one-liner unit test would be ideal here.
- `[appendix]` Reference machine CPU model + physical/logical core count (\S\ref{app:hardware})
- `[appendix]` Reference machine RAM in GB (\S\ref{app:hardware})
- `[appendix]` Reference machine OS + version string (\S\ref{app:hardware})
- `[appendix]` Reference machine Python interpreter version used for the numbers in the paper (\S\ref{app:hardware})
