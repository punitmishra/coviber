# CoViber — Whitepaper

**Continuous Context Replication for AI-Augmented Knowledge Work**

The full design & evaluation paper describes the four contributions this
codebase implements: (1) a loader-agnostic ingestion architecture, (2) the
cross-source WorkGraph, (3) statistical persona modelling, and (4) multi-signal
urgency triage — plus an MCP-native interface to expose the context to an LLM.

> **De-identified public version pending.** The original evaluation was run on a
> private production deployment; those figures and the persona excerpt are being
> re-derived on the synthetic `demo` dataset before the paper is published here.
> The architecture sections map 1:1 to the modules in `coviber/`
> (`loaders/`, `workgraph.py`, `urgency.py`, `store.py`, `pipeline.py`).

See the [README](./README.md) for the architecture overview and quickstart.
