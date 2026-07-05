"""coviber CLI — ingest, triage, query, and inspect the work graph."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .loaders import available
from .pipeline import Settings, build_queue, ingest
from .store import Store


def _load_settings(args) -> Settings:
    cfg = {}
    if args.config:
        cfg = _read_config(args.config)
    if getattr(args, "loader", None):
        cfg["loader"] = args.loader
    if getattr(args, "path", None):
        cfg.setdefault("config", {})["path"] = args.path
    if getattr(args, "data_dir", None):
        cfg["data_dir"] = args.data_dir
    return Settings.from_dict(cfg)


def _read_config(path: str) -> dict:
    p = Path(path)
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            sys.exit("YAML config needs pyyaml: pip install pyyaml")
        return yaml.safe_load(text) or {}
    return json.loads(text)


def cmd_ingest(args):
    stats = ingest(_load_settings(args))
    g = stats["graph"]
    print(f"loader={stats['loader']}  loaded={stats['loaded']}  new={stats['new']}  total={stats['total']}")
    print(f"graph: {g['people']} people · {g['projects']} projects · "
          f"{g['channels']} channels · {g['tickets']} tickets")
    if g["projects_list"]:
        print("projects:", ", ".join(g["projects_list"]))


def cmd_triage(args):
    queue = build_queue(_load_settings(args))
    if not queue:
        print("nothing urgent — inbox clear (or run `coviber ingest` first).")
        return
    print(f"# Triage — {len(queue)} actionable item(s)\n")
    for i, t in enumerate(queue, 1):
        r = t["record"]
        bar = "🔴" * min(t["urgency"], 10)
        print(f"{i}. [{t['urgency']:>2}] {bar}  {r.from_name}  ·  {r.source}/{r.channel}")
        print(f"     {r.subject or r.text[:70]}")
        print(f"     signals: {', '.join(t['signals'])}\n")


def cmd_query(args):
    store = Store(_load_settings(args).data_dir)
    hits = store.search(args.text, limit=args.k)
    if not hits:
        print("no results (run `coviber ingest` first).")
        return
    for scoreval, r in hits:
        print(f"[{scoreval:.3f}] {r.from_name} · {r.source}/{r.channel}")
        print(f"        {r.subject or r.text[:80]}")


def cmd_graph(args):
    store = Store(_load_settings(args).data_dir)
    gp = store.dir / "workgraph.json"
    if not gp.exists():
        print("no graph yet — run `coviber ingest`."); return
    g = json.loads(gp.read_text(encoding="utf-8"))
    if args.person:
        print(json.dumps(g["people"].get(args.person, {"error": "not found"}), indent=2)); return
    print(json.dumps({"people": len(g["people"]), "projects": len(g["projects"]),
                      "channels": len(g["channels"]), "tickets": len(g["tickets"]),
                      "people_list": sorted(g["people"]), "projects_list": sorted(g["projects"])}, indent=2))


def cmd_demo(args):
    """Zero-config end-to-end: ingest synthetic data + show the graph & triage."""
    s = Settings(loader="demo", data_dir=args.data_dir or "./coviber_data",
                 you="you", known_projects=["Falcon", "Orbit", "Atlas"],
                 priority_senders=["Grace Hopper"],
                 collaborators=["Ada Byron", "Linus Vega", "Margaret Chen"])
    stats = ingest(s)
    g = stats["graph"]
    print(f"loader=demo  loaded={stats['loaded']}  new={stats['new']}  total={stats['total']}")
    print(f"graph: {g['people']} people · {g['projects']} projects · "
          f"{g['channels']} channels · {g['tickets']} tickets")
    print("projects:", ", ".join(g["projects_list"]), "\n")
    queue = build_queue(s)
    print(f"# Triage — {len(queue)} actionable item(s)\n")
    for i, t in enumerate(queue, 1):
        r = t["record"]
        bar = "🔴" * min(t["urgency"], 10)
        print(f"{i}. [{t['urgency']:>2}] {bar}  {r.from_name}  ·  {r.source}/{r.channel}")
        print(f"     {r.subject or r.text[:70]}")
        print(f"     signals: {', '.join(t['signals'])}\n")


def cmd_loaders(args):
    print("available loaders:", ", ".join(available()))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coviber", description="Continuous context replica for AI-augmented work.")
    p.add_argument("--data-dir", default=None, help="where to store records + graph (default ./coviber_data)")
    # accepted before *or* after the subcommand: `coviber serve --data-dir ~/.coviber`
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)

    ig = sub.add_parser("ingest", parents=[common], help="load records via a loader → store + graph")
    ig.add_argument("--loader", help="loader name (see `coviber loaders`)")
    ig.add_argument("--path", help="file path for the jsonl loader")
    ig.add_argument("--config", help="YAML/JSON settings file")
    ig.set_defaults(func=cmd_ingest)

    tr = sub.add_parser("triage", parents=[common], help="show the prioritized obligation queue")
    tr.add_argument("--config"); tr.set_defaults(func=cmd_triage)

    q = sub.add_parser("query", parents=[common], help="semantic/keyword search over context")
    q.add_argument("text"); q.add_argument("-k", type=int, default=8); q.add_argument("--config")
    q.set_defaults(func=cmd_query)

    gr = sub.add_parser("graph", parents=[common], help="inspect the work graph")
    gr.add_argument("--person"); gr.add_argument("--config"); gr.set_defaults(func=cmd_graph)

    dm = sub.add_parser("demo", parents=[common], help="run end-to-end on synthetic data (no setup)")
    dm.set_defaults(func=cmd_demo)

    sub.add_parser("loaders", help="list available loaders").set_defaults(func=cmd_loaders)

    sv = sub.add_parser("serve", parents=[common],
                        help="start the local MCP server (stdio) for Claude / any MCP client")
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


def cmd_serve(args):
    import os
    if args.data_dir:
        os.environ["COVIBER_DATA_DIR"] = os.path.expanduser(args.data_dir)
    try:
        from .mcp_server import main as serve_main
    except ImportError:
        sys.exit('MCP server needs the [mcp] extra:  pip install "coviber[mcp]"')
    serve_main()


if __name__ == "__main__":
    main()
