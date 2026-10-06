"""SafeDep.io malware category listing.

Article cards are anchors inside an h2 (title is the anchor text; href is
site-root-relative like /some-post-slug). Pagination is an anchor whose
text is Next (e.g. href="/category/malware/2"); later pages also carry a
Previous link that must be ignored.
"""

from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://safedep.io/category/malware/',)
WAIT_SELECTOR = 'h2 a'


class _SafeDepHTMLParser(HTMLParser):
    """Extract article links and the Next link from a category page."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None
        self._h2_depth = 0
        # Each entry is (is_article, href, text_parts) for one open anchor.
        self._anchor_stack: List[Tuple[bool, Optional[str], List[str]]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == 'h2':
            self._h2_depth += 1
        elif tag == 'a':
            self._anchor_stack.append((self._h2_depth > 0, attributes.get('href'), []))

    def handle_data(self, data: str) -> None:
        if self._anchor_stack:
            self._anchor_stack[-1][2].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h2' and self._h2_depth:
            self._h2_depth -= 1
        elif tag == 'a' and self._anchor_stack:
            is_article, href, anchor_text = self._anchor_stack.pop()
            title = ' '.join(''.join(anchor_text).split())
            if is_article:
                if title and href:
                    self.articles.append((title, urljoin(self.page_url, href)))
            # Exact text match so the Previous link (and any other nav
            # anchor) is ignored. If the markup changes so the Next anchor
            # no longer reads exactly "Next", pagination stops early rather
            # than looping — fail closed.
            elif self.next_page_url is None and title == 'Next' and href:
                self.next_page_url = urljoin(self.page_url, href)


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, url) pairs, next page URL or None) for one page."""
    parser = _SafeDepHTMLParser(page_url)
    parser.feed(html)
    return parser.articles, parser.next_page_url
