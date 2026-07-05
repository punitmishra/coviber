"""Pluggable vector persistence + search — JSON on disk by default, Qdrant optional.

The store's semantic-search path stays identical: encode → upsert missing →
delete stale → search top-k by cosine. What changes is where vectors live.
- `JSONVectorStore`: one whole-file `embeddings.json` next to `records.jsonl`.
  Zero deps beyond stdlib. Fine up to ~10^5 records; past that the load-per-
  query cost dominates.
- `QdrantVectorStore`: vectors persist in a Qdrant collection (local Docker or
  a remote instance). Server-side ANN search means query cost stops growing
  with corpus size. Requires the `[qdrant]` extra: `pip install coviber[qdrant]`.

Selection happens once, in `resolve()`. Callers only see the `VectorStore`
protocol; the store doesn't know or care which backend it got.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Iterable, Protocol


class VectorStore(Protocol):
    """Backend-agnostic vector persistence + search.

    `model` is stored so we can invalidate the whole index on model change
    (a different encoder produces a different vector space; old vectors are
    meaningless). All ids in this interface are the string form of a
    `Record.id` (32-hex-char MD5). Vectors are lists of floats (already
    L2-normalized by the encoder; cosine == dot product).
    """

    def known_ids(self) -> set[str]: ...
    def upsert(self, id_vecs: list[tuple[str, list[float]]]) -> None: ...
    def delete(self, ids: Iterable[str]) -> None: ...
    def search(self, query_vec: list[float], live_ids: set[str], limit: int
               ) -> list[tuple[float, str]]: ...
    def model(self) -> str: ...
    def rebind(self, model: str) -> None:
        """Called after wipe() when the encoder model changes — persist the new tag."""

    def wipe(self) -> None:
        """Drop every persisted vector. Called on model mismatch."""


# ---------------------------------------------------------------------------
# JSON file backend — the historical / default implementation, unchanged in
# behavior. Extracted here so Store can swap it out for Qdrant.
# ---------------------------------------------------------------------------


class JSONVectorStore:
    """Vectors live in a single JSON file alongside records.jsonl.

    No in-process cache — each method call reads the file (or its absence)
    from disk. This matches the pre-v0.2 semantics exactly, including the
    invariant that an external process editing embeddings.json (or the model
    tag) is picked up on the next call. Batched ops keep IO cheap: `upsert`
    takes the whole batch and does a single read + single write per call.
    """

    def __init__(self, data_dir: Path, model_tag: str, filename: str = "embeddings.json"):
        self._path = Path(data_dir) / filename
        self._model = model_tag

    def _load(self) -> dict[str, list[float]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            print(f"coviber: rebuilding corrupt embedding cache {self._path}", file=sys.stderr)
            return {}
        if not isinstance(data, dict) or data.get("model") != self._model:
            # Different model → every cached vector is invalid. Same behavior as pre-v0.2.
            return {}
        vecs = data.get("vectors")
        if not isinstance(vecs, dict):
            return {}
        return {k: v for k, v in vecs.items() if isinstance(v, list)}

    def _persist(self, vectors: dict[str, list[float]]):
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"model": self._model, "vectors": vectors}), encoding="utf-8",
        )
        os.replace(tmp, self._path)

    # --- protocol ---
    def known_ids(self) -> set[str]:
        return set(self._load().keys())

    def upsert(self, id_vecs: list[tuple[str, list[float]]]) -> None:
        if not id_vecs:
            return
        vectors = self._load()
        for rid, vec in id_vecs:
            vectors[rid] = vec
        self._persist(vectors)

    def delete(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        vectors = self._load()
        changed = False
        for rid in ids:
            if rid in vectors:
                del vectors[rid]
                changed = True
        if changed:
            self._persist(vectors)

    def search(self, query_vec: list[float], live_ids: set[str], limit: int
               ) -> list[tuple[float, str]]:
        vectors = self._load()
        candidates = [(rid, vectors[rid]) for rid in live_ids if rid in vectors]
        if not candidates:
            return []
        try:
            import numpy as np
            m = np.asarray([v for _, v in candidates])
            scores = (m @ np.asarray(query_vec)).tolist()
        except ImportError:
            scores = [sum(a * b for a, b in zip(v, query_vec)) for _, v in candidates]
        scored = sorted(zip(scores, [rid for rid, _ in candidates]), key=lambda x: -x[0])
        return scored[:limit]

    def model(self) -> str:
        return self._model

    def rebind(self, model: str) -> None:
        # Persist the new tag with an empty vector map; next search will re-encode.
        self._model = model
        self._persist({})

    def wipe(self) -> None:
        if self._path.exists():
            self._path.unlink()


# ---------------------------------------------------------------------------
# Qdrant backend — server-side ANN search, no load-per-query. Requires the
# [qdrant] extra. The Qdrant instance can be local Docker (see docker-compose.
# yml in the repo root) or remote; the URL is the only thing that changes.
# ---------------------------------------------------------------------------


class QdrantVectorStore:
    """Vectors persist in a Qdrant collection; the model tag persists in a
    small sidecar file so we can invalidate the whole collection on model
    change (Qdrant collection metadata is more awkward to write than a JSON
    file, and the whole point of this backend is to keep large indexes off
    the local filesystem — the sidecar is a few bytes).

    Record ids are 32-hex-char MD5 → parsed as UUIDs (Qdrant native id form).
    Vectors are assumed L2-normalized upstream; distance=Cosine.
    """

    _DIM_DEFAULT = 384  # all-MiniLM-L6-v2

    def __init__(self, data_dir: Path, model_tag: str, *, url: str,
                 collection: str = "coviber_records", api_key: str | None = None,
                 dim: int = _DIM_DEFAULT, meta_filename: str = "qdrant.meta.json"):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels
        except ImportError as e:
            raise ImportError(
                "Qdrant backend requires the [qdrant] extra: pip install \"coviber[qdrant]\""
            ) from e
        self._qmodels = qmodels
        self._client = QdrantClient(url=url, api_key=api_key)
        self._collection = collection
        self._dim = dim
        self._model_tag = model_tag
        self._meta_path = Path(data_dir) / meta_filename
        self._ensure_collection()
        self._reconcile_model_tag()

    # --- internals ---
    def _ensure_collection(self):
        collections = {c.name for c in self._client.get_collections().collections}
        if self._collection in collections:
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=self._qmodels.VectorParams(
                size=self._dim, distance=self._qmodels.Distance.COSINE,
            ),
        )

    def _read_meta_tag(self) -> str | None:
        if not self._meta_path.exists():
            return None
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8")).get("model")
        except (json.JSONDecodeError, OSError):
            return None

    def _write_meta_tag(self, tag: str):
        tmp = self._meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"model": tag}), encoding="utf-8")
        os.replace(tmp, self._meta_path)

    def _reconcile_model_tag(self):
        persisted = self._read_meta_tag()
        if persisted is None:
            self._write_meta_tag(self._model_tag)
            return
        if persisted != self._model_tag:
            # Model change → same behavior as JSON backend: wipe.
            self.wipe()
            self._write_meta_tag(self._model_tag)

    @staticmethod
    def _to_point_id(record_id: str) -> str:
        """Record.id is a 32-hex-char MD5. Qdrant accepts unsigned int or UUID
        string; MD5 is 128 bits = one UUID exactly, so we lose no bits and get
        a stable, invertible mapping."""
        return str(uuid.UUID(record_id))

    # --- protocol ---
    def known_ids(self) -> set[str]:
        ids: set[str] = set()
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                limit=1024, offset=offset, with_payload=True, with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                if payload.get("record_id"):
                    ids.add(payload["record_id"])
            if offset is None:
                break
        return ids

    def upsert(self, id_vecs: list[tuple[str, list[float]]]) -> None:
        if not id_vecs:
            return
        points = [
            self._qmodels.PointStruct(
                id=self._to_point_id(rid),
                vector=vec,
                payload={"record_id": rid},
            )
            for rid, vec in id_vecs
        ]
        self._client.upsert(collection_name=self._collection, points=points, wait=True)

    def delete(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        self._client.delete(
            collection_name=self._collection,
            points_selector=self._qmodels.PointIdsList(
                points=[self._to_point_id(rid) for rid in ids],
            ),
            wait=True,
        )

    def search(self, query_vec: list[float], live_ids: set[str], limit: int
               ) -> list[tuple[float, str]]:
        # We over-fetch, then filter to live_ids on the client, so a record
        # that was deleted from records.jsonl but is still in Qdrant (mid-
        # reconciliation) can't leak into results. Cheap: `limit` is small.
        overshoot = max(limit * 2, 32)
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=query_vec,
            limit=overshoot,
        )
        out: list[tuple[float, str]] = []
        for h in hits:
            rid = (h.payload or {}).get("record_id")
            if rid in live_ids:
                out.append((float(h.score), rid))
                if len(out) >= limit:
                    break
        return out

    def model(self) -> str:
        return self._model_tag

    def rebind(self, model: str) -> None:
        self.wipe()
        self._model_tag = model
        self._write_meta_tag(model)

    def wipe(self) -> None:
        try:
            self._client.delete_collection(collection_name=self._collection)
        except Exception:
            pass
        self._ensure_collection()


# ---------------------------------------------------------------------------
# Resolver — one place that maps config/env to a backend instance.
# ---------------------------------------------------------------------------


def resolve(data_dir: Path, model_tag: str, *, qdrant: dict | None = None) -> VectorStore:
    """Pick a backend for this Store instance.

    Precedence:
      1. `qdrant={"url": ...}` in config → QdrantVectorStore
      2. `COVIBER_QDRANT_URL` env var → QdrantVectorStore
      3. otherwise → JSONVectorStore (the default, zero-dep behavior)

    A Qdrant URL failing on connect at construction time raises up to the
    caller; if you'd rather silently fall back to JSON on connection failure,
    do that at the call site, not here — silent fallback masks real config
    drift for a memory product.
    """
    cfg = dict(qdrant or {})
    url = cfg.get("url") or os.environ.get("COVIBER_QDRANT_URL")
    if not url:
        return JSONVectorStore(data_dir, model_tag=model_tag)
    return QdrantVectorStore(
        data_dir, model_tag=model_tag, url=url,
        collection=cfg.get("collection") or os.environ.get("COVIBER_QDRANT_COLLECTION", "coviber_records"),
        api_key=cfg.get("api_key") or os.environ.get("COVIBER_QDRANT_API_KEY"),
        dim=int(cfg.get("dim", 384)),
    )
