import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sites
from main import load_site_config
from scraper import ACCESS_MODES, SiteScraper, get_scraper_for_url
from git_operations import get_app_env, pushes_enabled


# --- Stub site modules ----------------------------------------------------
#
# The unit tests target the general scraping mechanism, not any particular
# site's markup. These stubs implement the site contract (URL_PREFIXES,
# WAIT_SELECTOR, extract) with deliberately different extract implementations
# and pagination shapes, so the engine must work with both without knowing
# either's HTML. Real modules under src/sites/ are only used to check URL
# resolution in SiteRegistryTests.

def _extract_titled(html, page_url):
    """Pages are JSON with "items" ([{title, href}]) and "more" keys."""
    data = json.loads(html)
    articles = [(item["title"], urljoin(page_url, item["href"])) for item in data["items"]]
    next_url = urljoin(page_url, data["more"]) if data.get("more") else None
    return articles, next_url


def _extract_paired(html, page_url):
    """Pages are JSON with "posts" ([[title, url]]) and "next" keys."""
    data = json.loads(html)
    articles = [(title, urljoin(page_url, url)) for title, url in data["posts"]]
    next_url = urljoin(page_url, data["next"]) if data.get("next") else None
    return articles, next_url


def _page_titled(articles, next_href=None):
    return json.dumps({
        "items": [{"title": title, "href": href} for title, href in articles],
        "more": next_href,
    })


def _page_paired(articles, next_href=None):
    return json.dumps({
        "posts": [[title, href] for title, href in articles],
        "next": next_href,
    })


STUB_SITES = (
    SimpleNamespace(
        URL_PREFIXES=("https://stub-titled.example/",),
        WAIT_SELECTOR="#app",
        extract=_extract_titled,
        page=_page_titled,
    ),
    SimpleNamespace(
        URL_PREFIXES=("https://stub-paired.example/",),
        WAIT_SELECTOR=".post",
        extract=_extract_paired,
        page=_page_paired,
    ),
)


