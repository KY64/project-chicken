"""Cloudforce One research feed — https://www.cloudflare.com/cloudforce-one/research/

Server-rendered, so aiohttp is enough. The page has no pagination: it lists
the whole current research set at once, like cure53.

The cards are built oddly — the anchor text is always "Read now", and the
real title sits in the block just above it, first paragraph of
``div[data-qa="FragmentMarkdown"]`` (sometimes wrapped in ``<strong>``).
So the parser records a block's first paragraph and pairs it with the next
research link.

Two markup hazards shaped this parser; preserve both if you change it:

- The newsletter form's fine print is also a FragmentMarkdown block. Title
  state must reset when every block starts, or form text becomes the next
  card's title.
- Card links come in three shapes: root-relative ``/cloudforce-one/research/``,
  root-relative ``/threat-intelligence/research/``, and absolute URLs on the
  apex host (``https://cloudflare.com/...``, no www). Absolute links are
  stripped to a path before matching, and urljoin then canonicalizes every
  URL to the configured origin, so the same card linked in two forms
  deduplicates.
"""

import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urljoin

URL_PREFIXES = ('https://www.cloudflare.com/cloudforce-one/research',)
WAIT_SELECTOR = 'a[data-qa="FragmentLink"][href^="/cloudforce-one/research/"]'

# Strip absolute link forms (www or apex) so one path regex covers all of them.
_ABS_CF_ORIGIN = re.compile(r'^https?://(?:www\.)?cloudflare\.com')
# Either research area, slug segments required; rejects the bare listing URLs.
_RESEARCH_HREF = re.compile(
    r'^/(?:cloudforce-one|threat-intelligence)/research/(?:[^/?#]+/)+$'
)


def extract(html: str, page_url: str) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return ((title, URL) pairs, None) — one static page, no pagination."""
    parser = _CloudforceHTMLParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.articles, None


class _CloudforceHTMLParser(HTMLParser):
    """Pair each card's first markdown paragraph with the research anchor after it."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self._seen_urls: set[str] = set()
        self._in_markdown = False
        self._title_parts: Optional[List[str]] = None
        self._pending_title: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)

        if tag == 'div' and attributes.get('data-qa') == 'FragmentMarkdown':
            # Reset per block: the newsletter form's fine print is also a
            # FragmentMarkdown block and must not become a card's title.
            self._in_markdown = True
            self._pending_title = None
            self._title_parts = None
            return

        if self._in_markdown and tag == 'p' and self._title_parts is None:
            self._title_parts = []
            return

        if tag == 'a' and attributes.get('data-qa') == 'FragmentLink':
            self._emit(attributes.get('href') or '')

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'p' and self._title_parts is not None:
            title = ' '.join(''.join(self._title_parts).split())
            # First paragraph of the block is the title; summaries below it
            # must not replace it.
            if title and self._pending_title is None:
                self._pending_title = title
            self._title_parts = None
        elif tag == 'div' and self._in_markdown:
            self._in_markdown = False

    def _emit(self, href: str) -> None:
        path = _ABS_CF_ORIGIN.sub('', href) or '/'
        if not _RESEARCH_HREF.match(path):
            return
        url = urljoin(self.page_url, path)
        if url in self._seen_urls:
            return
        title = self._pending_title
        if not title:
            return
        self._seen_urls.add(url)
        self.articles.append((title, url))
        self._pending_title = None
