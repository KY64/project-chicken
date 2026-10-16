"""TXOne Networks white papers — https://www.txone.com/resources/white-papers/

Server-side rendered (Next.js static output); aiohttp works. Each result is
a card anchor whose href is a relative ``/resources/white-papers/<slug>/``;
the title lives in the ``<h3>`` nested inside the anchor. The listing is a
single page — no pagination markup and ``/page/2`` is 404 — so extraction
returns no next page. One card is also rendered as a featured duplicate, so
URLs are deduplicated here.
"""

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://www.txone.com/resources/white-papers/',)
WAIT_SELECTOR = 'a[href^="/resources/white-papers/"] h3'

_CARD_HREF = re.compile(r'^/resources/white-papers/[^?#]+/?$')


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, URL) pairs, None) — one static page, no pagination."""
    parser = _TxoneHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, None


class _TxoneHTMLParser(HTMLParser):
    """Collect card anchors and take the first inner <h3> as the title."""

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
            if _CARD_HREF.match(href):
                url = urljoin(self.page_url, href)
                if url not in self._seen_urls:
                    self._card_href = url
            return

        if tag == 'h3' and self._card_href is not None and self._title_parts is None:
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h3' and self._title_parts is not None:
            title = ' '.join(''.join(self._title_parts).split())
            if title:
                self._seen_urls.add(self._card_href)
                self.articles.append((title, self._card_href))
            self._title_parts = None
        elif tag == 'a':
            # End of the card anchor: drop half-collected state so a heading
            # outside a card can never attach to a stale href.
            self._card_href = None
            self._title_parts = None
