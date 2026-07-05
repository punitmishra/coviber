"""WebScrape loader tests — bs4 gated, offline only.

Covers the html-inline-vs-filepath detection (audit finding L3/#3): the old
`.endswith(".html")` heuristic misfired both ways — inline HTML with an
`<a href="/x.html">` looked like a file path, and a real `page.htm` never
did. Detection is now by `Path(...).is_file()`.

Run with: python -m pytest tests/test_webscrape_loader.py
"""
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("bs4")

from coviber import get_loader  # noqa: E402


def _minimal_html_page(title_text="Hello"):
    return (
        "<html><body><ul>"
        f'<li class="entry"><a href="/x.html">{title_text}</a></li>'
        "</ul></body></html>"
    )


CFG_TEMPLATE = {
    "source": "test",
    "record_selector": "li.entry",
    "fields": {
        "subject": {"selector": "a", "attr": "text"},
        "url": {"selector": "a", "attr": "href"},
    },
    "url": "https://example.com/",
}


def test_inline_html_string_does_not_get_misread_as_a_file_path():
    """Inline HTML that ends with `.html` (via an <a href="/x.html">) used to
    be misinterpreted as a filesystem path, raising FileNotFoundError.
    After the fix, inline HTML flows straight into BeautifulSoup."""
    cfg = {**CFG_TEMPLATE, "html": _minimal_html_page("Hello")}
    recs = list(get_loader("webscrape", cfg).load())
    assert len(recs) == 1
    assert recs[0].subject == "Hello"
    assert recs[0].url == "https://example.com/x.html"  # urljoin absolutized


def test_file_path_input_is_read_from_disk():
    """A path to a real file (any extension — not just .html) must be read
    from disk. The old heuristic missed .htm, .xhtml, .html.tmp, etc."""
    with tempfile.TemporaryDirectory() as d:
        for filename in ("page.html", "page.htm", "page.xhtml"):
            path = Path(d) / filename
            path.write_text(_minimal_html_page(f"from-{filename}"), encoding="utf-8")
            cfg = {**CFG_TEMPLATE, "html": str(path)}
            recs = list(get_loader("webscrape", cfg).load())
            assert len(recs) == 1
            assert recs[0].subject == f"from-{filename}"


def test_multiline_inline_html_never_matches_path_heuristic():
    """Multi-line inline HTML strings must NOT be probed as paths — POSIX
    filenames can't contain newlines, so `.is_file()` returns False, and
    the loader treats them as inline. Also guards against any embedded
    control chars raising OSError from `is_file()`."""
    cfg = {
        **CFG_TEMPLATE,
        "html": "\n".join([
            "<html><body>",
            '<ul><li class="entry">',
            '<a href="/page.html">Nested</a>',
            "</li></ul></body></html>",
        ]),
    }
    recs = list(get_loader("webscrape", cfg).load())
    assert recs[0].subject == "Nested"
