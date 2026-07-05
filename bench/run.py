#!/usr/bin/env python3
"""Reproducible benchmark on the synthetic corpus — no unverifiable numbers.

Everything here runs on generated data and your own machine, so anyone can
reproduce the table:  python bench/run.py [--scale N]

Measures the four hot paths from the whitepaper: ingest+dedup, graph build,
urgency triage, and semantic search.
"""
import argparse
import statistics
import tempfile
import time

from coviber.loaders.demo import _DATA
from coviber.record import Record
from coviber.store import Store
from coviber.urgency import Config, triage
from coviber.workgraph import WorkGraph


def _synth(n):
    """Deterministically blow up the 15-record demo corpus to n records."""
    out = []
    for i in range(n):
        base = dict(_DATA[i % len(_DATA)])
        base["subject"] = f"{base.get('subject','')} #{i}"
        base["text"] = f"{base.get('text','')} (item {i})"
        out.append(Record(**base))
    return out


def _time(fn, repeat=5):
    ts = []
    for _ in range(repeat):
        t = time.perf_counter(); fn(); ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=2000, help="synthetic record count")
    args = ap.parse_args()
    n = args.scale
    recs = _synth(n)
    cfg = Config(you="you", priority_senders={"Grace Hopper"}, collaborators={"Ada Byron"})

    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        t_ingest = _time(lambda: store.upsert(recs), repeat=3)

        def build_graph():
            g = WorkGraph(known_projects=["Falcon", "Orbit", "Atlas"], you="you")
            g.ingest(recs)
        t_graph = _time(build_graph, repeat=3)

        loaded = store.all()
        t_triage = _time(lambda: triage(loaded, cfg), repeat=5)

        # store.search never raises (it falls back to keyword scoring internally),
        # so probe the embedder directly to report the backend honestly
        try:
            from coviber.store import _get_embedder
            _get_embedder()
            search_mode = "embeddings (all-MiniLM-L6-v2)"
        except Exception:
            search_mode = "keyword fallback — install the [search] extra for embeddings"
        t_search = _time(lambda: store.search("orbit embedding router gpu"), repeat=3)

    print(f"\nCoViber benchmark — {n} synthetic records (median of repeats)\n")
    print(f"{'stage':<28}{'latency':>12}{'throughput':>18}")
    print("-" * 58)
    print(f"{'ingest + dedup (JSONL)':<28}{t_ingest:>9.1f} ms{n/(t_ingest/1000):>13,.0f} rec/s")
    print(f"{'work-graph build':<28}{t_graph:>9.1f} ms{n/(t_graph/1000):>13,.0f} rec/s")
    print(f"{'urgency triage (full scan)':<28}{t_triage:>9.1f} ms{n/(t_triage/1000):>13,.0f} rec/s")
    print(f"{'semantic search (top-8)':<28}{t_search:>9.1f} ms{'':>18}")
    print(f"\nsearch backend: {search_mode}")
    print("reproduce: python bench/run.py --scale", n)


if __name__ == "__main__":
    main()
