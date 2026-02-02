"""Website email scraper module."""

import re
import asyncio
import random
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
import httpx
from bs4 import BeautifulSoup
from datetime import datetime

from app.core.config import settings
from app.modules.verifier import verifier, JUNK_PATTERNS


@dataclass
class ScrapedEmail:
    """Scraped email with metadata."""
    email: str
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    source_url: str = ""


@dataclass
class ScrapeResult:
    """Result from scraping a domain."""
    domain: str
    success: bool
    pages_crawled: int
    emails_found: int
    emails: List[ScrapedEmail] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Keywords for contact pages
CONTACT_KEYWORDS = [
    'contact', 'about', 'team', 'staff', 'people', 'leadership',
    'our-team', 'meet-the-team', 'about-us', 'who-we-are', 'company',
    'management', 'executives', 'directory', 'employees', 'our-people'
]

# Phone pattern
PHONE_PATTERN = re.compile(
    r'(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}'
)

# Email pattern
EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
)

# Role/title patterns
ROLE_PATTERNS = [
    r'CEO|Chief Executive Officer',
    r'CFO|Chief Financial Officer',
    r'CTO|Chief Technology Officer',
    r'COO|Chief Operating Officer',
    r'CMO|Chief Marketing Officer',
    r'President|Vice President|VP',
    r'Director|Manager|Head of',
    r'Partner|Principal|Owner',
    r'Founder|Co-Founder',
    r'Attorney|Lawyer|Counsel',
    r'Doctor|Dr\.|MD|Physician',
    r'Accountant|CPA',
    r'Dentist|DDS|DMD',
    r'Agent|Broker|Realtor',
    r'Technician|Specialist',
]

# Name patterns (simple heuristic)
NAME_PATTERN = re.compile(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)')


