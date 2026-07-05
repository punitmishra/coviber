"""Vector-backend tests: exercise the JSON path via public API + the Qdrant
path via a fake qdrant_client, and gate a live-Qdrant integration test on a
reachable Qdrant URL (skipped by default; CI does not run it).

Run: python -m pytest tests/test_vector_stores.py
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import sys
import uuid
from types import SimpleNamespace

import pytest

import coviber.store as store_mod
from coviber.record import Record
from coviber.store import EMBED_MODEL, Store
from coviber.vector_stores import JSONVectorStore, resolve


# ---- shared FakeEmbedder identical to test_embedding_index ---------------


def _vec(text, dim=8):
    h = hashlib.sha256(text.encode("utf-8")).digest()[:dim]
    v = [b / 255.0 + 1e-6 for b in h]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


class FakeEmbedder:
    def encode(self, texts, normalize_embeddings=True):
        return [_vec(t) for t in texts]


@contextlib.contextmanager
def fake_embedder():
    old = store_mod._embedder
    store_mod._embedder = FakeEmbedder()
    try:
        yield
    finally:
        store_mod._embedder = old


def _recs(n, start=0):
    return [Record(source="test", from_name=f"P{i}", subject=f"subj {i}", text=f"body text {i}")
            for i in range(start, start + n)]


# ---- direct JSONVectorStore contract ------------------------------------


def test_json_vector_store_roundtrip(tmp_path):
    vs = JSONVectorStore(tmp_path, model_tag="m1")
    assert vs.known_ids() == set()

    v1 = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    v2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    vs.upsert([("a", v1), ("b", v2)])
    assert vs.known_ids() == {"a", "b"}
    hits = vs.search([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], live_ids={"a", "b"}, limit=2)
    assert [rid for _, rid in hits] == ["b", "a"]

    vs.delete(["a"])
    assert vs.known_ids() == {"b"}


def test_json_vector_store_model_mismatch_returns_empty(tmp_path):
    # Persist under one model tag, then read under another → invalidates.
    JSONVectorStore(tmp_path, "m1").upsert([("x", [1.0] + [0.0] * 7)])
    assert JSONVectorStore(tmp_path, "m2").known_ids() == set()


def test_json_vector_store_search_filters_to_live_ids(tmp_path):
    vs = JSONVectorStore(tmp_path, "m1")
    vs.upsert([
        ("a", [1.0] + [0.0] * 7),
        ("b", [0.0, 1.0] + [0.0] * 6),
        ("c", [0.0, 0.0, 1.0] + [0.0] * 5),
    ])
    # Query pointing at "a" — but "a" is not live; expect b/c ranked below their
    # true similarity with each other, and "a" completely absent.
    hits = vs.search([1.0] + [0.0] * 7, live_ids={"b", "c"}, limit=5)
    assert {rid for _, rid in hits} == {"b", "c"}


# ---- resolver -----------------------------------------------------------


def test_resolve_defaults_to_json(tmp_path, monkeypatch):
    monkeypatch.delenv("COVIBER_QDRANT_URL", raising=False)
    vs = resolve(tmp_path, model_tag=EMBED_MODEL)
    assert isinstance(vs, JSONVectorStore)


def test_resolve_reads_env_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("COVIBER_QDRANT_URL", "http://fake:6333")
    calls = {}
    class _Client:
        def __init__(self, url, api_key=None):
            calls["url"] = url
        def get_collections(self):
            return SimpleNamespace(collections=[])
        def create_collection(self, **kw):
            calls["created"] = kw["collection_name"]
    fake_qdrant = SimpleNamespace(QdrantClient=_Client)
    fake_qmodels = SimpleNamespace(
        VectorParams=lambda size, distance: {"size": size, "distance": distance},
        Distance=SimpleNamespace(COSINE="cosine"),
    )
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_qdrant)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", SimpleNamespace(models=fake_qmodels))
    vs = resolve(tmp_path, model_tag=EMBED_MODEL)
    assert type(vs).__name__ == "QdrantVectorStore"
    assert calls["url"] == "http://fake:6333"
    assert calls["created"] == "coviber_records"


def test_resolve_config_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COVIBER_QDRANT_URL", "http://env:6333")
    calls = {}
    class _Client:
        def __init__(self, url, api_key=None):
            calls["url"] = url
        def get_collections(self):
            return SimpleNamespace(collections=[])
        def create_collection(self, **kw):
            pass
    monkeypatch.setitem(sys.modules, "qdrant_client",
                        SimpleNamespace(QdrantClient=_Client))
    monkeypatch.setitem(sys.modules, "qdrant_client.http",
                        SimpleNamespace(models=SimpleNamespace(
                            VectorParams=lambda **kw: kw,
                            Distance=SimpleNamespace(COSINE="cosine"),
                        )))
    resolve(tmp_path, model_tag=EMBED_MODEL, qdrant={"url": "http://from-config:6333"})
    assert calls["url"] == "http://from-config:6333"


def test_resolve_qdrant_missing_extra_raises(tmp_path, monkeypatch):
    # Force ImportError for qdrant_client even if it's installed in the env.
    monkeypatch.setitem(sys.modules, "qdrant_client", None)
    with pytest.raises(ImportError) as exc:
        resolve(tmp_path, model_tag=EMBED_MODEL, qdrant={"url": "http://x:6333"})
    assert "coviber[qdrant]" in str(exc.value)


# ---- Qdrant backend end-to-end via a fake qdrant_client ------------------


class _FakeQdrantClient:
    """In-memory stand-in that speaks just enough of the Qdrant client API."""

    def __init__(self, url=None, api_key=None):
        self.url = url
        self.collections: dict[str, list] = {}

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.collections])

    def create_collection(self, collection_name, vectors_config):
        self.collections[collection_name] = []

    def delete_collection(self, collection_name):
        self.collections.pop(collection_name, None)

    def upsert(self, collection_name, points, wait=True):
        by_id = {p.id: p for p in self.collections[collection_name]}
        for p in points:
            by_id[p.id] = p
        self.collections[collection_name] = list(by_id.values())

    def delete(self, collection_name, points_selector, wait=True):
        drop = set(points_selector.points)
        self.collections[collection_name] = [
            p for p in self.collections[collection_name] if p.id not in drop
        ]

    def scroll(self, collection_name, limit=1024, offset=None, with_payload=True, with_vectors=False):
        pts = self.collections[collection_name]
        start = 0 if offset is None else int(offset)
        chunk = pts[start:start + limit]
        next_offset = start + limit if start + limit < len(pts) else None
        return chunk, next_offset

    def search(self, collection_name, query_vector, limit=10):
        # Dumbest possible cosine over the whole collection — the fake exists to
        # verify the coviber-side glue, not to model Qdrant's ANN behavior.
        def dot(a, b):
            return sum(x * y for x, y in zip(a, b))
        pts = self.collections[collection_name]
        scored = [(dot(p.vector, query_vector), p) for p in pts]
        scored.sort(key=lambda t: -t[0])
        return [SimpleNamespace(score=s, payload=p.payload) for s, p in scored[:limit]]


class _PointStruct:
    def __init__(self, id, vector, payload):
        self.id, self.vector, self.payload = id, vector, payload


class _PointIdsList:
    def __init__(self, points):
        self.points = points


@contextlib.contextmanager
def _stub_qdrant(monkeypatch):
    monkeypatch.setitem(sys.modules, "qdrant_client",
                        SimpleNamespace(QdrantClient=_FakeQdrantClient))
    monkeypatch.setitem(sys.modules, "qdrant_client.http",
                        SimpleNamespace(models=SimpleNamespace(
                            VectorParams=lambda **kw: kw,
                            Distance=SimpleNamespace(COSINE="cosine"),
                            PointStruct=_PointStruct,
                            PointIdsList=_PointIdsList,
                        )))
    yield


def test_qdrant_backend_end_to_end_via_store(tmp_path, monkeypatch):
    with _stub_qdrant(monkeypatch), fake_embedder():
        store = Store(tmp_path, qdrant={"url": "http://fake:6333"})
        recs = _recs(3)
        store.upsert(recs)
        hits = store.search("subj 1 body text 1", limit=2)
    assert hits and hits[0][1].subject == "subj 1"
    assert store.last_search_backend == f"embeddings ({EMBED_MODEL}) via QdrantVectorStore"


def test_qdrant_backend_prunes_stale_ids(tmp_path, monkeypatch):
    with _stub_qdrant(monkeypatch), fake_embedder():
        store = Store(tmp_path, qdrant={"url": "http://fake:6333"})
        recs = _recs(3)
        store.upsert(recs)
        store.search("prime the index")
        # Drop record 1 from the JSONL store directly.
        keep = [recs[0], recs[2]]
        store.records_path.write_text(
            "".join(json.dumps(r.to_dict()) + "\n" for r in keep), encoding="utf-8")
        # Second search should reconcile Qdrant with the JSONL store.
        store.search("q")
        known = store._vectors.known_ids()
    assert known == {r.id for r in keep}


def test_qdrant_backend_model_mismatch_wipes_collection(tmp_path, monkeypatch):
    with _stub_qdrant(monkeypatch), fake_embedder():
        s1 = Store(tmp_path, qdrant={"url": "http://fake:6333"})
        s1.upsert(_recs(2))
        s1.search("prime")
        # Simulate a persisted model tag from a different encoder.
        meta = tmp_path / "qdrant.meta.json"
        meta.write_text(json.dumps({"model": "some-other-model"}), encoding="utf-8")
        s2 = Store(tmp_path, qdrant={"url": "http://fake:6333"})
        # Constructor should have wiped the collection.
        assert s2._vectors.known_ids() == set()


def test_qdrant_record_id_to_point_id_is_stable():
    from coviber.vector_stores import QdrantVectorStore
    rid = "0123456789abcdef0123456789abcdef"
    assert QdrantVectorStore._to_point_id(rid) == str(uuid.UUID(rid))


# ---- live-Qdrant integration test (opt-in) ------------------------------

QDRANT_URL = os.environ.get("COVIBER_TEST_QDRANT_URL")


@pytest.mark.skipif(not QDRANT_URL, reason="Set COVIBER_TEST_QDRANT_URL to run live-Qdrant tests")
def test_live_qdrant_roundtrip(tmp_path):
    pytest.importorskip("qdrant_client")
    with fake_embedder():
        collection = f"coviber_test_{uuid.uuid4().hex[:8]}"
        store = Store(tmp_path, qdrant={"url": QDRANT_URL, "collection": collection, "dim": 8})
        try:
            recs = _recs(4)
            store.upsert(recs)
            hits = store.search("subj 1 body text 1", limit=2)
            assert hits and hits[0][1].subject == "subj 1"
            assert store._vectors.known_ids() == {r.id for r in recs}
        finally:
            store._vectors.wipe()
            # wipe recreates the collection; drop it cleanly on the way out
            store._vectors._client.delete_collection(collection_name=collection)
