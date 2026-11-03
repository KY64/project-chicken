import csv
import os
import sys
from typing import List, Tuple

from git_operations import (
    configure_git,
    checkout_orphan_branch,
    push_branch,
    checkout_main,
    commit_changes,
    create_empty_commit,
    push_main,
    get_app_env
)
from state_manager import load_seen_urls, save_new_urls
from scraper import ACCESS_MODES, get_scraper_for_url


def load_site_config(csv_path: str) -> List[Tuple[str, str, str, str]]:
    """Load and validate site configuration from CSV file."""
    sites = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        for columns in reader:
            if not columns or not any(column.strip() for column in columns):
                continue
            if len(columns) != 4:
                raise ValueError(
                    f"{csv_path}:{reader.line_num}: expected 4 columns "
                    "(url, branch, state CSV, access mode)"
                )

            url, branch_name, state_csv, access_mode = (column.strip() for column in columns)
            if access_mode not in ACCESS_MODES:
                allowed = ', '.join(sorted(ACCESS_MODES))
                raise ValueError(
                    f"{csv_path}:{reader.line_num}: unknown access mode "
                    f"{access_mode!r}; expected one of: {allowed}"
                )
            sites.append((url, branch_name, state_csv, access_mode))

    return sites


def process_site(url: str, branch_name: str, state_csv: str, access_mode: str) -> List[str]:
    """
    Process a single site: scrape articles and publish new ones.

    Args:
        url: Site URL to scrape
        branch_name: Orphan branch name for this site
        state_csv: Path to CSV file tracking seen URLs

    Returns:
        URLs of newly published articles. The caller records them in the
        state CSV, which requires main to be checked out first.
    """
    print(f"Processing site: {url} (access_mode={access_mode})")

    # State files are tracked on main, but publishing leaves the run on the
    # site's orphan branch. Without returning first, every site after the
    # first publisher reads an empty state file and republishes everything.
    checkout_main()

    # Load seen URLs
    seen_urls = load_seen_urls(state_csv)
    if seen_urls:
        print(f"  Loaded {len(seen_urls)} seen URLs from {state_csv}")
    else:
        print(f"  No saved state in {state_csv}: initial run, capped at 3 pages")

    # Get scraper
    scraper = get_scraper_for_url(url, access_mode)

    # Determine if this is initial run
    is_initial_run = len(seen_urls) == 0
    max_pages = 3 if is_initial_run else None

    print(f"  Scraping articles (max_pages={max_pages})")

    # Pages are newest-first, so stop after the first page overlapping saved
    # state. The scraper returns that page too; filter known articles below.
    # Dedupe within the batch in case a scraper yields the same URL more than once.
    articles = scraper.scrape_articles(max_pages=max_pages, seen_urls=seen_urls)
    articles = list({article_url: (title, article_url) for title, article_url in articles}.values())
    print(f"  Found {len(articles)} unique articles")

    # Filter new articles
    new_articles = [(title, url) for title, url in articles if url not in seen_urls]
    print(f"  Found {len(new_articles)} new articles")

    # Publish oldest first: pages are scraped newest-first, and each new
    # commit lands on top of the orphan branch, so reversing the batch leaves
    # the newest article as the tip the Atom feed serves first
    new_urls = []
    for title, article_url in reversed(new_articles):
        print(f"    Publishing: {title}")

        # Checkout/create orphan branch
        checkout_orphan_branch(branch_name)

        # Create empty commit
        create_empty_commit(title, article_url)

        # Push branch
        push_branch(branch_name)

        new_urls.append(article_url)

    # The state file is tracked on main and must not be written here: the
    # run is currently on the orphan branch, where the file would be
    # untracked and lost when switching back
    return new_urls


def main() -> None:
    """Main orchestration function."""
    # Configure git
    configure_git()

    # Validate APP_ENV early to fail-fast before doing work
    app_env = get_app_env()
    print(f"APP_ENV={app_env}")

    # Load site configuration
    site_csv = 'site.csv'
    if not os.path.exists(site_csv):
        sys.exit(f"Error: {site_csv} not found")

    sites = load_site_config(site_csv)
    print(f"Loaded {len(sites)} sites to monitor")

    # State files live on main. Every read and every write of a state CSV
    # must happen with main checked out: on a site's orphan branch the file
    # does not exist, so the read sees "no state" and the write is discarded
    # when the run switches back. Both regressions shipped once (0782d27 read
    # side, 407f11c write side) and both caused full republishes.
    for url, branch_name, state_csv, access_mode in sites:
        try:
            new_urls = process_site(url, branch_name, state_csv, access_mode)
        except Exception as e:
            print(f"Error processing site {url}: {e}")
            continue
        if not new_urls:
            continue

        # Record as soon as this site is done. Publishing pushed commits to
        # the feed branch already, so a failure in a later site (or a killed
        # runner) must not leave these URLs unrecorded: the next run would
        # republish them onto the same branch. Failures here are logged
        # separately — the site itself succeeded — and the final push retries.
        try:
            checkout_main()
            written = save_new_urls(state_csv, new_urls)
            if not written:
                print(f"  No new URLs to record for {branch_name}")
                continue

            print(f"  Recorded {written} new URLs in {state_csv}")
            commit_changes(f"Update seen URLs ({branch_name})", [state_csv])
            push_main()
        except Exception as e:
            print(f"Error recording state for {branch_name}: {e}")
            continue

    # Switch back to main; nothing is written off main, so the branch state
    # here is just where the run ends.
    print("Switching back to main branch")
    checkout_main()

    # Safety net for a per-site push that lost a race or hit a transient
    # error: the commit is local, so pushing again lands it. No-op otherwise.
    push_main()

    print("Done!")


if __name__ == '__main__':
    main()
