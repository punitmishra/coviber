"""Persistence + semantic search.

Zero-dependency by default: records are stored as deduped JSONL and search falls
back to keyword scoring. If `sentence-transformers` is installed (the [search]
extra), search upgrades to local embeddings + cosine — same model the whitepaper
uses (all-MiniLM-L6-v2, 384-dim). Vectors persist locally via a `VectorStore`
backend (see coviber.vector_stores): `JSONVectorStore` by default (one file next
to records.jsonl, zero deps); `QdrantVectorStore` when a URL is configured (the
`[qdrant]` extra, server-side ANN search — pick this past ~10^5 records).
Writers serialize on an advisory file lock (`.lock`); reads stay lock-free.
"""
from __future__ import annotations

import json
import math
import os
import sys
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Iterable

from .record import Record
from .vector_stores import VectorStore, resolve as resolve_vector_store

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


def _to_float32_list(v) -> list[float]:
    """Coerce an encoder row (numpy ndarray or list of numbers) to a list of
    float32-precision Python floats. Halves the JSON serialization width
    versus float64 with no meaningful precision loss for a float32 model.
    """
    try:
        import numpy as np
        if isinstance(v, np.ndarray):
            return v.astype("float32").tolist()
        return np.asarray(v, dtype="float32").tolist()
    except ImportError:
        # No numpy — do the round-trip via struct so we still shed precision.
        import struct
        return [struct.unpack("f", struct.pack("f", float(x)))[0] for x in v]


