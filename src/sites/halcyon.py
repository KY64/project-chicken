"""Halcyon ransomware research reports.

The reports listing is server-rendered. Each CMS list item has a title in
``h3.rra-report_header`` and a Read Report link under
``/ransomware-research-reports/``. The page exposes all current cards and no
next-page control, so extraction ends after this listing.
"""

from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://www.halcyon.ai/ransomware-research/reports',)
WAIT_SELECTOR = 'h3.rra-report_header'


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return report title/URL pairs; this listing has no next page."""
    parser = _HalcyonHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, None


class _HalcyonHTMLParser(HTMLParser):
    """Extract one title and its Read Report URL from each CMS list item."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self._div_list_item_stack: List[bool] = []
        self._card_depth = 0
        self._card_title: Optional[str] = None
        self._card_url: Optional[str] = None
        self._title_depth = 0
        self._title_parts: List[str] = []
        self._anchor_stack: List[Tuple[Optional[str], List[str]]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == 'div':
            is_list_item = attributes.get('role') == 'listitem'
            self._div_list_item_stack.append(is_list_item)
            if is_list_item:
                if self._card_depth == 0:
                    self._card_title = None
                    self._card_url = None
                self._card_depth += 1
        elif tag == 'h3' and self._card_depth:
            classes = set((attributes.get('class') or '').split())
            if 'rra-report_header' in classes:
                self._title_depth += 1
                self._title_parts = []
        elif tag == 'a':
            self._anchor_stack.append((attributes.get('href'), []))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)
        if self._anchor_stack:
            self._anchor_stack[-1][1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h3' and self._title_depth:
            self._title_depth -= 1
            title = ' '.join(''.join(self._title_parts).split())
            if title:
                self._card_title = title
        elif tag == 'a' and self._anchor_stack:
            href, text_parts = self._anchor_stack.pop()
            label = ' '.join(''.join(text_parts).split())
            if (
                self._card_depth
                and self._card_url is None
                and href
                and href.startswith('/ransomware-research-reports/')
                and label.lower() == 'read report'
            ):
                self._card_url = urljoin(self.page_url, href)
        elif tag == 'div' and self._div_list_item_stack:
            if self._div_list_item_stack.pop():
                self._card_depth -= 1
                if self._card_depth == 0 and self._card_title and self._card_url:
                    self.articles.append((self._card_title, self._card_url))
