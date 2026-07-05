"""CoViber MCP server — expose the local memory engine to any MCP client.

Gives Claude Desktop / Claude Code / any MCP client continuous personal context
over the Model Context Protocol: semantic recall, the urgency queue, the work
graph, and voice modelling — all served from your local disk. No cloud egress,
no telemetry.

Run:
    coviber serve                                 # stdio (Claude Desktop / Code)
    coviber serve --data-dir ~/covibe             # point at your store
    coviber serve --config ~/.coviber/config.yaml # same settings file as the CLI

Requires the [mcp] extra:  pip install "coviber[mcp]"
"""
# NOTE: do NOT add `from __future__ import annotations` here — FastMCP introspects
# real annotation classes, and stringized annotations break tool registration.
import os

from mcp.server.fastmcp import FastMCP

from .config import read_config
from .persona import learn
from .pipeline import Settings, build_queue, ingest
from .store import Store

mcp = FastMCP("coviber")


def _settings() -> Settings:
    """Config parity with the CLI: COVIBER_CONFIG (same YAML/JSON file `coviber triage
    --config` takes) seeds Settings; COVIBER_DATA_DIR / COVIBER_YOU override when set.
    Re-read per call so every tool sees current config without a server restart."""
    path = os.environ.get("COVIBER_CONFIG")
    s = Settings.from_dict(read_config(path)) if path else Settings()
    if os.environ.get("COVIBER_DATA_DIR"):
        s.data_dir = os.environ["COVIBER_DATA_DIR"]
    if os.environ.get("COVIBER_YOU"):
        s.you = os.environ["COVIBER_YOU"]
    return s


@mcp.tool()
def recall(query: str, limit: int = 6) -> str:
    """Semantic search over your local context — 'what do I know about X?'.
    Returns the most relevant records (sender, source, subject) from local memory."""
    hits = Store(_settings().data_dir).search(query, limit=limit)
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


def _load_graph(data_dir: str):
    """Read workgraph.json defensively.

    Returns a dict, or a string on error / not-yet-built states. The store's
    save_graph writes atomically (L1/#7), but a torn file could still land
    if the operator hand-edits it, or if a partial write from an older
    coviber version predates the fix — so guard the read at the boundary.
    """
    import json
    from pathlib import Path
    gp = Path(data_dir) / "workgraph.json"
    if not gp.exists():
        return "No graph yet — run `coviber ingest`."
    try:
        return json.loads(gp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return f"Work graph is unreadable ({type(e).__name__}: {e}). Re-run `coviber ingest`."


@mcp.tool()
def who_is(name: str) -> str:
    """What the work graph knows about a person: platforms, projects, channels, activity."""
    import json
    g = _load_graph(_settings().data_dir)
    if isinstance(g, str):
        return g
    # WorkGraph stores person keys lowercased (L4/#14); the pretty form lives
    # in the `display_name` node field. Look up case-insensitively so callers
    # can pass "Ada Byron" or "ada byron" or "ADA BYRON" and get the same node.
    people = g.get("people", {})
    node = people.get(name) or people.get((name or "").lower())
    return json.dumps(node, indent=2) if node else f"'{name}' not found in the work graph."


@mcp.tool()
def project_status(name: str) -> str:
    """What the work graph knows about a project: people, channels, related tickets."""
    import json
    g = _load_graph(_settings().data_dir)
    if isinstance(g, str):
        return g
    node = g.get("projects", {}).get(name)
    return json.dumps(node, indent=2) if node else f"Project '{name}' not found."


@mcp.tool()
def graph_summary() -> str:
    """High-level shape of your context: counts + top people + projects."""
    import json
    g = _load_graph(_settings().data_dir)
    if isinstance(g, str):
        return g
    # Use .get() everywhere so an old, hand-edited, or partially-populated
    # workgraph.json can't KeyError the summary — the fields are ~stable
    # but not part of a documented contract (audit finding L7/#33).
    people = g.get("people", {})
    projects = g.get("projects", {})
    channels = g.get("channels", {})
    tickets = g.get("tickets", {})
    return json.dumps({
        "people": len(people),
        "projects": len(projects),
        "channels": len(channels),
        "tickets": len(tickets),
        "projects_list": sorted(projects),
        "top_people": sorted(
            people, key=lambda p: -people[p].get("interaction_count", 0),
        )[:8],
    }, indent=2)


@mcp.tool()
def voice_profile() -> str:
    """Your inference-free writing-voice profile + a ready system prompt for drafting
    in your style, learned locally from records you authored (from_name == 'you')."""
    s = _settings()
    you = s.you.lower()
    # body only — a leading subject line would defeat the persona engine's opener detection
    mine = [r.text for r in Store(s.data_dir).all()
            if (r.from_name or "").lower() == you and r.text]
    if not mine:
        return ("No self-authored messages found in local memory. Set from_name to your "
                "identity when ingesting so the persona engine can learn your voice.")
    vp = learn(mine)
    import json
    # Pass `s.you` so the drafted prompt says "Write as <you>" instead of
    # "Write as the user" — the whole point of an inference-free persona
    # (audit finding L6/#27).
    return json.dumps({"profile": vp.to_dict(), "system_prompt": vp.system_prompt(s.you)}, indent=2)


@mcp.tool()
def refresh(loader: str, path: str = "") -> str:
    """Ingest fresh context via a named loader — loader='jsonl' with a path, or any
    registered loader. Pass loader='demo' explicitly to load the synthetic demo corpus
    (it mixes fictional records into your real store; use a scratch data dir).

    Loader errors (unknown loader, missing file, permission denied) are caught
    and returned as a readable string so the MCP client sees an actionable
    message rather than a raw Python traceback."""
    s = _settings()  # inherit known_projects, skip rules, etc. from the shared config
    s.loader, s.loader_config = loader, ({"path": path} if path else {})
    try:
        stats = ingest(s)
    except (KeyError, ValueError, FileNotFoundError, IsADirectoryError,
            PermissionError, OSError) as e:
        # KeyError => unknown loader name; the rest are file / config issues.
        # ImportError still propagates: it means the caller asked for an
        # optional-extra loader (webscrape/qdrant) without installing the
        # extra, which is a setup problem the operator should see plainly.
        return f"refresh failed ({type(e).__name__}: {e})"
    g = stats["graph"]
    return (f"Ingested via {loader}: {stats['new']} new / {stats['total']} total. "
            f"Graph: {g['people']} people, {g['projects']} projects, {g['tickets']} tickets.")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
