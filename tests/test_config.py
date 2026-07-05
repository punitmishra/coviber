"""Shared settings-file parsing + serve CLI plumbing — no [mcp] extra needed."""
import json

from coviber.cli import build_parser
from coviber.config import read_config


def test_read_config_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"you": "punit"}), encoding="utf-8")
    assert read_config(str(p)) == {"you": "punit"}


def test_serve_parser_accepts_config():
    args = build_parser().parse_args(["serve", "--config", "x.yaml"])
    assert args.config == "x.yaml"
    assert args.func.__name__ == "cmd_serve"


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        test_read_config_json(Path(d))
    test_serve_parser_accepts_config()
    print("ok")
