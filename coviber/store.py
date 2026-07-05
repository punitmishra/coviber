"""Persistence + semantic search.

Zero-dependency by default: records are stored as deduped JSONL and search falls
back to keyword scoring. If `sentence-transformers` is installed (the [search]
extra), search upgrades to local embeddings + cosine — same model the whitepaper
uses (all-MiniLM-L6-v2, 384-dim). Everything stays on disk, no cloud egress.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable, Optional

from .record import Record

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


class Store:
    def __init__(self, data_dir: str | Path = "./coviber_data"):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.dir / "records.jsonl"

    # --- record persistence (dedup by id, keep last) ---
    def upsert(self, records: Iterable[Record]) -> int:
        existing = {r.id: r for r in self.all()}
        n_new = 0
        for r in records:
            if r.id not in existing:
                n_new += 1
            existing[r.id] = r
        with self.records_path.open("w") as f:
            for r in existing.values():
                f.write(json.dumps(r.to_dict()) + "\n")
        return n_new

    def all(self) -> list[Record]:
        if not self.records_path.exists():
            return []
        out = []
        with self.records_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(Record.from_dict(json.loads(line)))
        return out

    # --- semantic / keyword search ---
    def search(self, query: str, limit: int = 8) -> list[tuple[float, Record]]:
        records = self.all()
        if not records:
            return []
        try:
            emb = _get_embedder()
            import numpy as np
            texts = [f"{r.subject} {r.text}" for r in records]
            mat = emb.encode(texts, normalize_embeddings=True)
            q = emb.encode([query], normalize_embeddings=True)[0]
            scores = mat @ q
            ranked = sorted(zip(scores.tolist(), records), key=lambda x: -x[0])
        except Exception:
            ranked = self._keyword_search(query, records)
        return ranked[:limit]

    def _keyword_search(self, query: str, records) -> list[tuple[float, Record]]:
        terms = [t for t in query.lower().split() if t]
        scored = []
        for r in records:
            blob = f"{r.subject} {r.text} {r.from_name}".lower()
            hits = sum(blob.count(t) for t in terms)
            denom = math.log(2 + len(blob.split()))
            scored.append((hits / denom, r))
        return sorted(scored, key=lambda x: -x[0])

    def save_graph(self, graph_dict: dict):
        (self.dir / "workgraph.json").write_text(json.dumps(graph_dict, indent=2))
