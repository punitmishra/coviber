#!/usr/bin/env python3
"""Reproducible benchmark on the synthetic corpus — no unverifiable numbers.

Everything here runs on generated data and your own machine, so anyone can
reproduce every published number:  python bench/run.py [--scale N]

Measures the five hot paths named in the whitepaper: ingest+dedup, graph
build, urgency triage, semantic search cold + warm.

New in v0.6:
  --scales N,M,K,...       Sweep across sizes in one run (default: single --scale).
  --output PATH.json       Write machine-readable JSON alongside the human table.
  --search-mode auto|off   Force keyword-only search (`off`) or auto-select
                           whichever backend is available (`auto`, default).

The JSON output shape is the source of truth for the whitepaper's evaluation
tables and for issue #48 ("bench numbers at real scale, not aspirational").
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from coviber.loaders.demo import _DATA
from coviber.record import Record
from coviber.store import Store
from coviber.urgency import Config, triage
from coviber.workgraph import WorkGraph


def _synth(n: int) -> list[Record]:
    """Deterministically blow up the 15-record demo corpus to n records."""
    out = []
    for i in range(n):
        base = dict(_DATA[i % len(_DATA)])
        base["subject"] = f"{base.get('subject','')} #{i}"
        base["text"] = f"{base.get('text','')} (item {i})"
        out.append(Record(**base))
    return out


def _time(fn, repeat: int = 5) -> float:
    """Median wall-clock over `repeat` runs, in milliseconds."""
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def _hw_fingerprint() -> dict:
    """Minimal hardware/environment fingerprint for reproducibility."""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
    }


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _bench_one_scale(n: int, *, search_mode: str) -> dict:
    """Run every stage at scale `n` and return a dict of measurements."""
    recs = _synth(n)
    cfg = Config(
        you="you",
        priority_senders={"Grace Hopper"},
        collaborators={"Ada Byron"},
    )

    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        t_ingest = _time(lambda: store.upsert(recs), repeat=3)

        def build_graph():
            g = WorkGraph(known_projects=["Falcon", "Orbit", "Atlas"], you="you")
            g.ingest(recs)
        t_graph = _time(build_graph, repeat=3)

        loaded = store.all()
        t_triage = _time(lambda: triage(loaded, cfg), repeat=5)

        # Cold vs warm search: the first call encodes every record; every
        # subsequent call hits the persisted vector index and only encodes
        # the query. Reporting both makes the "warm queries skip record
        # encoding entirely" claim in the README testable.
        if search_mode == "off":
            # Force keyword path — used for the "zero-dep default" story.
            import coviber.store as store_mod

            def _unavail():
                raise ImportError("[search] extra disabled by bench")
            store_mod._get_embedder = _unavail
            store_mod._embedder = None

        t_search_cold = _time(lambda: store.search("orbit embedding router gpu"), repeat=1)
        t_search_warm = _time(lambda: store.search("orbit embedding router gpu"), repeat=3)
        backend = store.last_search_backend

    return {
        "scale": n,
        "ingest_ms": round(t_ingest, 2),
        "ingest_throughput_rec_per_s": round(n / (t_ingest / 1000)),
        "graph_ms": round(t_graph, 2),
        "graph_throughput_rec_per_s": round(n / (t_graph / 1000)),
        "triage_ms": round(t_triage, 2),
        "triage_throughput_rec_per_s": round(n / (t_triage / 1000)),
        "search_cold_ms": round(t_search_cold, 2),
        "search_warm_ms": round(t_search_warm, 2),
        "search_backend": backend,
    }


def _print_human(rows: list[dict]):
    """Print the classic README-style table but with cold vs warm search."""
    print(f"\nCoViber benchmark — {len(rows)} scale(s) (median of repeats)\n")
    header = (
        f"{'scale':>8}  "
        f"{'ingest':>10}  {'graph':>10}  {'triage':>10}  "
        f"{'search cold':>13}  {'search warm':>13}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['scale']:>8}  "
            f"{r['ingest_ms']:>7.1f} ms  "
            f"{r['graph_ms']:>7.1f} ms  "
            f"{r['triage_ms']:>7.1f} ms  "
            f"{r['search_cold_ms']:>10.1f} ms  "
            f"{r['search_warm_ms']:>10.1f} ms"
        )
    if rows:
        print(f"\nsearch backend: {rows[-1]['search_backend']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scale", type=int, help="synthetic record count (single-scale run)")
    ap.add_argument(
        "--scales", type=str,
        help="comma-separated scale sweep, e.g. 1000,10000,100000 (overrides --scale)",
    )
    ap.add_argument("--output", type=str, help="write JSON results to this path")
    ap.add_argument(
        "--search-mode", choices=("auto", "off"), default="auto",
        help="'off' forces keyword fallback (skip embeddings entirely)",
    )
    args = ap.parse_args()

    if args.scales:
        scales = [int(s.strip()) for s in args.scales.split(",") if s.strip()]
    elif args.scale:
        scales = [args.scale]
    else:
        scales = [2000]  # historical default

    rows = [_bench_one_scale(n, search_mode=args.search_mode) for n in scales]
    _print_human(rows)

    if args.output:
        payload = {
            "git_sha": _git_sha(),
            "hardware": _hw_fingerprint(),
            "search_mode": args.search_mode,
            "results": rows,
            # Machine-readable schema version so the whitepaper's eval tables
            # and any tooling reading these JSON files can pin against a
            # stable shape.
            "schema_version": "1.0",
        }
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.output}")

    print("reproduce:", " ".join(["python bench/run.py"] + sys.argv[1:]))


if __name__ == "__main__":
    main()
