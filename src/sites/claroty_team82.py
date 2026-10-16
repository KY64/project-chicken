"""Claroty Team82 research feed — https://claroty.com/team82/research

Server-side rendered; aiohttp works. Articles are anchors with the class
``entry-card`` whose href starts with ``/team82/research/``; the title lives
in the ``<h2>`` nested inside the anchor. Pagination is a ``<link
rel="next">`` tag in the head pointing at ``?team82_resources_page=N``; the
last page (and past-end pages) omit it, so extraction ends naturally.
"""

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://claroty.com/team82/research',)
WAIT_SELECTOR = 'a.entry-card[href^="/team82/research/"]'

_ARTICLE_HREF = re.compile(r'^/team82/research/[a-z0-9-]+$')


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, URL) pairs, next page URL or None) for one page."""
    parser = _ClarityHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, parser.next_page_url


class _ClarityHTMLParser(HTMLParser):
    """Collect entry-card anchors (title from their inner <h2>) and rel=next."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None
        self._seen_hrefs: set[str] = set()
        self._card_href: Optional[str] = None
        self._title_parts: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)

        if tag == 'link' and attributes.get('rel') == 'next':
            href = attributes.get('href') or ''
            if href:
                self.next_page_url = urljoin(self.page_url, href)
            return

        if tag == 'a':
            href = attributes.get('href') or ''
            classes = set((attributes.get('class') or '').split())
            if 'entry-card' in classes and _ARTICLE_HREF.match(href):
                # Only the card anchor; nested text is collected below.
                if href not in self._seen_hrefs:
                    self._card_href = urljoin(self.page_url, href)
            return

        if tag == 'h2' and self._card_href is not None and self._title_parts is None:
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h2' and self._title_parts is not None:
            title = re.sub(r'\s+', ' ', ''.join(self._title_parts)).strip()
            if title:
                self._seen_hrefs.add(self._card_href)
                self.articles.append((title, self._card_href))
            self._title_parts = None
        elif tag == 'a':
            # End of the card anchor: drop any half-collected state so a
            # heading outside a card can never attach to a stale href.
            self._card_href = None
            self._title_parts = None
