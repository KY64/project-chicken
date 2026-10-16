"""Dragos resources — filtered report listing.

Server-side rendered; aiohttp works. The configured URL carries the filter
query parameters (f3/f4) that pin the listing to Dragos reports. Each result
card puts its article anchor — absolute URL, plain-text title — inside a
``div.PagePromo-title``; the rest of the page (nav links, in-body
LinkEnhancement anchors) is excluded by that container requirement. The page
is static: every result is in the first response (the ``s=`` parameter is a
client-side cursor the server ignores), so there is no next page. The featured
carousel repeats cards many times, so URLs are deduplicated here.

Extraction is a container-anchored regex rather than an HTMLParser state
machine: the page's featured slides carry unbalanced divs around some cards,
which leaks open/close tracking onto unrelated anchors.
"""

import html as html_module
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://www.dragos.com/resources',)
WAIT_SELECTOR = 'div.PagePromo-title a.Link'

_TITLE_ANCHOR = re.compile(
    r'<div class="PagePromo-title">\s*'
    r'<a\b[^>]*?href="(?P<href>[^"]+)"[^>]*>(?P<title>[^<]+)</a>'
)


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, URL) pairs, None) — one static page, no pagination."""
    articles: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for match in _TITLE_ANCHOR.finditer(html):
        href = match.group('href').strip()
        title = ' '.join(html_module.unescape(match.group('title')).split())
        if not href.startswith(('http://', 'https://')) or not title:
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        articles.append((title, url))
    return articles, None
