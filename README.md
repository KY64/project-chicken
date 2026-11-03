# Website Monitor RSS Feed System

Well, no chickens here, mate. Just a metaphor.

This just some tricks for monitoring website by scraping articles and broadcasts them as RSS feeds using GitHub's native Atom feeds.

## Architecture

The system monitors websites for new articles and publishes them as empty commits on orphan branches. GitHub automatically generates Atom feeds for these branches, providing RSS functionality without manual XML generation.

### Key Components

- **State Management:** CSV files track seen URLs — one row per URL, appended only when the URL is not already there; recorded on `main` right after each site publishes; `site.csv` on `main` branch defines sites
- **RSS Generation:** Leverages GitHub's native Atom feeds from orphan branches
- **Feed Items:** New articles published as empty commits (header = title, body = URL)
- **Scraping:** Per-site access mode selects browser (JS enabled), browser (JS disabled), or direct `aiohttp`; browser modes use Browserless CDP in production and local Chromium for testing
- **Error Handling:** Retry with exponential backoff on failures
- **Initial Run:** Publishes first 3 pages of articles max (to avoid flooding feed)

## Project Structure

```
project-chicken/
├── .github/
│   └── workflows/
│       └── monitor.yml    # GitHub Actions workflow
├── src/
│   ├── __init__.py
│   ├── main.py            # Entry point
│   ├── scraper.py         # Shared scraping engine (access modes, retries, pagination)
│   ├── sites/             # One module per site: title, URL, next-page extraction
│   │   ├── __init__.py    # Site registry (URL prefix matching)
│   │   └── <site>.py      # Site-specific extraction contract
│   ├── git_operations.py  # Git operations
│   └── state_manager.py   # State management
├── state/                 # Per-site seen-URL CSV files
├── site.csv               # Site configuration
├── requirements.txt       # Python dependencies
└── README.md
```

## Setup

### GitHub Actions (Production)

1. Fork or create a repository
2. Add `PLAYWRIGHT_CDP_ENDPOINT` to repository secrets
3. Push the code to the repository
4. The workflow runs automatically every 2 days