class SiteConfigTests(unittest.TestCase):
    def test_site_config_loads_access_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "site.csv"
            config.write_text(
                "https://cert.pl/en/news/,site-cert-pl,state/cert-pl.csv,browser_no_js\n",
                encoding="utf-8",
            )

            self.assertEqual(
                load_site_config(str(config)),
                [("https://cert.pl/en/news/", "site-cert-pl", "state/cert-pl.csv", "browser_no_js")],
            )

    def test_site_config_rejects_unknown_access_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "site.csv"
            config.write_text("https://cert.pl/,branch,state.csv,unknown\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown access mode"):
                load_site_config(str(config))

    def test_site_config_requires_four_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "site.csv"
            config.write_text("https://cert.pl/,branch,state.csv\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "expected 4 columns"):
                load_site_config(str(config))


class EngineTests(unittest.TestCase):
    """The general scraping mechanism, verified with stub site modules.

    What differs per site is only what extract() returns; the engine's
    behavior (pagination, termination, cutoff) must not depend on it.
    """

    def _scrape(self, site, make_pages, start_path, make_seen_urls=None, max_pages=None):
        """Run SiteScraper against a local server.

        make_pages(base_url) -> {path: body}; make_seen_urls(base_url) -> URLs
        the engine should treat as already seen. Returns (visited, articles,
        base_url).
        """
        pages = {}
        seen_urls = set()
        visited = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                visited.append(self.path)
                encoded = pages[self.path].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        base_url = f"http://127.0.0.1:{server.server_port}"
        pages.update(make_pages(base_url))
        if make_seen_urls is not None:
            seen_urls.update(make_seen_urls(base_url))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            scraper = SiteScraper(site, f"{base_url}{start_path}", "aiohttp")
            articles = scraper.scrape_articles(max_pages=max_pages, seen_urls=seen_urls)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        return visited, articles, base_url

    def test_engine_collects_single_page_when_no_next_page(self):
        for site in STUB_SITES:
            with self.subTest(site=site.URL_PREFIXES[0]):
                visited, articles, base_url = self._scrape(
                    site,
                    lambda base: {"/news/": site.page([("One", "/one/"), ("Two", "/two/")])},
                    "/news/",
                )

                self.assertEqual(visited, ["/news/"])
                self.assertEqual(
                    articles,
                    [("One", f"{base_url}/one/"), ("Two", f"{base_url}/two/")],
                )

    def test_engine_returns_empty_when_site_has_no_articles(self):
        for site in STUB_SITES:
            with self.subTest(site=site.URL_PREFIXES[0]):
                visited, articles, _ = self._scrape(
                    site,
                    lambda base: {"/news/": site.page([])},
                    "/news/",
                )

                self.assertEqual(visited, ["/news/"])
                self.assertEqual(articles, [])

    def test_engine_follows_next_page_reported_by_site(self):
        for site in STUB_SITES:
            with self.subTest(site=site.URL_PREFIXES[0]):
                visited, articles, base_url = self._scrape(
                    site,
                    lambda base: {
                        "/news/": site.page([("One", "/one/")], next_href="2/"),
                        "/news/2/": site.page([("Two", "/two/")]),
                    },
                    "/news/",
                )

                # The engine follows whatever next-page URL the site module
                # reports; it never constructs pagination URLs itself.
                self.assertEqual(visited, ["/news/", "/news/2/"])
                self.assertEqual(
                    articles,
                    [("One", f"{base_url}/one/"), ("Two", f"{base_url}/two/")],
                )

    def test_engine_stops_after_page_overlaps_seen_urls(self):
        for site in STUB_SITES:
            with self.subTest(site=site.URL_PREFIXES[0]):
                visited, articles, base_url = self._scrape(
                    site,
                    lambda base: {
                        "/news/": site.page(
                            [("New", "/new/"), ("Seen", "/seen/")], next_href="2/"
                        ),
                        "/news/2/": site.page([("Older", "/older/")]),
                    },
                    "/news/",
                    make_seen_urls=lambda base: {f"{base}/seen/"},
                )

                # The overlapping page is kept for the caller to filter;
                # older pages are not fetched.
                self.assertEqual(visited, ["/news/"])
                self.assertEqual(
                    articles,
                    [("New", f"{base_url}/new/"), ("Seen", f"{base_url}/seen/")],
                )

    def test_engine_respects_max_pages(self):
        for site in STUB_SITES:
            with self.subTest(site=site.URL_PREFIXES[0]):
                visited, _, _ = self._scrape(
                    site,
                    lambda base: {
                        "/news/": site.page([("One", "/one/")], next_href="2/"),
                        "/news/2/": site.page([("Two", "/two/")], next_href="3/"),
                        "/news/3/": site.page([("Three", "/three/")]),
                    },
                    "/news/",
                    max_pages=2,
                )

                self.assertEqual(visited, ["/news/", "/news/2/"])

    def test_engine_stops_when_next_page_repeats_current_page(self):
        for site in STUB_SITES:
            with self.subTest(site=site.URL_PREFIXES[0]):
                visited, articles, _ = self._scrape(
                    site,
                    lambda base: {"/news/": site.page([("One", "/one/")], next_href="/news/")},
                    "/news/",
                )

                # A self-referential next link must not loop the run forever.
                self.assertEqual(visited, ["/news/"])
                self.assertEqual([title for title, _ in articles], ["One"])

    def test_engine_rejects_incomplete_site_module(self):
        incomplete = SimpleNamespace(URL_PREFIXES=("https://x.example/",), WAIT_SELECTOR="a")

        with self.assertRaisesRegex(ValueError, "not a site module"):
            SiteScraper(incomplete, "https://x.example/", "aiohttp")


class SiteRegistryTests(unittest.TestCase):
    """URL resolution loads the right site module for different sites."""

    def test_registry_resolves_every_registered_site(self):
        for module in sites.SITES:
            for prefix in module.URL_PREFIXES:
                with self.subTest(site=module.__name__, prefix=prefix):
                    self.assertIs(get_scraper_for_url(prefix, "aiohttp").site, module)

    def test_registry_prefers_longest_matching_prefix(self):
        broad = SimpleNamespace(
            URL_PREFIXES=("https://example.com/",), WAIT_SELECTOR="a", extract=lambda h, u: ([], None)
        )
        narrow = SimpleNamespace(
            URL_PREFIXES=("https://example.com/malware/",), WAIT_SELECTOR="a", extract=lambda h, u: ([], None)
        )
        original = sites.SITES
        sites.SITES = [broad, narrow]
        try:
            self.assertIs(sites.get_site_for_url("https://example.com/malware/page"), narrow)
            self.assertIs(sites.get_site_for_url("https://example.com/other"), broad)
        finally:
            sites.SITES = original

    def test_factory_accepts_each_access_mode(self):
        url = sites.SITES[0].URL_PREFIXES[0]
        for access_mode in ACCESS_MODES:
            with self.subTest(access_mode=access_mode):
                scraper = get_scraper_for_url(url, access_mode)
                self.assertEqual(scraper.access_mode, access_mode)

    def test_factory_rejects_unknown_url(self):
        with self.assertRaisesRegex(ValueError, "No site module"):
            get_scraper_for_url("https://unknown.example/news/", "aiohttp")

    def test_factory_does_not_match_url_substrings(self):
        # Sites match by URL prefix, so a URL that merely contains another
        # site's prefix must not resolve to it.
        prefix = sites.SITES[0].URL_PREFIXES[0]
        with self.assertRaisesRegex(ValueError, "No site module"):
            get_scraper_for_url(f"https://evil.example.com/{prefix}", "aiohttp")


class AppEnvTests(unittest.TestCase):
    def setUp(self):
        # Save original APP_ENV if set
        self._original_app_env = os.environ.get("APP_ENV")

    def tearDown(self):
        # Restore original APP_ENV
        if self._original_app_env is not None:
            os.environ["APP_ENV"] = self._original_app_env
        elif "APP_ENV" in os.environ:
            del os.environ["APP_ENV"]

    def test_get_app_env_accepts_develop(self):
        os.environ["APP_ENV"] = "develop"
        self.assertEqual(get_app_env(), "develop")

    def test_get_app_env_accepts_production(self):
        os.environ["APP_ENV"] = "production"
        self.assertEqual(get_app_env(), "production")

    def test_get_app_env_rejects_unset(self):
        if "APP_ENV" in os.environ:
            del os.environ["APP_ENV"]
        with self.assertRaises(SystemExit) as cm:
            get_app_env()
        self.assertIn("APP_ENV must be set", str(cm.exception))

    def test_get_app_env_rejects_unknown(self):
        os.environ["APP_ENV"] = "staging"
        with self.assertRaises(SystemExit) as cm:
            get_app_env()
        self.assertIn("staging", str(cm.exception))

    def test_pushes_enabled_true_in_production(self):
        os.environ["APP_ENV"] = "production"
        self.assertTrue(pushes_enabled())

    def test_pushes_enabled_false_in_develop(self):
        os.environ["APP_ENV"] = "develop"
        self.assertFalse(pushes_enabled())


if __name__ == "__main__":
    unittest.main()
