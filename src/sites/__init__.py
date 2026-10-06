"""Per-site scraping specs, one module per site.

Each module in this package handles exactly one site and defines the whole
site-specific surface — how to get the title, the URL, and go to the next
page:

- URL_PREFIXES: tuple of URL prefixes this site handles. When several sites
  match a URL, the longest prefix wins.
- WAIT_SELECTOR: CSS selector browser modes wait for before parsing.
- extract(html, page_url) -> (articles, next_page_url): parse one page of
  HTML into ((title, url) pairs, absolute next-page URL or None).

Everything else (access modes, retries, pagination, CDP wiring) lives in
``scraper.SiteScraper``. When a site's markup changes, edit only that site's
module here.

Site modules must not import ``scraper``: it imports this package to resolve
URLs to site modules.
"""

import importlib
import pkgutil
from typing import List

_REQUIRED_ATTRIBUTES = ('URL_PREFIXES', 'WAIT_SELECTOR', 'extract')


def _load_site_modules() -> List[object]:
    """Import every module in this package and validate the site contract."""
    modules = []
    for info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f'{__name__}.{info.name}')
        missing = [name for name in _REQUIRED_ATTRIBUTES if not hasattr(module, name)]
        if missing:
            raise ImportError(
                f'{__name__}.{info.name} is missing required site attributes: '
                f'{", ".join(missing)}'
            )
        modules.append(module)
    return modules


SITES = _load_site_modules()


def get_site_for_url(url: str):
    """Return the site module with the longest matching URL prefix."""
    best_module = None
    best_length = -1
    for module in SITES:
        for prefix in module.URL_PREFIXES:
            if url.startswith(prefix) and len(prefix) > best_length:
                best_module = module
                best_length = len(prefix)

    if best_module is None:
        raise ValueError(f'No site module available for URL: {url}')
    return best_module