### Local Testing

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. Run in develop mode (commits locally, no push — see
   [Development vs production behavior](#development-vs-production-behavior)):
   ```bash
   APP_ENV=develop python src/main.py
   ```

3. Run in production mode (commits and pushes):
   ```bash
   APP_ENV=production python src/main.py
   ```

4. Run with CDP endpoint:
   ```bash
   APP_ENV=production PLAYWRIGHT_CDP_ENDPOINT=your_endpoint python src/main.py
   ```

### Local Browser via Container (Browserless)

Browser modes can run against a Browserless container instead of a local
Chromium install. The scraper connects to it through the usual CDP endpoint.

1. Start the container (self-chosen token, no account needed):

   ```bash
   podman run -d --name browserless \
     -p 9222:3000 \
     -e TOKEN=local-chicken-token \
     -e TIMEOUT=300000 \
     --shm-size=2g \
     ghcr.io/browserless/chromium
   ```

   `docker run` works the same way. `--shm-size=2g` is required (the default
   64 MB shared memory crashes Chromium under load).

2. Run with the container as the CDP endpoint:

   ```bash
   APP_ENV=develop \
     PLAYWRIGHT_CDP_ENDPOINT="ws://127.0.0.1:9222/chromium?token=local-chicken-token" \
     python src/main.py
   ```

Verified gotchas:

- Use `127.0.0.1`, not `localhost`: if `localhost` resolves to IPv6 `::1`,
  podman's user-space networking resets the connection.
- Do not set `TIMEOUT=-1` (documented as "disable timeout"): this build closes
  the WebSocket handshake with `408` immediately. Use a large positive
  millisecond value instead (the scraper's page timeout is 45 s, so anything
  above that is fine).
- The container's Chromium cannot reach services on the host's `127.0.0.1`
  (its localhost is its own). For local test servers use
  `host.containers.internal` in the target URL.

Both `browser` and `browser_no_js` modes are verified working end-to-end
through this container for sites compatible with plain Chromium. The local
container does not provide a Stealth route (it returns 404), so Cloudflare-
protected `browser` feeds should use Browserless Stealth in production by
setting `PLAYWRIGHT_CDP_ENDPOINT` to `/stealth` or `/chromium/stealth`.

## Development vs production behavior

`APP_ENV` decides whether the run publishes to GitHub or only on this machine.
Everything else — scraping, filtering, per-site state recording, the 3-page
initial-run cap — is identical in both modes.

| Aspect | `develop` | `production` |
| --- | --- | --- |
| git network access | none: never pulls, never `ls-remote`s | pulls `main`, `ls-remote`s branches missing locally |
| feed branch checkout | existing local branch is reused; otherwise a **new empty orphan** is created | branch missing locally but present on origin is checked out and pulled, keeping its remote history |
| feed branch push | skipped | `git push --force origin <branch>` after every article commit |
| state CSV | committed locally after each site | committed and pushed after each site |
| `main` push | skipped | after each site, plus one final safety push |
| browser modes | local Chromium unless `PLAYWRIGHT_CDP_ENDPOINT` is set | `PLAYWRIGHT_CDP_ENDPOINT` expected (no local Chromium on the runner) |
| commit identity | `github-actions[bot]` unless `GIT_USER_NAME`/`GIT_USER_EMAIL` are set | same |

### What that means when running `develop`

1. **Publishing still rewrites the working tree.** Publishing checks out the
   site's orphan branch and clears it, so uncommitted changes to *tracked*
   files are reverted when the run returns to `main`. Untracked files such as
   `.env` survive. Commit or stash before starting a run.
2. **You push the results yourself**, and only what you choose:
   ```bash
   git push origin main site-<site-name>
   ```
   The feed branch is new locally, so the first push creates it on origin.
3. **A develop-created orphan has no shared history with origin.** If a site's
   branch already exists on GitHub, `develop` does not look it up (no network);
   it creates a fresh orphan. Force-pushing that replaces the remote history,
   and the dropped entries do not come back: their URLs stay recorded in state,
   so they are never republished (see
   [State guarantees and limits](#state-guarantees-and-limits)). To keep remote
   history, fetch the branch first so it exists locally before running:
   ```bash
   git fetch origin site-<site-name>
   ```
4. **Local `main` can be behind origin.** `develop` never pulls, so if the
   scheduled run committed state since your clone, push with
   `git pull --rebase origin main` first, otherwise the push is rejected.
5. **Commit identity is the bot by default.** `configure_git()` writes the bot
   identity into this repository's config unless `GIT_USER_NAME` and
   `GIT_USER_EMAIL` are set, so local commits and state commits look like
   automated ones.

## Configuration

### Adding a New Site

Adding a site takes two pieces, and when the site's markup later changes,
only the site module needs editing.

1. Create one module for the site under `src/sites/` (see
   `src/sites/cert_pl.py` or `src/sites/safedep.py` for examples). It
   defines the whole site-specific surface — how to get the title, the URL,
   and go to the next page:

   - `URL_PREFIXES`: tuple of URL prefixes this site handles (the longest
     matching prefix wins when resolving a URL to a site)
   - `WAIT_SELECTOR`: CSS selector browser modes wait for before parsing
   - `extract(html, page_url) -> (articles, next_page_url)`: parse one
     page into `(title, url)` pairs plus the absolute next-page URL
     (or `None` at the last page)

   Everything else — access modes, retries, the seen-URL pagination cutoff,
   CDP wiring — lives in the shared engine (`src/scraper.py`).

2. Add a row to `site.csv`:
```
https://example.com/news/,site-example-com,state/example-com.csv,browser
```

The CSV format is:
- Column 1: Site URL
- Column 2: Orphan branch name (domain-based naming recommended)
- Column 3: State CSV path, relative to the repository root (store per-site files under `state/`; domain-based naming recommended)
- Column 4: Access mode: `browser`, `browser_no_js`, or `aiohttp`

Browser modes use Browserless CDP when `PLAYWRIGHT_CDP_ENDPOINT` is set,
and local headless Chromium otherwise. The selected access mode is
independent of which browser backend is used.

## How It Works

1. Load site configuration from `site.csv`
2. For each site:
   - Return to `main` first, then load seen URLs from its state CSV
     (publishing leaves HEAD on an orphan branch where state is not tracked;
     loading there would read "no state" and republish everything)
   - Run site-specific scraper with retry logic
   - For initial run (no state CSV yet): scrape first 3 pages max
   - For subsequent runs: after each page, check its URLs against the saved
     state — on the first page that overlaps, stop (articles are newest-first,
     so older pages hold only already-published items); known URLs from that
     page are filtered out before publishing
   - Filter articles against known URLs
   - For each new article:
     - Checkout/create orphan branch
     - Create empty commit with title and URL
     - Push branch to origin (production only)
   - Return to `main`, record the newly published URLs in the state CSV, then
     commit and push it (production only) — **always before moving on to the
     next site**, not once at the end: the feed commits are already pushed by
     this point, so a later site failing, or the runner dying, must not leave
     them unrecorded, or the next run republishes them onto the same branch.
     If this commit or push fails it is logged separately (the site itself
     succeeded) and the remaining sites still run.
3. Switch back to `main` and push it once more as a safety net; pushing an
   already-pushed `main` is a no-op.

## State guarantees and limits

`state/*.csv` is the only input to the "already published?" decision. The
pipeline never reads a feed branch's history to decide what to publish, and it
keeps no state between runs — every run is a new process that reads these
files back from `main`.

What state guarantees:

- A URL recorded in a state file is not published again, whatever happens to
  its feed branch.
- Appends are a union against the file, so a state file holds one row per URL.
  A repeated append is a no-op and creates no commit.
- Dedupe is **per file**. The same article can legitimately be recorded by two
  sites (for example a post listed in both a malware and a security category),
  and each feed publishes it once.

What state does not guarantee:

- **Losing or rolling back a state file makes those URLs look new again**, so
  they get republished and the feed shows duplicates. This is why state is
  committed and pushed after every site rather than once at the end.
- **A feed branch does not heal itself.** If a branch is recreated (a fresh
  orphan, or a force-push that replaces its history) it only shows items
  published after that point: the older entries still exist in state, so they
  are suppressed from republishing and never come back on their own.
- **The feed reflects the upstream listing, not a backfill.** If an upstream
  page still lists an article whose URL is already in state, the run finds zero
  new articles for that site — which is the expected result, not a failure.

## RSS Feed Access

After the workflow runs, access the RSS feed at:
```
https://github.com/USERNAME/REPO/commits/BRANCH.atom
```

For example, for CERT.pl:
```
https://github.com/USERNAME/REPO/commits/site-cert-pl.atom
```

## Environment Variables

- `APP_ENV`: Environment mode, must be `develop` or `production` (required)
  - `develop`: commits locally only, does not push to origin
  - `production`: commits and pushes to origin
  - See [Development vs production behavior](#development-vs-production-behavior)
    for the full difference, including what `develop` does to the working tree
- `PLAYWRIGHT_CDP_ENDPOINT`: Playwright CDP endpoint URL (required for production, optional for local testing)
- `GIT_USER_NAME`: Git user name (optional, defaults to github-actions[bot])
- `GIT_USER_EMAIL`: Git user email (optional, defaults to github-actions[bot] email)

## Design Decisions

1. **CDP API Provider:** Generic Playwright CDP endpoint (configured via `PLAYWRIGHT_CDP_ENDPOINT` env var) for production; fallback to local Chromium for local testing
2. **Error Recovery:** Retry with exponential backoff (max 3 retries)
3. **Initial Run Behavior:** Publish first 3 pages of articles max (to avoid flooding feed)
4. **Branch Naming:** Domain-based (e.g., `site-cert-pl` from URL)
5. **Git Configuration:** Use GitHub Actions bot identity by default; custom identity optional via env vars
6. **State CSV Naming:** Simple domain-based naming under `state/` (e.g., `state/cert-pl.csv` for seen URLs)
7. **Browser Installation:** GitHub Actions uses CDP endpoint (no local Chromium); local testing requires `playwright install chromium`
8. **Environment Modes:** `APP_ENV` gates push behavior; fail-fast if unset to prevent accidental publishes
9. **Seen-URL Cutoff:** pagination stops at the first page overlapping saved state (articles are newest-first), so each run fetches only as far back as needed; the overlapping page is kept and its known URLs filtered out before publishing
10. **State Reads And Writes On Main:** every state read and write happens with `main` checked out, because orphan branches do not track `state/` — reading there sees "no state" and writing there is discarded, and both regressions caused full republishes once
11. **Per-Site State Recording:** new URLs are committed and pushed immediately after their site publishes, always before the next site starts, so a failure only ever loses the site in flight, never the whole run
12. **Idempotent State Appends:** `save_new_urls` skips URLs already in the file, so a state file holds one row per URL and a divergence between branches and state cannot hide in duplicated rows
13. **Serialized Runs:** the workflow's `concurrency` group allows one monitor run at a time; overlapping runs would read the same state and both publish and append the same articles
14. **State Is Authoritative:** no run consults feed-branch history to decide what was published, so the CSV files stay the single source of truth; the cost is that a recreated branch shows only items published after it existed (see [State guarantees and limits](#state-guarantees-and-limits))

## License

This project is licensed under the GNU General Public License v3.0 only
([LICENSE](LICENSE)).
