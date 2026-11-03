"""Tests for the state CSV writer.

State is the only record of what was published, so the writer must never
record an URL twice. Duplicate rows do not break filtering (the loader builds
a set), but they hide divergence between the feed branches and state, which
is what made the earlier republish incidents hard to read.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_manager import load_seen_urls, save_new_urls


class SaveNewUrlsTests(unittest.TestCase):
    def _path(self, directory: str, name: str = "state.csv") -> str:
        return str(Path(directory) / name)

    def test_creates_file_with_new_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(directory)
            written = save_new_urls(path, ["https://a.example/1", "https://a.example/2"])

            self.assertEqual(written, 2)
            self.assertEqual(
                load_seen_urls(path),
                {"https://a.example/1", "https://a.example/2"},
            )

    def test_writes_nothing_when_all_urls_are_known(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(directory)
            save_new_urls(path, ["https://a.example/1"])
            before = Path(path).read_text()

            written = save_new_urls(path, ["https://a.example/1"])

            self.assertEqual(written, 0)
            self.assertEqual(Path(path).read_text(), before)

    def test_appends_only_unknown_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(directory)
            save_new_urls(path, ["https://a.example/1", "https://a.example/2"])

            written = save_new_urls(path, ["https://a.example/2", "https://a.example/3"])

            self.assertEqual(written, 1)
            self.assertEqual(
                load_seen_urls(path),
                {"https://a.example/1", "https://a.example/2", "https://a.example/3"},
            )
            # Existing rows stay put and the new one lands last.
            rows = Path(path).read_text().split()
            self.assertEqual(
                rows,
                ["https://a.example/1", "https://a.example/2", "https://a.example/3"],
            )

    def test_collapses_repeats_inside_one_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(directory)

            written = save_new_urls(
                path,
                ["https://a.example/1", "https://a.example/1", "https://a.example/2"],
            )

            self.assertEqual(written, 2)
            self.assertEqual(len(Path(path).read_text().split()), 2)

    def test_preserves_existing_rows_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(directory)
            Path(path).write_text("https://a.example/old\n", encoding="utf-8")

            save_new_urls(path, ["https://a.example/new"])

            self.assertEqual(
                Path(path).read_text(),
                "https://a.example/old\nhttps://a.example/new\n",
            )

    def test_creates_missing_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._path(directory, "nested/dir/state.csv")

            written = save_new_urls(path, ["https://a.example/1"])

            self.assertEqual(written, 1)
            self.assertTrue(Path(path).is_file())


if __name__ == "__main__":
    unittest.main()