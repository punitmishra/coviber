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
