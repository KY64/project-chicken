import asyncio
import os
import time
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from typing import List, Tuple, Optional, Set
from urllib.parse import urljoin, urlparse

import aiohttp
from playwright.sync_api import sync_playwright, Page


ACCESS_MODES = frozenset({'browser', 'browser_no_js', 'aiohttp'})


MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


class BaseScraper(ABC):
    """Scrape a site through a configured browser or direct HTTP mode."""

    NEXT_PAGE_SELECTOR = 'a:has-text("»")'
    PAGE_TIMEOUT_SECONDS = 45

    def __init__(self, base_url: str, access_mode: str):
        if access_mode not in ACCESS_MODES:
            raise ValueError(f"Unsupported access mode: {access_mode!r}")
        self.base_url = base_url
        self.access_mode = access_mode
        self.cdp_endpoint = os.getenv('PLAYWRIGHT_CDP_ENDPOINT')

    @abstractmethod
    def extract_articles(self, page: Page) -> List[Tuple[str, str]]:
        """Extract normalized (title, URL) pairs from a browser page."""
        raise NotImplementedError

    def extract_articles_from_html(self, html: str, page_url: str) -> Tuple[List[Tuple[str, str]], bool]:
        """Extract articles and pagination state from a fetched HTML document."""
        raise NotImplementedError(f"{type(self).__name__} does not support aiohttp mode")

    def scrape_articles(
        self,
        max_pages: Optional[int] = None,
        seen_urls: Optional[Set[str]] = None
    ) -> List[Tuple[str, str]]:
        """Scrape articles with bounded retries and exponential backoff.

        Stops after the first page containing any already-seen URL. The caller
        still filters those known articles from the returned results.

        Args:
            max_pages: Maximum pages to scrape (None = unlimited)
            seen_urls: URLs already published; any match stops pagination
        """
        for attempt in range(MAX_RETRIES):
            try:
                return self._scrape_articles_internal(max_pages, seen_urls)
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    print(f"Scraping failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {delay}s: {e}")
                    time.sleep(delay)
                else:
                    raise

    def _get_browser_and_page(self, playwright):
        """Get the local or Browserless browser and its page."""
        if self.cdp_endpoint:
            browser = playwright.chromium.connect_over_cdp(self.cdp_endpoint)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
        page = context.new_page()
        return browser, context, page

    def _scrape_articles_internal(
        self,
        max_pages: Optional[int] = None,
        seen_urls: Optional[Set[str]] = None
    ) -> List[Tuple[str, str]]:
        if self.access_mode == 'aiohttp':
            return asyncio.run(self._scrape_with_aiohttp(max_pages, seen_urls))
        return self._scrape_with_browser(max_pages, seen_urls)

    def _scrape_with_browser(
        self,
        max_pages: Optional[int],
        seen_urls: Optional[Set[str]]
    ) -> List[Tuple[str, str]]:
        articles = []
        page_num = 1

        with sync_playwright() as p:
            browser, context, page = self._get_browser_and_page(p)
            cdp_session = None
            try:
                if self.access_mode == 'browser_no_js':
                    cdp_session = context.new_cdp_session(page)
                    cdp_session.send('Emulation.setScriptExecutionDisabled', {'value': True})

                while True:
                    page_url = self.base_url if page_num == 1 else urljoin(self.base_url, f"{page_num}/")
                    page.goto(
                        page_url,
                        wait_until='domcontentloaded',
                        timeout=self.PAGE_TIMEOUT_SECONDS * 1000,
                    )
                    page_articles = self.extract_articles(page)
                    articles.extend(page_articles)

                    # Pages are newest-first. Once a page overlaps saved state,
                    # we've reached previously published articles; keep this page
                    # for the caller to filter, but don't fetch older pages.
                    if seen_urls and any(url in seen_urls for _, url in page_articles):
                        break

                    if max_pages is not None and page_num >= max_pages:
                        break
                    if not page.query_selector(self.NEXT_PAGE_SELECTOR):
                        break

                    page_num += 1
                    time.sleep(1)
            finally:
                if cdp_session:
                    cdp_session.detach()
                browser.close()

        return articles

    async def _scrape_with_aiohttp(
        self,
        max_pages: Optional[int],
        seen_urls: Optional[Set[str]]
    ) -> List[Tuple[str, str]]:
        articles = []
        page_num = 1
        timeout = aiohttp.ClientTimeout(total=self.PAGE_TIMEOUT_SECONDS)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                page_url = self.base_url if page_num == 1 else urljoin(self.base_url, f"{page_num}/")
                async with session.get(page_url) as response:
                    response.raise_for_status()
                    html = await response.text()
                    page_url = str(response.url)

                page_articles, has_next_page = self.extract_articles_from_html(html, page_url)
                articles.extend(page_articles)

                # Pages are newest-first. Once a page overlaps saved state,
                # we've reached previously published articles; keep this page
                # for the caller to filter, but don't fetch older pages.
                if seen_urls and any(url in seen_urls for _, url in page_articles):
                    break

                if max_pages is not None and page_num >= max_pages:
                    break
                if not has_next_page:
                    break

                page_num += 1
                await asyncio.sleep(1)

        return articles


