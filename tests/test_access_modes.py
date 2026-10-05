import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import load_site_config
from scraper import ACCESS_MODES, CertPlScraper, get_scraper_for_url
from git_operations import get_app_env, pushes_enabled


class AccessModeTests(unittest.TestCase):
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

    def test_factory_accepts_each_access_mode(self):
        for access_mode in ACCESS_MODES:
            with self.subTest(access_mode=access_mode):
                scraper = get_scraper_for_url("https://cert.pl/en/news/", access_mode)
                self.assertEqual(scraper.access_mode, access_mode)

    def test_aiohttp_parser_extracts_cards_and_next_page(self):
        html = """
            <ul class="horizontal-post-list">
              <li><a class="post-outer-container" href="../../posts/2026/01/example/">
                <h4> Example &amp; Analysis </h4>
              </a></li>
            </ul>
            <a href="3/">»</a>
        """
        scraper = get_scraper_for_url("https://cert.pl/en/news/", "aiohttp")

        articles, has_next_page = scraper.extract_articles_from_html(
            html,
            "https://cert.pl/en/news/2/",
        )

        self.assertEqual(
            articles,
            [("Example & Analysis", "https://cert.pl/en/posts/2026/01/example/")],
        )
        self.assertTrue(has_next_page)


class PaginationTests(unittest.TestCase):
    def test_aiohttp_stops_after_page_overlaps_seen_urls(self):
        page_urls = []
        first_page = """
            <ul class="horizontal-post-list">
              <li><a class="post-outer-container" href="/en/posts/new/"><h4>New</h4></a></li>
              <li><a class="post-outer-container" href="/en/posts/seen/"><h4>Seen</h4></a></li>
            </ul>
            <a href="2/">»</a>
        """
        older_page = """
            <ul class="horizontal-post-list">
              <li><a class="post-outer-container" href="/en/posts/older/"><h4>Older</h4></a></li>
            </ul>
        """

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                page_urls.append(self.path)
                body = first_page if self.path == "/en/news/" else older_page
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        seen_url = f"http://127.0.0.1:{server.server_port}/en/posts/seen/"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}/en/news/"
            scraper = CertPlScraper(base_url, "aiohttp")

            articles = scraper.scrape_articles(seen_urls={seen_url})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(page_urls, ["/en/news/"])
        self.assertEqual(
            [article for article in articles if article[1] != seen_url],
            [("New", seen_url.replace("/seen/", "/new/"))],
        )
        self.assertIn(("Seen", seen_url), articles)


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