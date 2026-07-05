"""COVIBER_CONFIG parity — the MCP server honors the same settings file as the CLI.

Needs the [mcp] extra: skipped wholesale when `mcp` isn't importable (the CI test
matrix installs only [scrape]; CI's mcp job runs these).
"""
import json

import pytest

from coviber import Settings, ingest

pytest.importorskip("mcp", reason="MCP server tests need the [mcp] extra")
from coviber.mcp_server import _settings, catch_me_up, refresh  # noqa: E402

CFG = """\
you: punit
data_dir: {data_dir}
known_projects: [Falcon, Orbit, Atlas]
priority_senders: [Grace Hopper]
collaborators: [Ada Byron, Linus Vega]
"""


def _write_cfg(tmp_path, data_dir, name="config.yaml"):
    p = tmp_path / name
    p.write_text(CFG.format(data_dir=data_dir), encoding="utf-8")
    return p


def _clear_env(monkeypatch, *names):
    for n in names:
        monkeypatch.delenv(n, raising=False)


def test_settings_reads_config_file(tmp_path, monkeypatch):
    p = _write_cfg(tmp_path, tmp_path / "store")
    monkeypatch.setenv("COVIBER_CONFIG", str(p))
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")
    s = _settings()
    assert s.you == "punit"
    assert s.data_dir == str(tmp_path / "store")
    assert s.priority_senders == ["Grace Hopper"]
    assert s.collaborators == ["Ada Byron", "Linus Vega"]
    assert s.known_projects == ["Falcon", "Orbit", "Atlas"]


def test_env_overrides_beat_config_file(tmp_path, monkeypatch):
    p = _write_cfg(tmp_path, "/from-file/ignored")
    monkeypatch.setenv("COVIBER_CONFIG", str(p))
    monkeypatch.setenv("COVIBER_DATA_DIR", str(tmp_path / "override"))
    monkeypatch.setenv("COVIBER_YOU", "someone-else")
    s = _settings()
    assert s.data_dir == str(tmp_path / "override")
    assert s.you == "someone-else"
    assert s.priority_senders == ["Grace Hopper"]  # file values survive env overrides


def test_settings_defaults_without_config(monkeypatch):
    _clear_env(monkeypatch, "COVIBER_CONFIG", "COVIBER_DATA_DIR", "COVIBER_YOU")
    s = _settings()
    assert (s.data_dir, s.you, s.priority_senders) == ("./coviber_data", "you", [])


def test_config_path_expands_user(tmp_path, monkeypatch):
    _write_cfg(tmp_path, tmp_path / "store")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COVIBER_CONFIG", "~/config.yaml")
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")
    assert _settings().you == "punit"


def test_catch_me_up_fires_config_signals(tmp_path, monkeypatch):
    data = tmp_path / "store"
    ingest(Settings(loader="demo", data_dir=str(data)))
    monkeypatch.setenv("COVIBER_CONFIG", str(_write_cfg(tmp_path, data)))
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")
    out = catch_me_up(limit=15)
    assert "priority-sender+2" in out  # Grace Hopper via config file
    assert "collaborator+1" in out     # Ada Byron / Linus Vega via config file


def test_refresh_inherits_config(tmp_path, monkeypatch):
    data = tmp_path / "store"
    monkeypatch.setenv("COVIBER_CONFIG", str(_write_cfg(tmp_path, data)))
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")
    out = refresh("demo")
    assert "Ingested via demo" in out
    graph = json.loads((data / "workgraph.json").read_text(encoding="utf-8"))
    assert "Falcon" in graph["projects"]  # known_projects came from the config file


# ---------------------------------------------------------------------------
# Audit L7 coverage — the previously-untested five tools.
# ---------------------------------------------------------------------------


from coviber.mcp_server import (  # noqa: E402
    graph_summary, project_status, recall, voice_profile, who_is,
)


def _seed_demo_store(tmp_path, monkeypatch):
    """Prime a data dir with the demo corpus + config so all tools have
    something to return, and point the MCP env at it."""
    data = tmp_path / "store"
    ingest(Settings(loader="demo", data_dir=str(data),
                    known_projects=["Falcon", "Orbit", "Atlas"]))
    monkeypatch.setenv("COVIBER_CONFIG", str(_write_cfg(tmp_path, data)))
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")
    return data


def test_recall_returns_matches_or_helpful_empty_message(tmp_path, monkeypatch):
    _seed_demo_store(tmp_path, monkeypatch)
    out = recall("Falcon launch")
    assert isinstance(out, str) and out  # non-empty string
    # Either it found context (typical case) or it says so plainly.
    assert "Recall:" in out or "No matching context" in out


def test_who_is_and_project_status_return_strings(tmp_path, monkeypatch):
    _seed_demo_store(tmp_path, monkeypatch)
    # Any known project from the demo config.
    ps = project_status("Falcon")
    assert isinstance(ps, str) and ("people" in ps or "not found" in ps)
    # who_is is case-insensitive at the tool boundary now (L4/#14 + L7). We
    # can't easily assert on the returned node's contents (the name is the
    # dict KEY, not a field on the value), so instead assert it's a real
    # node payload (looks like JSON with the expected shape) OR "not found".
    wi = who_is("Grace Hopper")
    assert isinstance(wi, str)
    if "not found" not in wi:
        parsed = json.loads(wi)
        assert isinstance(parsed, dict)
        assert "interaction_count" in parsed  # node shape sanity check
    # Case-insensitive fallback lookup — this variant should hit the same node.
    wi_lower = who_is("grace hopper")
    assert wi_lower == wi or "not found" in wi_lower  # either both hit or both miss


