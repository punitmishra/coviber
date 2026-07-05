"""The pipeline: load (via any Loader) → dedup/store → WorkGraph → triage.

This is the loader-agnostic core. Swap the loader; everything downstream is
unchanged. Mirrors the whitepaper's ingest flow, with source-specific parsing
pushed out to pluggable loaders instead of a hardcoded per-platform dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .loaders import get_loader
from .store import Store
from .urgency import Config as UrgencyConfig, triage
from .workgraph import WorkGraph


@dataclass
class Settings:
    loader: str = "demo"
    loader_config: dict = field(default_factory=dict)
    data_dir: str = "./coviber_data"
    you: str = "you"
    known_projects: list = field(default_factory=list)
    priority_senders: list = field(default_factory=list)
    collaborators: list = field(default_factory=list)
    action_words: list = None       # None -> urgency defaults
    skip_senders: list = None
    skip_subjects: list = None
    weights: dict = None            # None -> urgency.DEFAULT_WEIGHTS
    qdrant: dict = None             # None -> JSON vector backend; {"url": ...} → Qdrant

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        d = dict(d or {})
        return cls(
            loader=d.get("loader", "demo"),
            loader_config=d.get("config", {}),
            data_dir=d.get("data_dir", "./coviber_data"),
            you=d.get("you", "you"),
            known_projects=d.get("known_projects", []),
            priority_senders=d.get("priority_senders", []),
            collaborators=d.get("collaborators", []),
            action_words=d.get("action_words"),
            skip_senders=d.get("skip_senders"),
            skip_subjects=d.get("skip_subjects"),
            weights=d.get("weights"),
            qdrant=d.get("qdrant"),
        )


def ingest(settings: Settings) -> dict:
    """Run one load→store→graph cycle. Returns a small stats dict."""
    loader = get_loader(settings.loader, settings.loader_config)
    records = list(loader.load())

    store = Store(settings.data_dir, qdrant=settings.qdrant)
    n_new = store.upsert(records)

    graph = WorkGraph(known_projects=settings.known_projects, you=settings.you)
    graph.ingest(store.all())
    store.save_graph(graph.to_dict())

    return {"loader": settings.loader, "loaded": len(records), "new": n_new,
            "total": len(store.all()), "graph": graph.summary()}


def build_queue(settings: Settings) -> list[dict]:
    store = Store(settings.data_dir, qdrant=settings.qdrant)
    cfg = UrgencyConfig(you=settings.you, priority_senders=set(settings.priority_senders),
                        collaborators=set(settings.collaborators),
                        action_words=set(settings.action_words) if settings.action_words else None,
                        skip_senders=set(settings.skip_senders) if settings.skip_senders else None,
                        skip_subjects=set(settings.skip_subjects) if settings.skip_subjects else None,
                        weights=settings.weights)
    return triage(store.all(), cfg)
