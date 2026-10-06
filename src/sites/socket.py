"""Socket.dev Security News category.

The category is protected by Cloudflare: use the Browserless-backed
``browser`` mode, with the production Stealth route configured through
``PLAYWRIGHT_CDP_ENDPOINT``. Article cards are labeled anchors styled as
vertical cards; the Next page link provides a direct ``?page=N`` URL.
"""

from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://socket.dev/blog/category/security-news',)
WAIT_SELECTOR = 'a[aria-label][href^="/blog/"].flex-d_column'


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return rendered Security News cards and the next page URL."""
    parser = _SocketHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, parser.next_page_url


class _SocketHTMLParser(HTMLParser):
    """Extract card title/hrefs and the category's Next page link."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != 'a':
            return
        attributes = dict(attrs)
        href = attributes.get('href') or ''
        label = attributes.get('aria-label') or ''
        classes = set((attributes.get('class') or '').split())

        if (
            'flex-d_column' in classes
            and label
            and href.startswith('/blog/')
            and not href.startswith('/blog/category/')
        ):
            self.articles.append((label.strip(), urljoin(self.page_url, href)))
        elif label == 'Next page' and href:
            self.next_page_url = urljoin(self.page_url, href)