class WebScraper:
    """Website email scraper."""

    def __init__(self):
        self.rate_limiters: Dict[str, float] = {}  # domain -> last request time

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with random user agent."""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    async def _rate_limit(self, domain: str):
        """Enforce rate limiting per domain."""
        last_request = self.rate_limiters.get(domain, 0)
        elapsed = asyncio.get_event_loop().time() - last_request
        min_interval = 1.0 / settings.SCRAPER_RATE_LIMIT

        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self.rate_limiters[domain] = asyncio.get_event_loop().time()

    async def _fetch_page(
        self, client: httpx.AsyncClient, url: str, domain: str
    ) -> Optional[str]:
        """Fetch a page with rate limiting and error handling."""
        await self._rate_limit(domain)

        try:
            response = await client.get(
                url,
                headers=self._get_headers(),
                timeout=settings.SCRAPER_TIMEOUT,
                follow_redirects=True,
            )
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}")

        return None

    def _extract_emails_from_html(self, html: str, source_url: str) -> List[ScrapedEmail]:
        """Extract emails and metadata from HTML."""
        emails_found: Dict[str, ScrapedEmail] = {}

        soup = BeautifulSoup(html, 'lxml')

        # Remove script and style tags
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()

        # Get all text
        text = soup.get_text(separator=' ')

        # Find emails
        raw_emails = EMAIL_PATTERN.findall(text)

        # Also check mailto links
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('mailto:'):
                email = href.replace('mailto:', '').split('?')[0].strip()
                if email:
                    raw_emails.append(email)

        # Process each email
        for email in raw_emails:
            email = email.lower().strip()

            # Skip if already found
            if email in emails_found:
                continue

            # Skip junk emails
            if self._is_junk_email(email):
                continue

            # Skip if invalid domain extension
            if not re.search(r'\.[a-z]{2,}$', email):
                continue

            scraped = ScrapedEmail(email=email, source_url=source_url)

            # Try to extract metadata from surrounding context
            scraped = self._extract_metadata(soup, text, email, scraped)

            emails_found[email] = scraped

        return list(emails_found.values())

    def _is_junk_email(self, email: str) -> bool:
        """Check if email matches junk patterns."""
        email_lower = email.lower()
        for pattern in JUNK_PATTERNS:
            if re.search(pattern, email_lower):
                return True
        return False

    def _extract_metadata(
        self, soup: BeautifulSoup, text: str, email: str, scraped: ScrapedEmail
    ) -> ScrapedEmail:
        """Extract name, role, phone from surrounding context."""
        # Find elements containing the email
        elements = soup.find_all(string=re.compile(re.escape(email), re.IGNORECASE))

        for element in elements[:3]:  # Check first few occurrences
            # Get parent container
            parent = element.parent
            if parent:
                # Go up a few levels to get more context
                for _ in range(5):
                    if parent.parent:
                        parent = parent.parent
                    else:
                        break

                context = parent.get_text(separator=' ')

                # Extract name
                if not scraped.name:
                    names = NAME_PATTERN.findall(context)
                    for name in names:
                        # Filter out obviously wrong names
                        if len(name) < 50 and len(name.split()) <= 4:
                            scraped.name = name.strip()
                            parts = name.split()
                            if len(parts) >= 2:
                                scraped.first_name = parts[0]
                                scraped.last_name = parts[-1]
                            break

                # Extract role/title
                if not scraped.role:
                    for pattern in ROLE_PATTERNS:
                        match = re.search(pattern, context, re.IGNORECASE)
                        if match:
                            scraped.role = match.group(0)
                            break

                # Extract phone
                if not scraped.phone:
                    phones = PHONE_PATTERN.findall(context)
                    if phones:
                        scraped.phone = phones[0]

        return scraped

    def _find_contact_urls(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find URLs that might contain contact information."""
        urls = set()
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text().lower()

            # Skip external links, anchors, and non-http
            if href.startswith('#') or href.startswith('javascript:'):
                continue

            # Build absolute URL
            full_url = urljoin(base_url, href)
            parsed_url = urlparse(full_url)

            # Must be same domain
            if parsed_url.netloc != base_domain:
                continue

            # Check if URL or link text contains contact keywords
            url_lower = full_url.lower()
            if any(kw in url_lower or kw in text for kw in CONTACT_KEYWORDS):
                urls.add(full_url)

        return list(urls)

    async def scrape_domain(self, domain: str) -> ScrapeResult:
        """Scrape a domain for email addresses."""
        result = ScrapeResult(
            domain=domain,
            success=False,
            pages_crawled=0,
            emails_found=0,
        )

        # Normalize domain
        domain = domain.lower().strip()
        if domain.startswith('http'):
            parsed = urlparse(domain)
            domain = parsed.netloc
            base_url = domain
        else:
            base_url = None

        # Try to resolve URL
        async with httpx.AsyncClient(verify=False) as client:
            # Try HTTPS first, then HTTP
            for scheme in ['https', 'http']:
                url = f"{scheme}://{domain}"
                try:
                    response = await client.head(
                        url,
                        headers=self._get_headers(),
                        timeout=10,
                        follow_redirects=True
                    )
                    if response.status_code < 400:
                        base_url = str(response.url)
                        break
                except:
                    continue

            if not base_url:
                result.errors.append(f"Could not resolve domain: {domain}")
                return result

            # Track visited URLs and found emails
            visited_urls: Set[str] = set()
            all_emails: Dict[str, ScrapedEmail] = {}
            urls_to_visit: List[str] = [base_url]

            # Add common contact page URLs
            for kw in ['contact', 'about', 'team', 'about-us', 'contact-us', 'our-team']:
                urls_to_visit.append(f"{base_url.rstrip('/')}/{kw}")
                urls_to_visit.append(f"{base_url.rstrip('/')}/{kw}/")

            while urls_to_visit and len(visited_urls) < settings.SCRAPER_MAX_PAGES:
                url = urls_to_visit.pop(0)

                # Normalize and check if visited
                url = url.split('#')[0].rstrip('/')
                if url in visited_urls:
                    continue
                visited_urls.add(url)

                # Fetch page
                html = await self._fetch_page(client, url, domain)
                if not html:
                    continue

                result.pages_crawled += 1

                # Parse HTML
                try:
                    soup = BeautifulSoup(html, 'lxml')
                except:
                    continue

                # Extract emails
                emails = self._extract_emails_from_html(html, url)
                for email in emails:
                    if email.email not in all_emails:
                        all_emails[email.email] = email

                # Find more contact URLs (only from first few pages)
                if result.pages_crawled <= 5:
                    new_urls = self._find_contact_urls(soup, url)
                    for new_url in new_urls:
                        if new_url not in visited_urls and new_url not in urls_to_visit:
                            urls_to_visit.append(new_url)

        result.success = True
        result.emails = list(all_emails.values())
        result.emails_found = len(result.emails)

        return result


# Singleton instance
scraper = WebScraper()
