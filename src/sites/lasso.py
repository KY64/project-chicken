"""Lasso Security research publications.

The publications list is server-rendered. Rows use
``a.publications_row`` with the title in ``h3.publications_title``. The
"Load More" link carries the next page in a query parameter, so each page
can be fetched directly with aiohttp.
"""

from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://www.lasso.security/research',)
WAIT_SELECTOR = 'a.publications_row[href^="/blog/"]'


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return one publications page and its Load More URL, if present."""
    parser = _LassoHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, parser.next_page_url


class _LassoHTMLParser(HTMLParser):
    """Collect publication rows, excluding the separate featured article."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None
        self._article_href: Optional[str] = None
        self._article_title: Optional[str] = None
        self._title_depth = 0
        self._title_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == 'a':
            href = attributes.get('href') or ''
            classes = set((attributes.get('class') or '').split())
            if 'publications_row' in classes and href.startswith('/blog/'):
                self._article_href = href
                self._article_title = None
            elif attributes.get('aria-label') == 'Next Page' and href:
                self.next_page_url = urljoin(self.page_url, href)
        elif tag == 'h3' and self._article_href:
            classes = set((attributes.get('class') or '').split())
            if 'publications_title' in classes:
                self._title_depth += 1
                self._title_parts = []

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h3' and self._title_depth:
            self._title_depth -= 1
            title = ' '.join(''.join(self._title_parts).split())
            if title:
                self._article_title = title
        elif tag == 'a' and self._article_href:
            if self._article_title:
                self.articles.append((self._article_title, urljoin(self.page_url, self._article_href)))
            self._article_href = None
            self._article_title = None
