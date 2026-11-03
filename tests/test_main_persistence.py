"""Regression tests for main()'s per-site state persistence.

Publishing pushes commits to a site's orphan branch immediately, but state is
recorded on main. If the run records state only after every site has finished,
one failing site (or a killed runner) leaves the successful sites' URLs
unrecorded, and the next run republishes them onto the same feed branch.

These tests pin the ordering that prevents that:

    process site -> checkout main -> save state -> commit -> push

and assert that a later site failing cannot discard an earlier site's record.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main as main_module

SITES = [
    ("https://a.example/", "site-a", "state/a.csv", "aiohttp"),
    ("https://b.example/", "site-b", "state/b.csv", "aiohttp"),
    ("https://c.example/", "site-c", "state/c.csv", "aiohttp"),
]


class MainPersistenceTests(unittest.TestCase):
    def _run_main(self, results, save_return=None):
        """Run main() with git, config, and scraping mocked.

        `results` maps site URL to the URL list process_site returns, or to an
        Exception instance it should raise. `save_return` optionally overrides
        what save_new_urls reports as written (default: len(urls)).
        """
        order = []
        saved = []
        committed = []

        def fake_process(url, branch_name, state_csv, access_mode):
            order.append(("process", branch_name))
            outcome = results[url]
            if isinstance(outcome, Exception):
                raise outcome
            return list(outcome)

        def fake_save(csv_path, urls):
            order.append(("save", csv_path))
            saved.append((csv_path, list(urls)))
            return len(urls) if save_return is None else save_return

        def fake_commit(message, paths):
            order.append(("commit", tuple(paths)))
            committed.append((message, tuple(paths)))

        def fake_checkout_main():
            order.append(("checkout_main",))

        def fake_push_main():
            order.append(("push_main",))

        with (
            mock.patch.object(main_module, "configure_git", mock.Mock()),
            mock.patch.object(main_module, "get_app_env", mock.Mock(return_value="develop")),
            mock.patch.object(main_module, "load_site_config", mock.Mock(return_value=SITES)),
            mock.patch.object(main_module.os.path, "exists", mock.Mock(return_value=True)),
            mock.patch.object(main_module, "process_site", side_effect=fake_process),
            mock.patch.object(main_module, "save_new_urls", side_effect=fake_save),
            mock.patch.object(main_module, "commit_changes", side_effect=fake_commit),
            mock.patch.object(main_module, "checkout_main", side_effect=fake_checkout_main),
            mock.patch.object(main_module, "push_main", side_effect=fake_push_main),
        ):
            main_module.main()

        return order, saved, committed

    def test_records_state_per_site_after_returning_to_main(self):
        order, saved, committed = self._run_main(
            {
                "https://a.example/": ["https://a.example/1"],
                "https://b.example/": [],
                "https://c.example/": [],
            }
        )

        self.assertEqual([path for path, _ in saved], ["state/a.csv"])
        self.assertIn("site-a", committed[0][0])

        # The write must happen with main checked out, between the site's
        # publish and the site's state commit.
        publish_at = order.index(("process", "site-a"))
        checkout_at = order.index(("checkout_main",))
        save_at = order.index(("save", "state/a.csv"))
        commit_at = order.index(("commit", ("state/a.csv",)))
        self.assertLess(publish_at, checkout_at)
        self.assertLess(checkout_at, save_at)
        self.assertLess(save_at, commit_at)

    def test_later_site_failure_keeps_earlier_records(self):
        order, saved, committed = self._run_main(
            {
                "https://a.example/": ["https://a.example/1"],
                "https://b.example/": RuntimeError("scrape failed"),
                "https://c.example/": ["https://c.example/1"],
            }
        )

        # Site b failed, but a and c were still recorded — the whole point.
        self.assertEqual(
            [path for path, _ in saved],
            ["state/a.csv", "state/c.csv"],
        )
        self.assertEqual(
            [paths for _, paths in committed],
            [("state/a.csv",), ("state/c.csv",)],
        )
        self.assertIn(("process", "site-b"), order)

    def test_skips_commit_when_nothing_new_was_recorded(self):
        order, saved, committed = self._run_main(
            {
                "https://a.example/": ["https://a.example/1"],
                "https://b.example/": [],
                "https://c.example/": [],
            },
            save_return=0,
        )

        self.assertEqual(len(saved), 1)      # the writer was consulted
        self.assertEqual(committed, [])        # but nothing changed -> no commit
        self.assertNotIn(("commit", ("state/a.csv",)), order)

    def test_no_state_write_for_sites_without_new_articles(self):
        _, saved, committed = self._run_main(
            {
                "https://a.example/": [],
                "https://b.example/": [],
                "https://c.example/": [],
            }
        )

        self.assertEqual(saved, [])
        self.assertEqual(committed, [])

    def test_final_push_always_attempted(self):
        order, _, _ = self._run_main(
            {
                "https://a.example/": ["https://a.example/1"],
                "https://b.example/": [],
                "https://c.example/": [],
            }
        )

        # Per-site push plus the end-of-run safety net.
        self.assertEqual(order.count(("push_main",)), 2)
        self.assertEqual(order[-1], ("push_main",))


if __name__ == "__main__":
    unittest.main()