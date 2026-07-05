"""Loader registry — resolve a loader by name at runtime.

Built-in loaders self-register on import. Third-party loaders register via the
`@register("name")` decorator or the `coviber.loaders` entry-point group.
"""
from __future__ import annotations

from importlib import metadata
from typing import Type

from .base import Loader

_REGISTRY: dict[str, Type[Loader]] = {}


def register(name: str):
    def deco(cls: Type[Loader]) -> Type[Loader]:
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            import warnings
            warnings.warn(f"coviber loader '{name}' re-registered by {cls.__module__}.{cls.__name__}",
                          stacklevel=2)
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def get_loader(name: str, config: dict | None = None) -> Loader:
    _load_entrypoints()
    if name not in _REGISTRY:
        raise KeyError(f"unknown loader '{name}'. available: {', '.join(available())}")
    return _REGISTRY[name](config)


def available() -> list[str]:
    _load_entrypoints()
    return sorted(_REGISTRY)


_ENTRYPOINTS_LOADED = False


def _load_entrypoints():
    global _ENTRYPOINTS_LOADED
    if _ENTRYPOINTS_LOADED:
        return
    _ENTRYPOINTS_LOADED = True
    try:
        eps = metadata.entry_points(group="coviber.loaders")
    except TypeError:  # Python 3.9: entry_points() takes no selection kwargs
        eps = metadata.entry_points().get("coviber.loaders", [])
    except Exception:
        eps = []
    for ep in eps:
        try:
            ep.load()  # importing the module runs its @register
        except Exception as exc:
            # Fail-open on plugin load errors so an uninstalled optional-extra
            # entry-point (or a temporarily-broken third-party plugin) doesn't
            # take out the whole registry. But surface the failure so a
            # third-party author sees WHY their plugin didn't register —
            # marketing "write your own loader in ~10 lines" means the
            # extension seam must be observable when it silently fails.
            import warnings
            ep_name = getattr(ep, "name", "?")
            ep_value = getattr(ep, "value", "?")
            warnings.warn(
                f"coviber: entry-point '{ep_name}' -> '{ep_value}' failed to load "
                f"({type(exc).__name__}: {exc})",
                RuntimeWarning, stacklevel=2,
            )


# Import built-ins so they register.
from . import demo, imap, jsonl, mbox, slackexport, webscrape  # noqa: E402,F401