class Store:
    def __init__(self, data_dir: str | Path = "./coviber_data", *,
                 vectors: VectorStore | None = None, qdrant: dict | None = None):
        """Store backed by JSONL records + a pluggable vector index.

        `vectors`: pre-built VectorStore instance (mostly for tests). If None,
        `resolve_vector_store` decides based on the `qdrant` config dict and
        the `COVIBER_QDRANT_URL` env var — falling back to `JSONVectorStore`
        when neither is set, preserving pre-v0.2 behavior.

        `data_dir` is `expanduser()`'d here so `~/store` works regardless of
        which config source supplied it (CLI --data-dir, COVIBER_DATA_DIR
        env, YAML `data_dir:`, or a direct Settings construction). Before
        this, only the CLI's serve command expanded, leaving MCP env-driven
        and YAML-driven configs with literal `~` directories (audit2/#8).
        """
        self.dir = Path(data_dir).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.dir / "records.jsonl"
        # Legacy attribute — some external callers may still read it; keep it
        # pointing at the JSON backend's file even when Qdrant is active.
        self.embeddings_path = self.dir / "embeddings.json"
        self.last_search_backend = None  # set by search(): "embeddings (<model>) via <backend>" | "keyword"
        self._vectors = vectors if vectors is not None else resolve_vector_store(
            self.dir, model_tag=EMBED_MODEL, qdrant=qdrant,
        )

    # --- record persistence (dedup by id, keep last) ---
    def upsert(self, records: Iterable[Record]) -> int:
        # the lock must cover the read too, or two writers interleave read-merge-
        # rewrite and the last one silently drops the other's records
        with _write_lock(self.dir):
            parsed, corrupt = self._read_all()
            if corrupt:
                self._quarantine(corrupt)
            existing = {r.id: r for r in parsed}
            n_new = 0
            for r in records:
                if r.id not in existing:
                    n_new += 1
                existing[r.id] = r
            # write-then-rename so a crash mid-write can't destroy the store.
            # PID+uuid-tag the tmp filename to match the pattern in
            # JSONVectorStore._persist and save_graph — two writers that
            # somehow bypass the advisory lock (unsupported platform, future
            # bulk_import helper) can't clobber a shared .jsonl.tmp.
            tmp = self.records_path.with_suffix(f".jsonl.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
            try:
                with tmp.open("w", encoding="utf-8") as f:
                    for r in existing.values():
                        f.write(json.dumps(r.to_dict()) + "\n")
                os.replace(tmp, self.records_path)
            except Exception:
                # A raise between open and os.replace leaves an orphan tmp
                # under records_path.jsonl.tmp.{pid}.{uuid}. Best-effort
                # cleanup so the data_dir doesn't collect debris.
                if tmp.exists():
                    with suppress(OSError):
                        tmp.unlink()
                raise
        return n_new

    def all(self) -> list[Record]:
        parsed, _ = self._read_all()
        return parsed

    def _read_all(self) -> tuple[list[Record], list[str]]:
        """Parse records.jsonl into (records, raw-corrupt-lines). Side-effect-free."""
        if not self.records_path.exists():
            return [], []
        out: list[Record] = []
        bad: list[str] = []
        with self.records_path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    out.append(Record.from_dict(json.loads(stripped)))
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"coviber: skipping corrupt record {self.records_path}:{lineno}: {e}",
                          file=sys.stderr)
                    bad.append(line.rstrip("\n"))
        return out, bad

    def _quarantine(self, lines: list[str]):
        """Append unparseable lines verbatim to records.jsonl.bad before we drop
        them from records.jsonl on rewrite. For a memory product, losing data
        silently is the worst failure mode — better a growing quarantine file
        we can inspect than lines that vanish on the next upsert.
        """
        bad_path = self.records_path.with_suffix(".jsonl.bad")
        with bad_path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        print(f"coviber: quarantined {len(lines)} corrupt line(s) → {bad_path}",
              file=sys.stderr)

    # --- semantic / keyword search ---
    def search(self, query: str, limit: int = 8) -> list[tuple[float, Record]]:
        records = self.all()
        if not records:
            return []
        try:
            ranked = self._embedding_search(query, records, limit)
            self.last_search_backend = f"embeddings ({EMBED_MODEL}) via {type(self._vectors).__name__}"
        except ImportError:
            # Expected fallback: [search] extra isn't installed. Silent.
            ranked = self._keyword_search(query, records)
            self.last_search_backend = "keyword"
        except Exception as exc:
            # Unexpected failure: extras ARE installed but something broke —
            # CUDA OOM, HuggingFace hub 5xx on first model download, corrupt
            # vector cache, Qdrant unreachable, numpy/torch mismatch. Fall
            # back to keyword so the caller still gets results, but SURFACE
            # it (stderr + warning) so an operator can tell "extras missing"
            # (silent) apart from "extras installed but broken" (this path).
            import warnings
            print(f"coviber: embedding search failed "
                  f"({type(exc).__name__}: {exc}); falling back to keyword",
                  file=sys.stderr)
            warnings.warn(
                f"coviber: embedding search failed ({type(exc).__name__}: {exc}); "
                "falling back to keyword",
                RuntimeWarning, stacklevel=2,
            )
            ranked = self._keyword_search(query, records)
            self.last_search_backend = "keyword (embedding failed)"
        return ranked[:limit]

    def _embedding_search(self, query: str, records: list[Record], limit: int
                          ) -> list[tuple[float, Record]]:
        emb = _get_embedder()
        # Model-tag reconciliation happens at construction; here we only
        # handle the delta between the record store and the vector index.
        live_ids = {r.id for r in records}
        known = self._vectors.known_ids()
        stale = known - live_ids
        missing = [r for r in records if r.id not in known]
        if missing:
            rows = emb.encode(
                [f"{r.subject} {r.text}" for r in missing], normalize_embeddings=True,
            )
            # `rows` may be a numpy ndarray (float32 from sentence-transformers)
            # or a plain list (e.g. from tests' FakeEmbedder). Coerce to
            # float32 lists in either case — float64 upcasting adds no signal
            # vs the source model and roughly doubles JSON on-disk size.
            self._vectors.upsert(
                [(r.id, _to_float32_list(v)) for r, v in zip(missing, rows)],
            )
        if stale:
            self._vectors.delete(stale)
        q = [float(x) for x in emb.encode([query], normalize_embeddings=True)[0]]
        # Over-fetch so the store can enforce its own truncation to `limit`
        # after mapping ids back to Records.
        hits = self._vectors.search(q, live_ids, limit=max(limit * 2, 16))
        id_to_rec = {r.id: r for r in records}
        return [(score, id_to_rec[rid]) for score, rid in hits if rid in id_to_rec]

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
        # Write-then-rename so a SIGINT / Ctrl-C / crash mid-write can't leave a
        # torn workgraph.json — every reader of this file (MCP who_is /
        # project_status / graph_summary; CLI graph) must be able to trust it.
        # PID+uuid tag on the tmp path guards the theoretical case where a
        # future caller races two ingest cycles on the same data_dir.
        with _write_lock(self.dir):
            target = self.dir / "workgraph.json"
            tmp = target.with_suffix(f".json.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
            try:
                tmp.write_text(json.dumps(graph_dict, indent=2), encoding="utf-8")
                os.replace(tmp, target)
            except Exception:
                if tmp.exists():
                    with suppress(OSError):
                        tmp.unlink()
                raise

    def load_graph(self) -> dict | str:
        """Read the persisted workgraph.json defensively.

        Returns a dict when the file exists and parses. Returns a readable
        string sentinel on the two failure modes (audit2/#13): (a) no graph
        yet (run `coviber ingest`); (b) file exists but is torn / unreadable
        (older coviber version predating the atomic-write fix, hand-edit,
        external corruption). Callers that want to distinguish the two
        check `isinstance(result, dict)`. This defensive-read helper lives
        on Store so every reader — CLI, MCP tools, third-party embedders —
        shares the same failure semantics.
        """
        gp = self.dir / "workgraph.json"
        if not gp.exists():
            return "No graph yet — run `coviber ingest`."
        try:
            return json.loads(gp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return f"Work graph is unreadable ({type(e).__name__}: {e}). Re-run `coviber ingest`."
