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
