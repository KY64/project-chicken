# Website Monitor RSS Feed System

A Python-based website monitoring system that scrapes articles and broadcasts them as RSS feeds using GitHub's native Atom feeds.

## Architecture

The system monitors websites for new articles and publishes them as empty commits on orphan branches. GitHub automatically generates Atom feeds for these branches, providing RSS functionality without manual XML generation.

### Key Components

- **State Management:** CSV files track seen URLs; `site.csv` on `main` branch defines sites
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
│   ├── scraper.py         # Scraping logic
│   ├── git_operations.py  # Git operations
│   └── state_manager.py   # State management
├── state/
│   └── cert-pl.csv        # Seen-URL state for CERT.pl
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

2. Run in develop mode (commits locally, no push):
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

## Configuration

### Adding a New Site

Edit `site.csv` and add a new line:
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

### Adding a New Scraper

1. Create a new subclass of `BaseScraper` in `src/scraper.py`
2. Implement the `extract_articles()` method
3. Add the scraper to `get_scraper_for_url()` function

## How It Works

1. Load site configuration from `site.csv`
2. For each site:
   - Load seen URLs from its state CSV
   - Run site-specific scraper with retry logic
   - For initial run (empty state CSV): scrape first 3 pages max
   - For subsequent runs: scrape all pages
   - Filter articles against known URLs
   - For each new article:
     - Checkout/create orphan branch
     - Create empty commit with title and URL
     - Push branch to origin (production only)
   - Update state CSV with new URLs
3. Switch back to main branch
4. Commit and push updated state CSV files (production only)

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
