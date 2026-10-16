"""Shared scraping engine.

Site-specific parsing lives in one module per site under ``sites``; this
module owns everything shared: access modes, retries, pagination, and
browser wiring. A site module defines only URL_PREFIXES, WAIT_SELECTOR,
and ``extract(html, page_url)`` returning (articles, next_page_url).
"""

import asyncio
import os
import time
from typing import List, Optional, Set, Tuple

import aiohttp
from playwright.sync_api import sync_playwright

import sites

ACCESS_MODES = frozenset({'browser', 'browser_no_js', 'aiohttp'})

MAX_RETRIES = 3
BASE_DELAY = 2  # seconds

# The whole per-site contract; sites/__init__.py validates it at import time.
SITE_MODULE_ATTRIBUTES = ('URL_PREFIXES', 'WAIT_SELECTOR', 'extract')


class SiteScraper:
    """Scraping engine for one site.

    ``site`` is a module from the ``sites`` package. The engine fetches pages
    through the configured access mode and follows the next-page URL the site
    module extracts; it never constructs pagination URLs itself, so "how to go
    to the next page" stays a per-site concern.
    """

    PAGE_TIMEOUT_SECONDS = 45

    def __init__(self, site, base_url: str, access_mode: str):
        if access_mode not in ACCESS_MODES:
            raise ValueError(f"Unsupported access mode: {access_mode!r}")
        missing = [name for name in SITE_MODULE_ATTRIBUTES if not hasattr(site, name)]
        if missing:
            raise ValueError(
                f"{getattr(site, '__name__', site)!r} is not a site module; "
                f"missing: {', '.join(missing)}"
            )
        self.site = site
        self.base_url = base_url
        self.access_mode = access_mode
        self.cdp_endpoint = os.getenv('PLAYWRIGHT_CDP_ENDPOINT')

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
        fetched_urls = set()

        with sync_playwright() as p:
            browser, context, page = self._get_browser_and_page(p)
            cdp_session = None
            try:
                if self.access_mode == 'browser_no_js':
                    cdp_session = context.new_cdp_session(page)
                    cdp_session.send('Emulation.setScriptExecutionDisabled', {'value': True})

                # Stop on a missing next-page URL or one already fetched, so a
                # self-referential "next" link cannot loop the run forever.
                next_page_url = self.base_url
                while next_page_url and next_page_url not in fetched_urls:
                    fetched_urls.add(next_page_url)
                    page.goto(
                        next_page_url,
                        wait_until='domcontentloaded',
                        timeout=self.PAGE_TIMEOUT_SECONDS * 1000,
                    )
                    page.wait_for_selector(
                        self.site.WAIT_SELECTOR,
                        timeout=self.PAGE_TIMEOUT_SECONDS * 1000,
                    )
                    page_articles, next_page_url = self.site.extract(page.content(), page.url)
                    articles.extend(page_articles)
                    print(f"    Page {len(fetched_urls)}: {len(page_articles)} articles")

                    # Pages are newest-first. Once a page overlaps saved state,
                    # we've reached previously published articles; keep this page
                    # for the caller to filter, but don't fetch older pages.
                    if seen_urls and any(url in seen_urls for _, url in page_articles):
                        print(f"    Stopping: page {len(fetched_urls)} matches saved state")
                        break

                    if max_pages is not None and len(fetched_urls) >= max_pages:
                        print(f"    Stopping: reached max_pages={max_pages}")
                        break

                    # Pace pages only when another fetch will actually happen.
                    if next_page_url and next_page_url not in fetched_urls:
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
        fetched_urls = set()
        timeout = aiohttp.ClientTimeout(total=self.PAGE_TIMEOUT_SECONDS)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Same loop shape as the browser path: follow the site's next-page
            # URL, stop on seen URLs / max_pages / a re-visited URL.
            next_page_url = self.base_url
            while next_page_url and next_page_url not in fetched_urls:
                fetched_urls.add(next_page_url)
                async with session.get(next_page_url) as response:
                    response.raise_for_status()
                    html = await response.text()
                    page_url = str(response.url)

                page_articles, next_page_url = self.site.extract(html, page_url)
                articles.extend(page_articles)
                print(f"    Page {len(fetched_urls)}: {len(page_articles)} articles")

                # Pages are newest-first. Once a page overlaps saved state,
                # we've reached previously published articles; keep this page
                # for the caller to filter, but don't fetch older pages.
                if seen_urls and any(url in seen_urls for _, url in page_articles):
                    print(f"    Stopping: page {len(fetched_urls)} matches saved state")
                    break

                if max_pages is not None and len(fetched_urls) >= max_pages:
                    print(f"    Stopping: reached max_pages={max_pages}")
                    break

                # Pace pages only when another fetch will actually happen.
                if next_page_url and next_page_url not in fetched_urls:
                    await asyncio.sleep(1)

        return articles


def get_scraper_for_url(url: str, access_mode: str) -> SiteScraper:
    """Get the site scraper configured for the selected access mode."""
    if access_mode not in ACCESS_MODES:
        allowed = ', '.join(sorted(ACCESS_MODES))
        raise ValueError(f"Unsupported access mode {access_mode!r}; expected one of: {allowed}")

    return SiteScraper(sites.get_site_for_url(url), url, access_mode)
