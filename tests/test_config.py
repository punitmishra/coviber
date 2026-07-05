"""Shared settings-file parsing + serve CLI plumbing — no [mcp] extra needed."""
import json
import sys

import pytest

from coviber.cli import build_parser
from coviber.config import ConfigError, read_config


def test_read_config_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"you": "punit"}), encoding="utf-8")
    assert read_config(str(p)) == {"you": "punit"}


def test_serve_parser_accepts_config():
    args = build_parser().parse_args(["serve", "--config", "x.yaml"])
    assert args.config == "x.yaml"
    assert args.func.__name__ == "cmd_serve"


def test_read_config_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError) as exc:
        read_config(str(tmp_path / "does-not-exist.json"))
    assert "does-not-exist.json" in str(exc.value)


def test_read_config_bad_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        read_config(str(p))
    assert "invalid JSON" in str(exc.value) and str(p) in str(exc.value)


def test_read_config_yaml_without_pyyaml_raises(tmp_path, monkeypatch):
    # Simulate pyyaml missing even if it happens to be installed in the test env.
    monkeypatch.setitem(sys.modules, "yaml", None)
    p = tmp_path / "cfg.yaml"
    p.write_text("you: punit\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        read_config(str(p))
    msg = str(exc.value)
    assert "pyyaml" in msg and str(p) in msg


def test_cli_main_exits_cleanly_on_config_error(tmp_path, capsys):
    # CLI users should see a friendly exit, not a traceback.
    from coviber.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["ingest", "--config", str(tmp_path / "missing.json")])
    assert "missing.json" in str(exc.value)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        test_read_config_json(Path(d))
    test_serve_parser_accepts_config()
    print("ok")