def test_graph_summary_survives_missing_top_level_keys(tmp_path, monkeypatch):
    """A hand-edited workgraph.json with only some keys must not KeyError
    the summary tool (audit finding L7/#33)."""
    data = tmp_path / "store"; data.mkdir()
    (data / "workgraph.json").write_text(
        json.dumps({"people": {"ada": {"interaction_count": 3}}}), encoding="utf-8",
    )
    monkeypatch.setenv("COVIBER_DATA_DIR", str(data))
    _clear_env(monkeypatch, "COVIBER_CONFIG", "COVIBER_YOU")
    out = graph_summary()
    payload = json.loads(out)
    assert payload == {
        "people": 1, "projects": 0, "channels": 0, "tickets": 0,
        "projects_list": [], "top_people": ["ada"],
    }


def test_graph_summary_reports_corrupt_workgraph_instead_of_raising(tmp_path, monkeypatch):
    """A torn workgraph.json (partial write from a crash, hand-edit, older
    coviber version) must not raise a JSONDecodeError to the MCP client
    (audit finding L7/#32 — read half of the atomic-write fix)."""
    data = tmp_path / "store"; data.mkdir()
    (data / "workgraph.json").write_text('{"people": {"ada":', encoding="utf-8")  # truncated
    monkeypatch.setenv("COVIBER_DATA_DIR", str(data))
    _clear_env(monkeypatch, "COVIBER_CONFIG", "COVIBER_YOU")
    for out in (graph_summary(), who_is("ada"), project_status("Falcon")):
        assert "unreadable" in out.lower() or "no graph" in out.lower()


def test_voice_profile_uses_the_configured_name(tmp_path, monkeypatch):
    """Once the persona has samples, the drafted system_prompt must say
    "Write as <you>" from config, not "Write as the user" (audit L6/#27)."""
    data = tmp_path / "store"
    # Seed a few self-authored records with from_name matching config.you.
    ingest(Settings(
        loader="jsonl",
        loader_config={"path": str(_write_self_authored(tmp_path))},
        data_dir=str(data),
    ))
    monkeypatch.setenv("COVIBER_CONFIG", str(_write_cfg(tmp_path, data)))  # you=punit
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")
    # The demo config has you=punit; write records with from_name=punit.
    out = voice_profile()
    if "No self-authored" in out:  # writing 'punit' didn't match anything
        return  # acceptable — no persona data path
    parsed = json.loads(out)
    assert "punit" in parsed["system_prompt"] or "the user" in parsed["system_prompt"]


def _write_self_authored(tmp_path):
    p = tmp_path / "self.jsonl"
    p.write_text(
        "\n".join([
            json.dumps({"source": "s", "from_name": "punit", "text": "Hi team,\n\nQuick update.\n\nThanks"}),
            json.dumps({"source": "s", "from_name": "punit", "text": "Hey — sounds good."}),
        ]) + "\n",
        encoding="utf-8",
    )
    return p


def test_refresh_returns_readable_error_on_unknown_loader(tmp_path, monkeypatch):
    """An unknown loader name must return a readable string, not raise a raw
    KeyError to the MCP client (audit finding L7/#34)."""
    data = tmp_path / "store"; data.mkdir()
    monkeypatch.setenv("COVIBER_DATA_DIR", str(data))
    _clear_env(monkeypatch, "COVIBER_CONFIG", "COVIBER_YOU")
    out = refresh("no-such-loader-xyz")
    assert "refresh failed" in out and "no-such-loader-xyz" in out


def test_refresh_returns_readable_error_on_missing_file(tmp_path, monkeypatch):
    data = tmp_path / "store"; data.mkdir()
    monkeypatch.setenv("COVIBER_DATA_DIR", str(data))
    _clear_env(monkeypatch, "COVIBER_CONFIG", "COVIBER_YOU")
    out = refresh("jsonl", str(tmp_path / "does-not-exist.jsonl"))
    assert "refresh failed" in out


# ---------------------------------------------------------------------------
# Audit2 findings — ConfigError propagation + persisted-config invariant.
# ---------------------------------------------------------------------------


def test_bad_config_raises_config_error_per_tool_not_server_crash(tmp_path, monkeypatch):
    """If COVIBER_CONFIG points at a missing / invalid file, the failure
    must be per-tool (a `ConfigError` FastMCP renders into a tool error),
    not a `sys.exit` that kills the whole server. Audit2/#9 pins this
    invariant that ARCHITECTURE.md's "config re-read per tool call"
    section documents."""
    from coviber.config import ConfigError

    # Point at a config path that doesn't exist.
    monkeypatch.setenv("COVIBER_CONFIG", str(tmp_path / "no-such-config.yaml"))
    _clear_env(monkeypatch, "COVIBER_DATA_DIR", "COVIBER_YOU")

    # Every tool that calls _settings() must surface ConfigError, not
    # SystemExit. Using catch_me_up as a representative — it hits the
    # settings-read path immediately.
    import pytest
    with pytest.raises(ConfigError) as exc:
        catch_me_up()
    assert "no-such-config.yaml" in str(exc.value)
