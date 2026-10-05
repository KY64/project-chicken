import os
import time
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, Browser, Page


MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


class BaseScraper(ABC):
    """Abstract base class for website scrapers."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.cdp_endpoint = os.getenv('PLAYWRIGHT_CDP_ENDPOINT')
        self.use_cdp = bool(self.cdp_endpoint)
    
    @abstractmethod
    def extract_articles(self, page: Page) -> List[Tuple[str, str]]:
        """
        Extract articles from the page.
        
        Args:
            page: Playwright Page object
            
        Returns:
            List of (title, url) tuples
        """
        pass
    
    def scrape_articles(self, max_pages: Optional[int] = None) -> List[Tuple[str, str]]:
        """
        Scrape articles from the website with retry logic.
        
        Args:
            max_pages: Maximum number of pages to scrape (None for all pages)
            
        Returns:
            List of (title, url) tuples
        """
        for attempt in range(MAX_RETRIES):
            try:
                return self._scrape_articles_internal(max_pages)
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                delay = BASE_DELAY * (2 ** attempt)
                print(f"Scraping failed (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {delay}s: {e}")
                time.sleep(delay)
        
        return []
    
    def _scrape_articles_internal(self, max_pages: Optional[int] = None) -> List[Tuple[str, str]]:
        """Internal scraping method without retry logic."""
        articles = []
        page_num = 1
        
        with sync_playwright() as p:
            if self.use_cdp:
                # Connect to CDP endpoint
                browser = p.chromium.connect_over_cdp(self.cdp_endpoint)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
            else:
                # Use local browser
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
            
            try:
                while True:
                    # Navigate to the page
                    if page_num == 1:
                        page.goto(self.base_url)
                    else:
                        page.goto(f"{self.base_url}{page_num}/")
                    
                    # Wait for page to load
                    page.wait_for_load_state('networkidle')
                    
                    # Extract articles
                    page_articles = self.extract_articles(page)
                    articles.extend(page_articles)
                    
                    # Check if we should continue
                    if max_pages is not None and page_num >= max_pages:
                        break
                    
                    # Check if there's a next page
                    next_button = page.query_selector('a:has-text("»")')
                    if not next_button:
                        break
                    
                    page_num += 1
                    time.sleep(1)  # Be polite to the server
                    
            finally:
                browser.close()
        
        return articles


class CertPlScraper(BaseScraper):
    """Scraper for CERT.pl news page."""
    
    def extract_articles(self, page: Page) -> List[Tuple[str, str]]:
        """
        Extract articles from CERT.pl news page.
        
        Args:
            page: Playwright Page object
            
        Returns:
            List of (title, url) tuples
        """
        articles = []
        
        # Find all article cards
        article_elements = page.query_selector_all('div:has(h4)')
        
        for element in article_elements:
            try:
                # Get the title from the h4 element
                title_element = element.query_selector('h4')
                if not title_element:
                    continue
                
                title = title_element.inner_text().strip()
                
                # Get the "Read more" link
                link_element = element.query_selector('a:has-text("Read more")')
                if not link_element:
                    continue
                
                relative_url = link_element.get_attribute('href')
                if not relative_url:
                    continue
                
                # Construct full URL
                full_url = urljoin(self.base_url, relative_url)
                
                articles.append((title, full_url))
            except Exception as e:
                # Skip this article if extraction fails
                continue
        
        return articles


def get_scraper_for_url(url: str) -> BaseScraper:
    """
    Get the appropriate scraper for a given URL.
    
    Args:
        url: URL to scrape
        
    Returns:
        Scraper instance
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    if 'cert.pl' in domain:
        return CertPlScraper(url)
    else:
        raise ValueError(f"No scraper available for domain: {domain}")
