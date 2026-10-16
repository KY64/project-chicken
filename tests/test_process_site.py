"""Regression tests for the per-site processing order in main.process_site.

The publish loop leaves HEAD on the site's orphan branch, where the state CSV
is not tracked. If the next site loads its state before returning to main,
load_seen_urls silently reads a missing file as "no state", the per-page
seen cutoff never fires, and the run republishes every article. These tests
lock the required order:

    checkout main -> load state -> scrape (cutoff against seen) -> filter -> publish

and check that only unseen articles reach git commits.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main as main_module
from main import process_site


class FakeScraper:
    """Stands in for SiteScraper; records how process_site calls it."""

    def __init__(self, articles):
        self._articles = articles
        self.call_kwargs = None

    def scrape_articles(self, **kwargs):
        self.call_kwargs = kwargs
        # Emulate the real engine's contract: return everything up to and
        # including the first page that overlaps seen state; caller filters.
        return list(self._articles)


SITE_URL = "https://stub.example/news/"
SEEN_URL = "https://stub.example/posts/seen/"
NEW_URL = "https://stub.example/posts/new/"


class ProcessSiteOrderTests(unittest.TestCase):
    """process_site must load state from main and only publish new URLs."""

    def _run(self, seen_urls, scraped_articles):
        """Execute process_site with git, state, and scraping mocked.

        Returns (calls_order, returned_urls, commit_titles).
        """
        order = []
        commit_titles = []
        scraper = FakeScraper(scraped_articles)

        def record(name):
            def inner(*args, **kwargs):
                order.append(name)
            return inner

        fake_git = {
            "checkout_main": record("checkout_main"),
            "checkout_orphan_branch": record("checkout_orphan_branch"),
            "create_empty_commit": lambda title, url: (order.append("create_empty_commit"), commit_titles.append(title)),
            "push_branch": record("push_branch"),
        }
        fake_load = mock.Mock(
            side_effect=lambda path: (order.append("load_seen_urls"), set(seen_urls))[1]
        )
        fake_get_scraper = mock.Mock(
            side_effect=lambda url, mode: (order.append("scrape"), scraper)[1]
        )

        with (
            mock.patch.object(main_module, "checkout_main", fake_git["checkout_main"]),
            mock.patch.object(main_module, "checkout_orphan_branch", fake_git["checkout_orphan_branch"]),
            mock.patch.object(main_module, "create_empty_commit", fake_git["create_empty_commit"]),
            mock.patch.object(main_module, "push_branch", fake_git["push_branch"]),
            mock.patch.object(main_module, "load_seen_urls", fake_load),
            mock.patch.object(main_module, "get_scraper_for_url", fake_get_scraper),
            mock.patch.dict(os.environ, {"APP_ENV": "develop"}),
        ):
            returned = process_site(SITE_URL, "site-stub", "state/stub.csv", "aiohttp")

        return order, returned, commit_titles

    def test_state_is_loaded_after_returning_to_main(self):
        """The site state must be read while on main, before any scraping."""
        articles = [("New post", NEW_URL), ("Seen post", SEEN_URL)]
        order, _, _ = self._run({SEEN_URL}, articles)

        self.assertLess(order.index("checkout_main"), order.index("load_seen_urls"))
        self.assertLess(order.index("load_seen_urls"), order.index("scrape"))

    def test_only_unseen_articles_are_published(self):
        """The overlapping page comes back whole; known URLs must be dropped."""
        articles = [("New post", NEW_URL), ("Seen post", SEEN_URL)]
        order, returned, commit_titles = self._run({SEEN_URL}, articles)

        self.assertEqual(returned, [NEW_URL])
        self.assertEqual(commit_titles, ["New post"])
        self.assertEqual(order.count("create_empty_commit"), 1)

    def test_no_commits_when_everything_already_seen(self):
        """A page fully covered by state publishes nothing."""
        articles = [("Seen post", SEEN_URL)]
        _, returned, commit_titles = self._run({SEEN_URL}, articles)

        self.assertEqual(returned, [])
        self.assertEqual(commit_titles, [])

    def test_empty_state_marks_initial_run_page_cap(self):
        """No state file means the run must cap pages instead of crawling all."""
        articles = [("New post", NEW_URL)]
        scraper = FakeScraper(articles)

        with (
            mock.patch.object(main_module, "checkout_main", mock.Mock()),
            mock.patch.object(main_module, "checkout_orphan_branch", mock.Mock()),
            mock.patch.object(main_module, "create_empty_commit", mock.Mock()),
            mock.patch.object(main_module, "push_branch", mock.Mock()),
            mock.patch.object(main_module, "load_seen_urls", mock.Mock(return_value=set())),
            mock.patch.object(main_module, "get_scraper_for_url", mock.Mock(return_value=scraper)),
            mock.patch.dict(os.environ, {"APP_ENV": "develop"}),
        ):
            returned = process_site(SITE_URL, "site-stub", "state/stub.csv", "aiohttp")

        # First run publishes, and the engine was handed the 3-page cap.
        self.assertEqual(returned, [NEW_URL])
        self.assertEqual(scraper.call_kwargs["max_pages"], 3)

    def test_seen_urls_are_passed_to_the_scraper(self):
        """The engine gets the loaded state so it can stop at the overlap page."""
        articles = [("New post", NEW_URL), ("Seen post", SEEN_URL)]
        scraper = FakeScraper(articles)

        with (
            mock.patch.object(main_module, "checkout_main", mock.Mock()),
            mock.patch.object(main_module, "checkout_orphan_branch", mock.Mock()),
            mock.patch.object(main_module, "create_empty_commit", mock.Mock()),
            mock.patch.object(main_module, "push_branch", mock.Mock()),
            mock.patch.object(main_module, "load_seen_urls", mock.Mock(return_value={SEEN_URL})),
            mock.patch.object(main_module, "get_scraper_for_url", mock.Mock(return_value=scraper)),
            mock.patch.dict(os.environ, {"APP_ENV": "develop"}),
        ):
            process_site(SITE_URL, "site-stub", "state/stub.csv", "aiohttp")

        self.assertEqual(scraper.call_kwargs["seen_urls"], {SEEN_URL})
        self.assertIsNone(scraper.call_kwargs["max_pages"])


if __name__ == "__main__":
    unittest.main()
