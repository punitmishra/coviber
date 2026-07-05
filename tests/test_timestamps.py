"""Timestamp normalization tests — run with: python -m pytest (or python tests/test_timestamps.py)."""
from coviber import Record
from coviber.record import _normalize_ts
from coviber.urgency import Config, score
from coviber.workgraph import WorkGraph


def test_rfc2822_to_iso_utc():
    assert _normalize_ts("Tue, 01 Jul 2025 10:00:00 -0700") == "2025-07-01T17:00:00+00:00"
    r = Record(source="email", from_name="Ada", ts="Tue, 01 Jul 2025 10:00:00 -0700")
    assert r.ts == "2025-07-01T17:00:00+00:00"


def test_z_suffix_and_naive_assumed_utc():
    assert _normalize_ts("2025-07-01T10:00:00Z") == "2025-07-01T10:00:00+00:00"  # 3.9 fromisoformat can't parse 'Z'
    assert _normalize_ts("2025-07-01T10:00:00") == "2025-07-01T10:00:00+00:00"


def test_offsets_converge_to_utc():
    assert _normalize_ts("2025-07-01T12:00:00+05:00") == "2025-07-01T07:00:00+00:00"


def test_epoch_string():
    assert _normalize_ts("1600000000") == "2020-09-13T12:26:40+00:00"
    assert _normalize_ts("1600000000.5") == "2020-09-13T12:26:40.500000+00:00"


def test_garbage_passes_through():
    for bad in ("not a date", "yesterday", "5", ""):  # "5" fails the epoch sanity range
        assert _normalize_ts(bad) == bad
    assert Record(source="s", text="x", ts="not a date").ts == "not a date"


def test_ts_not_part_of_id():
    assert Record(source="s", text="x").id == Record(source="s", text="x", ts="Tue, 01 Jul 2025 10:00:00 -0700").id


def test_last_seen_chronological_across_formats():
    older = Record(source="email", from_name="Ada", ts="Mon, 01 Jan 2024 09:00:00 +0000")
    newer = Record(source="slack", from_name="Ada", ts="2025-06-01T00:00:00+00:00")
    for batch in ([older, newer], [newer, older]):  # raw lexicographic max() would pick "Mon, ..."
        g = WorkGraph()
        g.ingest(batch)
        assert g.people["Ada"]["last_seen"] == "2025-06-01T00:00:00+00:00"


def test_unparseable_ts_never_clobbers_last_seen():
    g = WorkGraph()
    g.ingest([Record(source="slack", from_name="Ada", ts="2025-06-01T00:00:00+00:00"),
              Record(source="slack", from_name="Ada", ts="zzz not a date")])
    assert g.people["Ada"]["last_seen"] == "2025-06-01T00:00:00+00:00"


def test_rfc2822_record_gets_age_signal():
    r = Record(source="email", from_name="Ada", text="please review",
               ts="Mon, 01 Jan 2024 09:00:00 +0000")
    _, sig = score(r, Config(you="you"))
    assert "age>7d+3" in sig  # pre-normalization this ts fell into the except -> age 0


_ALL = [test_rfc2822_to_iso_utc, test_z_suffix_and_naive_assumed_utc, test_offsets_converge_to_utc,
        test_epoch_string, test_garbage_passes_through, test_ts_not_part_of_id,
        test_last_seen_chronological_across_formats, test_unparseable_ts_never_clobbers_last_seen,
        test_rfc2822_record_gets_age_signal]

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
