"""Concurrent-writer safety for Store — run with: python -m pytest tests/test_store_locking.py."""
import multiprocessing
import os
from pathlib import Path

import pytest

from coviber.record import Record
from coviber.store import Store, _write_lock

ROOT = Path(__file__).resolve().parent.parent  # this checkout, not any installed coviber

N_PROCS, PER_PROC = 4, 20


def test_lock_acquires_and_releases(tmp_path):
    fcntl = pytest.importorskip("fcntl")  # POSIX-only probe; the fallback paths are untestable here
    lock_file = tmp_path / ".lock"
    with _write_lock(tmp_path):
        assert lock_file.exists()
        with lock_file.open("ab") as fh:  # flock conflicts across open-file-descriptions, same process too
            with pytest.raises(OSError):
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with lock_file.open("ab") as fh:  # released on exit: non-blocking acquire now succeeds
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_lock_released_on_exception(tmp_path):
    fcntl = pytest.importorskip("fcntl")
    with pytest.raises(RuntimeError):
        with _write_lock(tmp_path):
            raise RuntimeError("boom")
    with (tmp_path / ".lock").open("ab") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # must not raise


def _hammer(data_dir, offset, barrier):
    import coviber
    assert coviber.__file__.startswith(str(ROOT)), coviber.__file__  # child must test THIS checkout
    store = Store(data_dir)
    barrier.wait()  # line everyone up so the read-merge-rewrite cycles actually interleave
    for i in range(PER_PROC):
        store.upsert([Record(source="race", subject=f"r{offset}-{i}", text=f"body {offset}-{i}")])


def test_concurrent_upserts_lose_nothing(tmp_path, monkeypatch):
    # Without _write_lock this reliably fails two ways: last-writer-wins drops
    # records (~20 of 80 survived when observed), and writers crash on the shared
    # records.jsonl.tmp (os.replace after another process already renamed it).
    monkeypatch.setenv("PYTHONPATH", str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    ctx = multiprocessing.get_context("spawn")  # portable; also matches macOS/Windows default
    barrier = ctx.Barrier(N_PROCS)
    procs = [ctx.Process(target=_hammer, args=(str(tmp_path), k, barrier)) for k in range(N_PROCS)]
    for p in procs: p.start()
    for p in procs: p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]
    assert len(Store(tmp_path).all()) == N_PROCS * PER_PROC


def test_upsert_n_new_under_lock(tmp_path):
    store = Store(tmp_path)
    recs = [Record(source="t", text=f"m{i}") for i in range(3)]
    assert store.upsert(recs) == 3
    assert store.upsert(recs + [Record(source="t", text="m3")]) == 1  # re-upsert dedupes, one novel
    assert len(store.all()) == 4


def test_upsert_quarantines_corrupt_lines(tmp_path):
    """Corrupt lines must not vanish silently on rewrite — they belong in a
    sidecar file so the operator can inspect and recover them."""
    store = Store(tmp_path)
    # seed a valid record
    store.upsert([Record(source="t", text="hello")])
    # inject a corrupt line at the end of records.jsonl
    with store.records_path.open("a", encoding="utf-8") as f:
        f.write("{not json but not empty either\n")
    # upsert triggers rewrite → corrupt line quarantined, then dropped from records.jsonl
    store.upsert([Record(source="t", text="world")])
    bad_path = store.records_path.with_suffix(".jsonl.bad")
    assert bad_path.exists()
    assert "{not json but not empty either" in bad_path.read_text(encoding="utf-8")
    # parsed records survive
    assert {r.text for r in store.all()} == {"hello", "world"}
    # idempotent: rewriting again does not duplicate the quarantined line
    store.upsert([Record(source="t", text="third")])
    assert bad_path.read_text(encoding="utf-8").count("{not json") == 1


def test_store_survives_non_string_ts_fields(tmp_path):
    """A hand-edited records.jsonl or a JSONL loader that emits a numeric epoch
    or a boolean must not crash the store — before the fix _normalize_ts called
    .strip() on the raw value and raised AttributeError uncaught, bricking
    every subsequent read (audit finding L1/#1)."""
    import json
    store = Store(tmp_path)
    # Seed via upsert so records.jsonl exists.
    store.upsert([Record(source="t", text="seed")])
    # Now append records with non-string ts values that would have crashed
    # _normalize_ts pre-fix. Both should survive the next read.
    with store.records_path.open("a", encoding="utf-8") as f:
        for row in ({"source": "t", "text": "int-ts", "ts": 1700000000, "id": "a" * 32},
                    {"source": "t", "text": "bool-ts", "ts": True, "id": "b" * 32}):
            f.write(json.dumps(row) + "\n")
    texts = {r.text for r in store.all()}
    assert {"seed", "int-ts", "bool-ts"} <= texts  # no crash, all parsed


def test_save_graph_write_is_atomic(tmp_path):
    """workgraph.json must be written via write-then-rename so a mid-write
    crash / Ctrl-C can't leave the MCP graph tools staring at a torn file
    (audit finding L1/#7)."""
    store = Store(tmp_path)
    # Sanity: no tmp files linger under normal operation.
    store.save_graph({"people": {"Alice": {}}, "projects": {}, "channels": {}, "tickets": {}})
    strays = [p for p in tmp_path.iterdir() if ".tmp" in p.suffixes or ".tmp" in p.name]
    assert not strays, f"leftover tmp files: {strays}"
    # The final file is well-formed JSON.
    import json
    payload = json.loads((tmp_path / "workgraph.json").read_text(encoding="utf-8"))
    assert payload["people"] == {"Alice": {}}


def _concurrent_search(data_dir, barrier):
    """Race two searches against a shared JSONVectorStore. Pre-fix they
    stomped on a shared `embeddings.json.tmp`; post-fix each writer uses a
    unique PID+uuid tmp path so os.replace can't fail mid-race."""
    import coviber
    from coviber.record import Record  # noqa: F401
    from coviber.store import Store
    # Contextual import so the child sees THIS checkout.
    assert coviber.__file__.startswith(str(ROOT)), coviber.__file__
    store = Store(data_dir)
    barrier.wait()
    # Loop a few times so misses/persists overlap.
    for _ in range(3):
        store.search("gibberish query")


def test_concurrent_search_does_not_race_on_tmp(tmp_path):
    """The two search callers must complete without OSError from a shared
    tmp path collision (audit finding L1/#6 + test-gap L1/#10). We can't
    guarantee the embedding backend is installed in CI, so we prime with
    an already-populated embeddings.json and let the JSONVectorStore code
    exercise its persist/load paths under real concurrent read+write."""
    import multiprocessing
    store = Store(tmp_path)
    store.upsert([Record(source="t", text=f"m{i}") for i in range(5)])
    # Prime the vector cache so search() has vectors to load; we build a
    # minimal one directly to avoid pulling sentence-transformers into CI.
    import json as _json
    vecs = {r.id: [0.1] * 8 for r in store.all()}
    (tmp_path / "embeddings.json").write_text(
        _json.dumps({"model": "all-MiniLM-L6-v2", "vectors": vecs}), encoding="utf-8",
    )
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(3)
    procs = [ctx.Process(target=_concurrent_search, args=(str(tmp_path), barrier))
             for _ in range(3)]
    for p in procs: p.start()
    for p in procs: p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]
    # No lingering tmp files with the pid+uuid pattern.
    strays = [p for p in tmp_path.iterdir()
              if p.name.startswith("embeddings.json.tmp.") or p.name.startswith("workgraph.json.tmp.")]
    assert not strays, f"leftover tmp files: {strays}"
