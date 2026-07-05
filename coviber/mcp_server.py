"""CoViber MCP server — expose the local memory engine to any MCP client.

Gives Claude Desktop / Claude Code / any MCP client continuous personal context
over the Model Context Protocol: semantic recall, the urgency queue, the work
graph, and voice modelling — all served from your local disk. No cloud egress,
no telemetry.

Run:
    coviber serve                       # stdio (Claude Desktop / Code)
    coviber serve --data-dir ~/covibe   # point at your store

Requires the [mcp] extra:  pip install "coviber[mcp]"
"""
# NOTE: do NOT add `from __future__ import annotations` here — FastMCP introspects
# real annotation classes, and stringized annotations break tool registration.
import os

from mcp.server.fastmcp import FastMCP

from .persona import learn
from .pipeline import Settings, build_queue, ingest
from .store import Store

DATA_DIR = os.environ.get("COVIBER_DATA_DIR", "./coviber_data")
mcp = FastMCP("coviber")


def _settings() -> Settings:
    return Settings(data_dir=DATA_DIR, you=os.environ.get("COVIBER_YOU", "you"))


@mcp.tool()
def recall(query: str, limit: int = 6) -> str:
    """Semantic search over your local context — 'what do I know about X?'.
    Returns the most relevant records (sender, source, subject) from local memory."""
    hits = Store(DATA_DIR).search(query, limit=limit)
    if not hits:
        return "No matching context. Run `coviber ingest` to load data first."
    lines = [f"# Recall: {query}"]
    for s, r in hits:
        lines.append(f"- [{s:.3f}] {r.from_name} · {r.source}/{r.channel} — {r.subject or r.text[:80]}")
    return "\n".join(lines)


@mcp.tool()
def catch_me_up(limit: int = 10) -> str:
    """The prioritized obligation queue — 'what needs my attention right now?'.
    Multi-signal urgency scored over your whole local stream, highest first."""
    queue = build_queue(_settings())[:limit]
    if not queue:
        return "Inbox clear — nothing urgent (or run `coviber ingest` first)."
    lines = [f"# What needs you ({len(queue)})"]
    for i, t in enumerate(queue, 1):
        r = t["record"]
        lines.append(f"{i}. [urgency {t['urgency']}] {r.from_name} · {r.source}/{r.channel}\n"
                     f"   {r.subject or r.text[:90]}  ({', '.join(t['signals'])})")
    return "\n".join(lines)


@mcp.tool()
def who_is(name: str) -> str:
    """What the work graph knows about a person: platforms, projects, channels, activity."""
    import json
    from pathlib import Path
    gp = Path(DATA_DIR) / "workgraph.json"
    if not gp.exists():
        return "No graph yet — run `coviber ingest`."
    node = json.loads(gp.read_text()).get("people", {}).get(name)
    return json.dumps(node, indent=2) if node else f"'{name}' not found in the work graph."


@mcp.tool()
def project_status(name: str) -> str:
    """What the work graph knows about a project: people, channels, related tickets."""
    import json
    from pathlib import Path
    gp = Path(DATA_DIR) / "workgraph.json"
    if not gp.exists():
        return "No graph yet — run `coviber ingest`."
    node = json.loads(gp.read_text()).get("projects", {}).get(name)
    return json.dumps(node, indent=2) if node else f"Project '{name}' not found."


@mcp.tool()
def graph_summary() -> str:
    """High-level shape of your context: counts + top people + projects."""
    import json
    from pathlib import Path
    gp = Path(DATA_DIR) / "workgraph.json"
    if not gp.exists():
        return "No graph yet — run `coviber ingest`."
    g = json.loads(gp.read_text())
    return json.dumps({
        "people": len(g["people"]), "projects": len(g["projects"]),
        "channels": len(g["channels"]), "tickets": len(g["tickets"]),
        "projects_list": sorted(g["projects"]),
        "top_people": sorted(g["people"], key=lambda p: -g["people"][p].get("interaction_count", 0))[:8],
    }, indent=2)


@mcp.tool()
def voice_profile() -> str:
    """Your inference-free writing-voice profile + a ready system prompt for drafting
    in your style, learned locally from records you authored (from_name == 'you')."""
    you = os.environ.get("COVIBER_YOU", "you").lower()
    # body only — a leading subject line would defeat the persona engine's opener detection
    mine = [r.text for r in Store(DATA_DIR).all()
            if (r.from_name or "").lower() == you and r.text]
    if not mine:
        return ("No self-authored messages found in local memory. Set from_name to your "
                "identity when ingesting so the persona engine can learn your voice.")
    vp = learn(mine)
    import json
    return json.dumps({"profile": vp.to_dict(), "system_prompt": vp.system_prompt()}, indent=2)


@mcp.tool()
def refresh(loader: str, path: str = "") -> str:
    """Ingest fresh context via a named loader — loader='jsonl' with a path, or any
    registered loader. Pass loader='demo' explicitly to load the synthetic demo corpus
    (it mixes fictional records into your real store; use a scratch data dir)."""
    cfg = {"path": path} if path else {}
    stats = ingest(Settings(loader=loader, loader_config=cfg, data_dir=DATA_DIR,
                            you=os.environ.get("COVIBER_YOU", "you")))
    g = stats["graph"]
    return (f"Ingested via {loader}: {stats['new']} new / {stats['total']} total. "
            f"Graph: {g['people']} people, {g['projects']} projects, {g['tickets']} tickets.")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
