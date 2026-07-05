"""Persisted embedding index tests — no torch/numpy needed; the embedder is faked.

Run with: python -m pytest (or python tests/test_embedding_index.py)
"""
import contextlib
import hashlib
import json
import math
import os
import tempfile

import coviber.store as store_mod
from coviber.record import Record
from coviber.store import EMBED_MODEL, Store


def _vec(text, dim=8):
    h = hashlib.sha256(text.encode("utf-8")).digest()[:dim]
    v = [b / 255.0 + 1e-6 for b in h]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


class FakeEmbedder:
    """Deterministic hash-based embedder; records every text it encodes."""
    def __init__(self):
        self.encoded = []

    def encode(self, texts, normalize_embeddings=True):
        self.encoded.extend(texts)
        return [_vec(t) for t in texts]


@contextlib.contextmanager
def fake_embedder(fake):
    old = store_mod._embedder
    store_mod._embedder = fake
    try:
        yield fake
    finally:
        store_mod._embedder = old


@contextlib.contextmanager
def no_embedder():
    """Simulate zero extras deterministically, even if [search] is installed."""
    def _unavailable():
        raise ImportError("sentence-transformers not installed")
    old_fn, old_emb = store_mod._get_embedder, store_mod._embedder
    store_mod._get_embedder, store_mod._embedder = _unavailable, None
    try:
        yield
    finally:
        store_mod._get_embedder, store_mod._embedder = old_fn, old_emb


def _recs(n, start=0):
    return [Record(source="test", from_name=f"P{i}", subject=f"subj {i}", text=f"body text {i}")
            for i in range(start, start + n)]


def test_first_search_populates_cache_and_ranks_by_cosine():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        recs = _recs(3); store.upsert(recs)
        with fake_embedder(FakeEmbedder()):
            hits = store.search("subj 1 body text 1", limit=2)  # exact record text → cosine 1.0
        assert store.last_search_backend == f"embeddings ({EMBED_MODEL}) via JSONVectorStore"
        assert len(hits) == 2
        top_score, top_rec = hits[0]
        assert isinstance(top_score, float) and isinstance(top_rec, Record)
        # Vectors are persisted at float32 precision (halves JSON size vs the
        # float64 upcast); cosine on normalized float32 vectors stays within
        # ~2e-8 of 1.0, so 1e-6 is a safe tolerance without losing signal.
        assert top_rec.subject == "subj 1" and abs(top_score - 1.0) < 1e-6
        data = json.loads(store.embeddings_path.read_text(encoding="utf-8"))
        assert data["model"] == EMBED_MODEL
        assert set(data["vectors"]) == {r.id for r in recs}


def test_warm_search_encodes_only_the_delta():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        store.upsert(_recs(3))
        with fake_embedder(FakeEmbedder()) as fe:
            store.search("q1")
            assert len(fe.encoded) == 4  # 3 records + query
            mtime = os.stat(store.embeddings_path).st_mtime_ns
            store.search("q2")
            assert len(fe.encoded) == 5  # warm: query only, no re-encode
            assert os.stat(store.embeddings_path).st_mtime_ns == mtime  # unchanged cache not rewritten
            store.upsert(_recs(1, start=10))
            store.search("q3")
            assert len(fe.encoded) == 7  # 1 new record + query


def test_deleted_record_pruned_from_cache():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        recs = _recs(3); store.upsert(recs)
        with fake_embedder(FakeEmbedder()):
            store.search("q")
            keep = recs[1:]
            store.records_path.write_text(
                "".join(json.dumps(r.to_dict()) + "\n" for r in keep), encoding="utf-8")
            store.search("q")
        data = json.loads(store.embeddings_path.read_text(encoding="utf-8"))
        assert set(data["vectors"]) == {r.id for r in keep}


def test_model_change_invalidates_cache():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        store.upsert(_recs(2))
        with fake_embedder(FakeEmbedder()) as fe:
            store.search("q")
            data = json.loads(store.embeddings_path.read_text(encoding="utf-8"))
            data["model"] = "some-other-model"
            store.embeddings_path.write_text(json.dumps(data), encoding="utf-8")
            before = len(fe.encoded)
            store.search("q")
            assert len(fe.encoded) == before + 3  # both records re-encoded + query
        assert json.loads(store.embeddings_path.read_text(encoding="utf-8"))["model"] == EMBED_MODEL


def test_keyword_fallback_with_zero_extras():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        store.upsert(_recs(2))
        with no_embedder():
            hits = store.search("body text")
        assert hits and store.last_search_backend == "keyword"
        assert not store.embeddings_path.exists()  # fallback never touches the vector cache


def test_corrupt_cache_is_rebuilt_not_fatal():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        store.upsert(_recs(2))
        with fake_embedder(FakeEmbedder()):
            store.search("q")
            for garbage in ("{definitely not json", json.dumps([1, 2, 3]),
                            json.dumps({"model": EMBED_MODEL, "vectors": {"x": "not-a-list"}})):
                store.embeddings_path.write_text(garbage, encoding="utf-8")
                hits = store.search("q")
                assert hits and store.last_search_backend.startswith("embeddings")
        data = json.loads(store.embeddings_path.read_text(encoding="utf-8"))
        assert set(data["vectors"]) == {r.id for r in store.all()}


_ALL = [test_first_search_populates_cache_and_ranks_by_cosine, test_warm_search_encodes_only_the_delta,
        test_deleted_record_pruned_from_cache, test_model_change_invalidates_cache,
        test_keyword_fallback_with_zero_extras, test_corrupt_cache_is_rebuilt_not_fatal]

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
