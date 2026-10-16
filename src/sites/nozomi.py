"""Nozomi Networks blog, Labs Research tag — /blog?tag=labs-research

The server ignores the tag query: aiohttp and browser_no_js both return the
unfiltered listing. Only the page's JS (JetBoost) applies it: it checks the
matching filter checkbox and re-renders the list to just the tag's posts
(verified: 30 of ~100 cards, re-ordered, stale cards removed rather than
hidden). So this site uses ``browser`` mode, and WAIT_SELECTOR is the
labs-research checkbox in its checked state — the same trigger the filter
script sets right before re-rendering the list.

Deliberately no next-page URL: the Webflow pager href is a bare
"?<hash>_page=N" query, and following it would drop ?tag=labs-research from
the URL and fetch an unfiltered page. All posts for the tag render within
the first page (newest-first), which is exactly what the feed needs.
"""

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://www.nozominetworks.com/blog',)
WAIT_SELECTOR = (
    'div.filter-block-line-item-wrapper:has(> div input.jetboost-list-item[value="labs-research"])'
    ' input.w-checkbox-input:checked'
)

_CARD_HREF = re.compile(r'^/blog/[a-z0-9-]+$')


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, URL) pairs, None) — one filtered page, no pagination."""
    parser = _NozomiHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, None


class _NozomiHTMLParser(HTMLParser):
    """Collect card anchors (class blog-page-link-block) and their inner <h2>."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self._seen_urls: set[str] = set()
        self._card_href: Optional[str] = None
        self._title_parts: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)

        if tag == 'a':
            href = attributes.get('href') or ''
            classes = set((attributes.get('class') or '').split())
            if 'blog-page-link-block' in classes and _CARD_HREF.match(href):
                url = urljoin(self.page_url, href)
                if url not in self._seen_urls:
                    self._card_href = url
            return

        if tag == 'h2' and self._card_href is not None and self._title_parts is None:
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h2' and self._title_parts is not None:
            title = ' '.join(''.join(self._title_parts).split())
            if title:
                self._seen_urls.add(self._card_href)
                self.articles.append((title, self._card_href))
            self._title_parts = None
        elif tag == 'a':
            # End of an anchor: drop half-collected state so a heading outside
            # a card can never attach to a stale href.
            self._card_href = None
            self._title_parts = None
