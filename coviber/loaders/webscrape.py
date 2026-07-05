"""Web-scrape loader — config-driven DOM extraction, no per-site code.

Give it a URL and a set of CSS selectors and it turns any list-style web page
(an inbox, a channel, an issue list) into Records. This is the generic version
of CoViber's original per-platform parsers: the *structure* lives in config, not
in code, so a new site is a YAML block rather than a new parser.

Requires the [scrape] extra:  pip install "coviber[scrape]"

Example config (see examples/scrape_config.example.yaml):

    loader: webscrape
    config:
      url: https://news.ycombinator.com/
      source: hn
      record_selector: "tr.athing"
      fields:
        subject: {selector: "span.titleline a", attr: text}
        url:     {selector: "span.titleline a", attr: href}
"""
from __future__ import annotations

from typing import Iterable

from ..record import Record
from . import register
from .base import Loader


def _extract(el, spec: dict) -> str:
    if not spec:
        return ""
    sel = spec.get("selector")
    node = el.select_one(sel) if sel else el
    if node is None:
        return ""
    attr = spec.get("attr", "text")
    if attr == "text":
        return node.get_text(" ", strip=True)
    val = node.get(attr) or ""
    if isinstance(val, list):  # multi-valued attributes like class
        val = " ".join(val)
    return val.strip()


@register("webscrape")
class WebScrapeLoader(Loader):
    """config: url, source, record_selector, fields{field: {selector, attr}}.

    Optional: `html` (scrape a local HTML string/file instead of fetching),
    `headers`, `timeout`.
    """

    def load(self) -> Iterable[Record]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise ImportError('webscrape needs the [scrape] extra: pip install "coviber[scrape]"') from e

        html = self.config.get("html")
        if not html:
            url = self.config.get("url")
            if not url:
                raise ValueError("webscrape loader needs 'url' or 'html' in config")
            import urllib.request
            req = urllib.request.Request(url, headers=self.config.get("headers", {"User-Agent": "coviber/0.1"}))
            with urllib.request.urlopen(req, timeout=self.config.get("timeout", 20)) as resp:
                html = resp.read().decode("utf-8", "replace")
        elif html.strip().endswith(".html"):
            from pathlib import Path
            html = Path(html).read_text(encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")
        source = self.config.get("source", "web")
        base_url = self.config.get("url", "")
        rec_sel = self.config.get("record_selector")
        rows = soup.select(rec_sel) if rec_sel else [soup]
        fields = self.config.get("fields", {})
        for el in rows:
            data = {"source": source}
            for field_name, spec in fields.items():
                data[field_name] = _extract(el, spec)
            # relative -> absolute url (urljoin handles absolute, /abs, and doc-relative forms)
            if data.get("url") and base_url:
                from urllib.parse import urljoin
                data["url"] = urljoin(base_url, data["url"])
            if data.get("subject") or data.get("text"):
                yield Record.from_dict(data)