class _CertPlHTMLParser(HTMLParser):
    """Extract CERT.pl article cards and its next-page marker from HTML."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.articles: List[Tuple[str, str]] = []
        self.has_next_page = False
        self._post_list_depth = 0
        self._card_href: Optional[str] = None
        self._title_depth = 0
        self._title_parts: List[str] = []
        self._anchor_stack: List[Tuple[bool, List[str]]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get('class') or '').split())

        if tag == 'ul':
            if self._post_list_depth or 'horizontal-post-list' in classes:
                self._post_list_depth += 1
        elif tag == 'a':
            is_card = self._post_list_depth > 0 and 'post-outer-container' in classes
            self._anchor_stack.append((is_card, []))
            if is_card:
                self._card_href = attributes.get('href')
                self._title_parts = []
        elif tag == 'h4' and self._card_href:
            self._title_depth += 1

    def handle_data(self, data: str) -> None:
        if self._anchor_stack:
            self._anchor_stack[-1][1].append(data)
        if self._title_depth:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'h4' and self._title_depth:
            self._title_depth -= 1
        elif tag == 'a' and self._anchor_stack:
            is_card, anchor_text = self._anchor_stack.pop()
            if '»' in ''.join(anchor_text):
                self.has_next_page = True
            if is_card and self._card_href:
                title = ' '.join(''.join(self._title_parts).split())
                if title:
                    self.articles.append((title, urljoin(self.page_url, self._card_href)))
                self._card_href = None
                self._title_parts = []
                self._title_depth = 0
        elif tag == 'ul' and self._post_list_depth:
            self._post_list_depth -= 1


class CertPlScraper(BaseScraper):
    """Scraper for CERT.pl news page."""

    ARTICLE_CARD_SELECTOR = 'ul.horizontal-post-list a.post-outer-container'

    def __init__(self, base_url: str, access_mode: str):
        super().__init__(base_url, access_mode)

    def extract_articles(self, page: Page) -> List[Tuple[str, str]]:
        """
        Extract articles from CERT.pl news page.

        Args:
            page: Playwright Page object

        Returns:
            List of (title, url) tuples
        """
        # Select card anchors rather than div:has(h4), which matches nested
        # page-level wrappers and repeats the first article. Waiting for one
        # also handles JS-rendered pages without waiting for unrelated network
        # activity to become idle.
        page.wait_for_selector(self.ARTICLE_CARD_SELECTOR, timeout=self.PAGE_TIMEOUT_SECONDS * 1000)
        return self.extract_articles_from_html(page.content(), page.url)[0]

    def extract_articles_from_html(self, html: str, page_url: str) -> Tuple[List[Tuple[str, str]], bool]:
        parser = _CertPlHTMLParser(page_url)
        parser.feed(html)
        return parser.articles, parser.has_next_page


def get_scraper_for_url(url: str, access_mode: str) -> BaseScraper:
    """Get the site scraper configured for the selected access mode."""
    if access_mode not in ACCESS_MODES:
        allowed = ', '.join(sorted(ACCESS_MODES))
        raise ValueError(f"Unsupported access mode {access_mode!r}; expected one of: {allowed}")

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    if 'cert.pl' in domain:
        return CertPlScraper(url, access_mode)
    raise ValueError(f"No scraper available for domain: {domain}")
