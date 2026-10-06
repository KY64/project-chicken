"""JFrog Security Research — https://research.jfrog.com/post/

Server-side rendered; aiohttp works. Articles are anchors with the class
``single-post-preview``; the title lives in the anchor's ``data-gal``
attribute ("Title | /post/slug/"). Pagination is numbered links
(``/post/page/N/``) with no "Next" anchor, so the next page is the smallest
numbered link greater than the current page number; the last page shows no
greater link and pagination ends there.
"""

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

URL_PREFIXES = ('https://research.jfrog.com/post/',)
WAIT_SELECTOR = 'a.single-post-preview'

# data-gal is "Article Title | /post/slug/".
_DATA_GAL = re.compile(r'^(?P<title>.+?)\s*\|\s*/post/.*$')
# Page paths are /post/ or /post/page/N/.
_PAGE_PATH = re.compile(r'^/post/(?:page/(?P<number>\d+)/)?$')


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, URL) pairs, next page URL or None) for one page."""
    parser = _JfrogHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, parser.next_page_url


class _JfrogHTMLParser(HTMLParser):
    """Collect article anchors and the smallest future page link."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None
        self._page_numbers: List[int] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != 'a':
            return
        attributes = dict(attrs)
        href = attributes.get('href') or ''
        classes = set((attributes.get('class') or '').split())

        if 'single-post-preview' in classes:
            match = _DATA_GAL.match(attributes.get('data-gal') or '')
            if match and href.startswith('/post/'):
                self.articles.append((match.group('title'), urljoin(self.page_url, href)))
        elif href.startswith('/post/page/'):
            page = _PAGE_PATH.match(urlsplit(urljoin(self.page_url, href)).path)
            if page and page.group('number'):
                self._page_numbers.append(int(page.group('number')))

    def close(self) -> None:
        super().close()
        current = _PAGE_PATH.match(urlsplit(self.page_url).path)
        if current:
            current_number = int(current.group('number') or 1)
            greater = [n for n in self._page_numbers if n > current_number]
            if greater:
                self.next_page_url = urljoin(self.page_url, f'/post/page/{min(greater)}/')
