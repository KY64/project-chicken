"""Huntress Threat Analysis blog category.

The category shell arrives in server HTML, but article cards are hydrated by
JavaScript; fetch with the Browserless-backed ``browser`` mode. Cards are
anchors with ``blog-index-card-link`` and title/href attributes. Pagination
is a client-side button, but each page is addressable by ``?page=N``; the
rendered ``Page N of M`` label supplies the next URL.
"""

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

URL_PREFIXES = ('https://www.huntress.com/blog-categories/threat-analysis',)
WAIT_SELECTOR = 'a.blog-index-card-link[href^="/blog/"]'

_PAGE_LABEL = re.compile(r'^Page\s+(\d+)\s+of\s+(\d+)$')


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return the rendered category articles and the next query-page URL."""
    parser = _HuntressHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, parser.next_page_url


class _HuntressHTMLParser(HTMLParser):
    """Read article cards and the rendered pagination range."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None
        self._pagination: Optional[Tuple[int, int]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        label = _PAGE_LABEL.match(attributes.get('aria-label') or '')
        if label:
            self._pagination = (int(label.group(1)), int(label.group(2)))
        if tag == 'a':
            classes = set((attributes.get('class') or '').split())
            href = attributes.get('href') or ''
            title = (attributes.get('title') or '').strip()
            if 'blog-index-card-link' in classes and href.startswith('/blog/') and title:
                self.articles.append((title, urljoin(self.page_url, href)))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)

    def close(self) -> None:
        super().close()
        if not self._pagination:
            return
        current, total = self._pagination
        if current >= total:
            return
        parts = urlsplit(self.page_url)
        query = parse_qs(parts.query, keep_blank_values=True)
        query['page'] = [str(current + 1)]
        self.next_page_url = urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query, doseq=True),
            parts.fragment,
        ))
