"""Cure53 publications, scoped to the Recent section only.

The homepage lists reports grouped by year. Only the entries between
``<span id="publications-recent">`` and the next year marker are wanted;
older reports and the academic/tools sections stay out of the feed. Each
entry is a single anchor whose ``strong`` child holds the report title and
whose href is a relative PDF path. The section is fully rendered in one
page, so extraction ends after it.
"""

from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://cure53.de/',)
WAIT_SELECTOR = 'span#publications-recent'


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return report title/URL pairs from the Recent section; no next page."""
    parser = _Cure53HTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, None


class _Cure53HTMLParser(HTMLParser):
    """Collect anchors from the Recent publications span only.

    The section runs from ``span#publications-recent`` until the next
    ``span#publications-*`` marker; any other anchor on the page (nav,
    academic papers, tools) is ignored.
    """

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self._in_recent = False
        self._anchor_stack: List[Tuple[Optional[str], List[str]]] = []
        self._strong_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == 'span':
            span_id = attributes.get('id') or ''
            if span_id == 'publications-recent':
                self._in_recent = True
            elif span_id.startswith('publications-'):
                self._in_recent = False
        elif tag == 'a' and self._in_recent:
            self._anchor_stack.append((attributes.get('href'), []))
        elif tag == 'strong' and self._anchor_stack:
            self._strong_depth += 1

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._anchor_stack:
            self._anchor_stack[-1][1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'strong' and self._strong_depth:
            self._strong_depth -= 1
        elif tag == 'a' and self._anchor_stack:
            href, text_parts = self._anchor_stack.pop()
            title = ' '.join(''.join(text_parts).split())
            if href and title:
                self.articles.append((title, urljoin(self.page_url, href)))
