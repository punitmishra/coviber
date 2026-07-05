"""Persistence + semantic search.

Zero-dependency by default: records are stored as deduped JSONL and search falls
back to keyword scoring. If `sentence-transformers` is installed (the [search]
extra), search upgrades to local embeddings + cosine — same model the whitepaper
uses (all-MiniLM-L6-v2, 384-dim). Vectors persist in embeddings.json (atomic
write, like records.jsonl) so only new records are encoded per query; a model
change invalidates the cache. Everything stays on disk, no cloud egress.
Writers serialize on an advisory file lock (`.lock`); reads stay lock-free.
"""
from __future__ import annotations

import json
import math
import os
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Iterable

from .record import Record

EMBED_MODEL = "all-MiniLM-L6-v2"

try:
    import fcntl  # POSIX
except ImportError:
    fcntl = None
try:
    import msvcrt  # Windows
except ImportError:
    msvcrt = None

_embedder = None


@contextmanager
def _write_lock(data_dir: Path):
    """Advisory inter-process lock on `<data_dir>/.lock`, held across a writer's
    whole read-merge-write cycle so concurrent writers (e.g. `coviber ingest` and
    the MCP server on the same data dir) queue up instead of clobbering each
    other. Blocking acquire. Readers never take it — the write-then-rename in
    upsert() already guarantees they can't see a torn file. No-op on platforms
    with neither fcntl nor msvcrt: single-process behaviour is unchanged, only
    the multi-writer guarantee is lost.
    """
    fh = (data_dir / ".lock").open("ab")
    try:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)  # released on close
        elif msvcrt is not None:
            fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)  # retries ~10s, then raises
        yield
    finally:
        if fcntl is None and msvcrt is not None:
            with suppress(OSError):
                fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        fh.close()


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


class Store:
    def __init__(self, data_dir: str | Path = "./coviber_data"):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.dir / "records.jsonl"
        self.embeddings_path = self.dir / "embeddings.json"
        self.last_search_backend = None  # set by search(): "embeddings (<model>)" | "keyword"

    # --- record persistence (dedup by id, keep last) ---
    def upsert(self, records: Iterable[Record]) -> int:
        # the lock must cover the read too, or two writers interleave read-merge-
        # rewrite and the last one silently drops the other's records
        with _write_lock(self.dir):
            existing = {r.id: r for r in self.all()}
            n_new = 0
            for r in records:
                if r.id not in existing:
                    n_new += 1
                existing[r.id] = r
            # write-then-rename so a crash mid-write can't destroy the store
            tmp = self.records_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for r in existing.values():
                    f.write(json.dumps(r.to_dict()) + "\n")
            os.replace(tmp, self.records_path)
        return n_new

    def all(self) -> list[Record]:
        if not self.records_path.exists():
            return []
        out = []
        with self.records_path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(Record.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"coviber: skipping corrupt record {self.records_path}:{lineno}: {e}",
                          file=sys.stderr)
        return out

    # --- semantic / keyword search ---
    def search(self, query: str, limit: int = 8) -> list[tuple[float, Record]]:
        records = self.all()
        if not records:
            return []
        try:
            ranked = self._embedding_search(query, records)
            self.last_search_backend = f"embeddings ({EMBED_MODEL})"
        except Exception:
            ranked = self._keyword_search(query, records)
            self.last_search_backend = "keyword"
        return ranked[:limit]

    def _embedding_search(self, query: str, records: list[Record]) -> list[tuple[float, Record]]:
        emb = _get_embedder()
        vectors = self._load_vectors()
        live = {r.id for r in records}
        stale = [i for i in vectors if i not in live]
        missing = [r for r in records if r.id not in vectors]
        if missing:  # encode only the delta — the warm path never re-encodes
            rows = emb.encode([f"{r.subject} {r.text}" for r in missing], normalize_embeddings=True)
            for r, v in zip(missing, rows):
                vectors[r.id] = [float(x) for x in v]
        for i in stale:
            del vectors[i]
        if missing or stale:
            self._save_vectors(vectors)
        q = [float(x) for x in emb.encode([query], normalize_embeddings=True)[0]]
        try:
            import numpy as np
            scores = (np.asarray([vectors[r.id] for r in records]) @ np.asarray(q)).tolist()
        except ImportError:
            scores = [sum(a * b for a, b in zip(vectors[r.id], q)) for r in records]
        return sorted(zip(scores, records), key=lambda x: -x[0])

    def _load_vectors(self) -> dict:
        if not self.embeddings_path.exists():
            return {}
        try:
            data = json.loads(self.embeddings_path.read_text(encoding="utf-8"))
            if data.get("model") != EMBED_MODEL:
                return {}  # different model → every cached vector is invalid
            vecs = data.get("vectors")
            return {k: v for k, v in vecs.items() if isinstance(v, list)} if isinstance(vecs, dict) else {}
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, AttributeError):
            print(f"coviber: rebuilding corrupt embedding cache {self.embeddings_path}", file=sys.stderr)
            return {}

    def _save_vectors(self, vectors: dict):
        tmp = self.embeddings_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"model": EMBED_MODEL, "vectors": vectors}), encoding="utf-8")
        os.replace(tmp, self.embeddings_path)

    def _keyword_search(self, query: str, records) -> list[tuple[float, Record]]:
        terms = [t for t in query.lower().split() if t]
        scored = []
        for r in records:
            blob = f"{r.subject} {r.text} {r.from_name}".lower()
            hits = sum(blob.count(t) for t in terms)
            if not hits:
                continue  # zero-score records are noise, not results
            denom = math.log(2 + len(blob.split()))
            scored.append((hits / denom, r))
        return sorted(scored, key=lambda x: -x[0])

    def save_graph(self, graph_dict: dict):
        with _write_lock(self.dir):
            (self.dir / "workgraph.json").write_text(json.dumps(graph_dict, indent=2),
                                                     encoding="utf-8")
