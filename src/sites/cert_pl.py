"""CERT.pl news page: article cards and » next-page links.

Article cards are anchors with class post-outer-container inside
ul.horizontal-post-list; the title is the card's h4 text. Pagination is a
plain anchor whose text is » with a relative href (e.g. ../news/2/).
"""

from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://cert.pl/en/news/',)
WAIT_SELECTOR = 'ul.horizontal-post-list a.post-outer-container'


class _CertPlHTMLParser(HTMLParser):
    """Extract CERT.pl article cards and its next-page link from HTML."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.next_page_url: Optional[str] = None
        self._post_list_depth = 0
        self._card_href: Optional[str] = None
        self._title_depth = 0
        self._title_parts: List[str] = []
        # Each entry is (is_card, href, text_parts) for one open anchor.
        self._anchor_stack: List[Tuple[bool, Optional[str], List[str]]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get('class') or '').split())

        if tag == 'ul':
            if self._post_list_depth or 'horizontal-post-list' in classes:
                self._post_list_depth += 1
        elif tag == 'a':
            is_card = self._post_list_depth > 0 and 'post-outer-container' in classes
            self._anchor_stack.append((is_card, attributes.get('href'), []))
            if is_card:
                self._card_href = attributes.get('href')
                self._title_parts = []
        elif tag == 'h4' and self._card_href:
            self._title_depth += 1

    def handle_data(self, data: str) -> None:
        if self._anchor_stack:
            self._anchor_stack[-1][2].append(data)
        if self._title_depth:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h4' and self._title_depth:
            self._title_depth -= 1
        elif tag == 'a' and self._anchor_stack:
            is_card, href, anchor_text = self._anchor_stack.pop()
            # The next-page link is the » anchor. Card anchors are excluded:
            # an article title could contain », and treating the card as a
            # next-page link would loop pagination into the article itself.
            if (
                self.next_page_url is None
                and not is_card
                and '»' in ''.join(anchor_text)
                and href
            ):
                self.next_page_url = urljoin(self.page_url, href)
            if is_card and self._card_href:
                title = ' '.join(''.join(self._title_parts).split())
                if title:
                    self.articles.append((title, urljoin(self.page_url, self._card_href)))
                self._card_href = None
                self._title_parts = []
                self._title_depth = 0
        elif tag == 'ul' and self._post_list_depth:
            self._post_list_depth -= 1


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, url) pairs, next page URL or None) for one page."""
    parser = _CertPlHTMLParser(page_url)
    parser.feed(html)
    return parser.articles, parser.next_page_url
