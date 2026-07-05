"""slackexport loader tests — a synthetic Acme Robotics workspace export."""
import json
import tempfile
from pathlib import Path

from coviber import Settings, available, get_loader, ingest

_USERS = [
    {"id": "U01GRACE", "profile": {"display_name": "Grace Hopper"}},
    {"id": "U02ADA", "profile": {"display_name": "", "real_name": "Ada Byron"}},  # display_name -> real_name fallback
    {"id": "U03CHEN", "profile": {"display_name": "Margaret Chen"}},
]

_FALCON_DAY1 = [
    {"user": "U01GRACE", "ts": "1719849600.000100", "thread_ts": "1719849600.000100",
     "text": "Falcon go/no-go tomorrow — <@U02ADA> can you post the risk checklist?"},
    {"user": "U03CHEN", "ts": "1719850000.000200", "thread_ts": "1719849600.000100",
     "text": "On it — checklist coming this afternoon."},
    {"user": "U01GRACE", "ts": "1719850100.000300", "subtype": "channel_join",
     "text": "<@U01GRACE> has joined the channel"},
]

_FALCON_DAY2 = [
    {"user": "U02ADA", "ts": "1719936000.000300",
     "text": "Orbit embedding router: fall back to CPU when the GPU pool saturates?"},
    {"user": "U9BOT", "ts": "1719936100.000400", "subtype": "bot_message", "text": "build green"},
    {"user": "U02ADA", "ts": "1719936200.000500", "text": "   "},
]

_ATLAS_DAY = [
    {"user": "U01GRACE", "ts": "1719936300.000600", "text": "Atlas schema decision is due Friday."},
]


def _make_export(root: Path, with_users: bool = True):
    if with_users:
        (root / "users.json").write_text(json.dumps(_USERS), encoding="utf-8")
    days = {"falcon": {"2024-07-01": _FALCON_DAY1, "2024-07-02": _FALCON_DAY2},
            "atlas": {"2024-07-02": _ATLAS_DAY}}
    for chan, files in days.items():
        d = root / chan; d.mkdir()
        for day, msgs in files.items():
            (d / f"{day}.json").write_text(json.dumps(msgs), encoding="utf-8")


def test_slackexport_registered():
    assert "slackexport" in available()


def test_slackexport_mapping_and_replied():
    with tempfile.TemporaryDirectory() as d:
        _make_export(Path(d))
        recs = list(get_loader("slackexport", {"path": d, "you": "Margaret Chen"}).load())
        assert len(recs) == 4  # channel_join, bot_message, blank text skipped
        assert all(r.source == "slack" and r.subject == "" and not r.unread for r in recs)

        atlas, parent, reply, ada = recs  # dirs sorted (#atlas first), then day files in date order
        assert atlas.channel == "#atlas" and atlas.from_name == "Grace Hopper"
        assert parent.from_name == "Grace Hopper" and parent.channel == "#falcon"
        assert parent.text == "Falcon go/no-go tomorrow — @Ada Byron can you post the risk checklist?"
        assert parent.ts == "2024-07-01T16:00:00.000100+00:00"
        assert parent.thread_id == "1719849600.000100" and parent.replied  # "you" answered in-thread
        assert reply.from_name == "Margaret Chen" and reply.replied
        assert ada.from_name == "Ada Byron" and ada.thread_id == "" and not ada.replied


def test_slackexport_channel_filter_and_you_as_user_id():
    with tempfile.TemporaryDirectory() as d:
        _make_export(Path(d))
        recs = list(get_loader("slackexport", {"path": d, "channels": ["#falcon"], "you": "U03CHEN"}).load())
        assert {r.channel for r in recs} == {"#falcon"} and len(recs) == 3
        assert [r.replied for r in recs if r.thread_id] == [True, True]


def test_slackexport_missing_users_json_keeps_raw_ids():
    with tempfile.TemporaryDirectory() as d:
        _make_export(Path(d), with_users=False)
        recs = list(get_loader("slackexport", {"path": d}).load())
        assert {r.from_name for r in recs} == {"U01GRACE", "U02ADA", "U03CHEN"}
        assert any("@U02ADA" in r.text and "<@" not in r.text for r in recs)


def test_slackexport_malformed_day_file_names_the_file():
    with tempfile.TemporaryDirectory() as d:
        _make_export(Path(d))
        (Path(d) / "falcon" / "2024-07-03.json").write_text("{not json", encoding="utf-8")
        try:
            list(get_loader("slackexport", {"path": d}).load())
            raise AssertionError("expected ValueError for malformed day file")
        except ValueError as e:
            assert "2024-07-03.json" in str(e)


def test_slackexport_end_to_end_ingest():
    with tempfile.TemporaryDirectory() as export, tempfile.TemporaryDirectory() as data:
        _make_export(Path(export))
        s = Settings(loader="slackexport", loader_config={"path": export, "you": "Margaret Chen"},
                     data_dir=data, you="Margaret Chen", known_projects=["Falcon", "Orbit", "Atlas"])
        stats = ingest(s)
        assert stats["loaded"] == 4 and stats["new"] == 4
        g = stats["graph"]
        assert set(g["projects_list"]) == {"Atlas", "Falcon", "Orbit"}
        assert g["channels"] == 2
        # Post-L4: person keys are lowercased in the graph (display form
        # available on the node).
        assert {"grace hopper", "ada byron"} <= set(g["top_people"])
        assert "margaret chen" not in g["top_people"]  # "you" is excluded from people


_ALL = [test_slackexport_registered, test_slackexport_mapping_and_replied,
        test_slackexport_channel_filter_and_you_as_user_id,
        test_slackexport_missing_users_json_keeps_raw_ids,
        test_slackexport_malformed_day_file_names_the_file, test_slackexport_end_to_end_ingest]

if __name__ == "__main__":
    for fn in _ALL:
        fn(); print(f"ok  {fn.__name__}")
    print("all tests passed")
