"""Email verification module - no paid APIs, built from scratch."""

import re
import dns.resolver
import asyncio
import aiosmtplib
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass
class VerificationResult:
    """Email verification result."""
    email: str
    status: str  # valid, invalid, unknown, risky
    confidence: float
    is_catch_all: bool
    is_free_provider: bool
    mx_record: Optional[str]
    smtp_response: Optional[str]
    details: Dict[str, Any]


# Free email providers
FREE_PROVIDERS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com',
    'icloud.com', 'mail.com', 'protonmail.com', 'zoho.com', 'yandex.com',
    'gmx.com', 'live.com', 'msn.com', 'me.com', 'mac.com', 'fastmail.com',
    'tutanota.com', 'hushmail.com', 'inbox.com', 'mail.ru', 'qq.com',
    '163.com', '126.com', 'yeah.net', 'sina.com', 'sohu.com'
}

# Junk/platform emails to filter out
JUNK_PATTERNS = [
    r'noreply', r'no-reply', r'donotreply', r'do-not-reply',
    r'mailer-daemon', r'postmaster', r'webmaster', r'hostmaster',
    r'@sentry\.io', r'@wixpress\.com', r'@wordpress\.com',
    r'@mailchimp\.com', r'@sendgrid\.', r'@amazonaws\.com',
    r'\.png$', r'\.jpg$', r'\.gif$', r'\.jpeg$', r'\.webp$',
    r'example\.com', r'test\.com', r'domain\.com', r'email\.com',
    r'@localhost', r'@127\.0\.0\.1'
]

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]


class EmailVerifier:
    """Email verification engine."""

    def __init__(self):
        self.disposable_domains: set = set()
        self._dns_cache: Dict[str, Tuple[List[str], datetime]] = {}
        self._semaphore = asyncio.Semaphore(settings.VERIFIER_MAX_CONCURRENT)

    async def load_disposable_domains(self):
        """Load disposable email domains list."""
        import httpx
        url = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30)
                if response.status_code == 200:
                    self.disposable_domains = set(
                        line.strip().lower()
                        for line in response.text.split('\n')
                        if line.strip() and not line.startswith('#')
                    )
                    print(f"Loaded {len(self.disposable_domains)} disposable domains")
        except Exception as e:
            print(f"Failed to load disposable domains: {e}")
            # Use a small fallback list
            self.disposable_domains = {
                'tempmail.com', 'throwaway.email', 'guerrillamail.com',
                'mailinator.com', '10minutemail.com', 'temp-mail.org'
            }

    def is_valid_syntax(self, email: str) -> bool:
        """Check if email has valid syntax."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email.lower()))

    def is_junk_email(self, email: str) -> bool:
        """Check if email matches junk patterns."""
        email_lower = email.lower()
        for pattern in JUNK_PATTERNS:
            if re.search(pattern, email_lower):
                return True
        return False

    def is_disposable(self, domain: str) -> bool:
        """Check if domain is disposable."""
        return domain.lower() in self.disposable_domains

    def is_free_provider(self, domain: str) -> bool:
        """Check if domain is a free email provider."""
        return domain.lower() in FREE_PROVIDERS

    async def get_mx_records(self, domain: str) -> List[str]:
        """Get MX records for domain with caching."""
        # Check cache
        if domain in self._dns_cache:
            records, cached_at = self._dns_cache[domain]
            if datetime.utcnow() - cached_at < timedelta(hours=1):
                return records

        try:
            loop = asyncio.get_event_loop()
            answers = await loop.run_in_executor(
                None,
                lambda: dns.resolver.resolve(domain, 'MX')
            )
            records = sorted(
                [(r.preference, str(r.exchange).rstrip('.')) for r in answers],
                key=lambda x: x[0]
            )
            mx_hosts = [r[1] for r in records]
            self._dns_cache[domain] = (mx_hosts, datetime.utcnow())
            return mx_hosts
        except dns.resolver.NXDOMAIN:
            return []
        except dns.resolver.NoAnswer:
            # Try A record as fallback
            try:
                loop = asyncio.get_event_loop()
                answers = await loop.run_in_executor(
                    None,
                    lambda: dns.resolver.resolve(domain, 'A')
                )
                records = [str(r) for r in answers]
                self._dns_cache[domain] = (records, datetime.utcnow())
                return records
            except:
                return []
        except Exception as e:
            print(f"DNS error for {domain}: {e}")
            return []

    async def smtp_verify(self, email: str, mx_host: str) -> Tuple[str, str]:
        """
        Verify email via SMTP handshake.
        Returns (status, response_code)
        """
        async with self._semaphore:
            try:
                # Add random delay to avoid rate limiting
                await asyncio.sleep(random.uniform(0.5, 2.0))

                smtp = aiosmtplib.SMTP(
                    hostname=mx_host,
                    port=25,
                    timeout=settings.VERIFIER_SMTP_TIMEOUT
                )

                await smtp.connect()
                await smtp.ehlo(hostname="leadmachine.local")

                # MAIL FROM with a fake sender
                code, _ = await smtp.execute_command(
                    f"MAIL FROM:<verify@leadmachine.local>"
                )

                # RCPT TO - the actual verification
                code, message = await smtp.execute_command(
                    f"RCPT TO:<{email}>"
                )

                await smtp.quit()

                if code == 250:
                    return "valid", str(code)
                elif code in [550, 551, 552, 553, 554]:
                    return "invalid", str(code)
                else:
                    return "unknown", str(code)

            except aiosmtplib.SMTPConnectError:
                return "unknown", "connect_failed"
            except aiosmtplib.SMTPResponseException as e:
                if e.code in [550, 551, 552, 553, 554]:
                    return "invalid", str(e.code)
                return "unknown", str(e.code)
            except asyncio.TimeoutError:
                return "unknown", "timeout"
            except Exception as e:
                return "unknown", f"error:{str(e)[:50]}"

    async def check_catch_all(self, domain: str, mx_host: str) -> bool:
        """Check if domain accepts all emails (catch-all)."""
        # Generate random gibberish email
        random_local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=20))
        test_email = f"{random_local}@{domain}"

        status, _ = await self.smtp_verify(test_email, mx_host)
        return status == "valid"

    async def verify_email(self, email: str) -> VerificationResult:
        """
        Perform full 5-step email verification.
        """
        email = email.lower().strip()
        details = {}

        # Extract domain
        try:
            local, domain = email.rsplit('@', 1)
        except ValueError:
            return VerificationResult(
                email=email,
                status="invalid",
                confidence=0.0,
                is_catch_all=False,
                is_free_provider=False,
                mx_record=None,
                smtp_response=None,
                details={"error": "Invalid email format"}
            )

        # Step 1: Syntax check
        if not self.is_valid_syntax(email):
            return VerificationResult(
                email=email,
                status="invalid",
                confidence=0.0,
                is_catch_all=False,
                is_free_provider=False,
                mx_record=None,
                smtp_response=None,
                details={"step": "syntax", "error": "Invalid syntax"}
            )
        details["syntax"] = "valid"

        # Check for junk emails
        if self.is_junk_email(email):
            return VerificationResult(
                email=email,
                status="invalid",
                confidence=0.0,
                is_catch_all=False,
                is_free_provider=False,
                mx_record=None,
                smtp_response=None,
                details={"step": "junk_filter", "error": "Junk/platform email"}
            )
        details["junk_filter"] = "passed"

        # Step 2: Disposable check
        is_disposable = self.is_disposable(domain)
        if is_disposable:
            return VerificationResult(
                email=email,
                status="invalid",
                confidence=0.0,
                is_catch_all=False,
                is_free_provider=False,
                mx_record=None,
                smtp_response=None,
                details={"step": "disposable", "error": "Disposable email domain"}
            )
        details["disposable"] = False

        # Check free provider
        is_free = self.is_free_provider(domain)
        details["free_provider"] = is_free

        # Step 3: MX record check
        mx_records = await self.get_mx_records(domain)
        if not mx_records:
            return VerificationResult(
                email=email,
                status="invalid",
                confidence=0.0,
                is_catch_all=False,
                is_free_provider=is_free,
                mx_record=None,
                smtp_response=None,
                details={"step": "mx_check", "error": "No MX records found"}
            )
        mx_host = mx_records[0]
        details["mx_records"] = mx_records

        # Step 4: SMTP handshake
        smtp_status, smtp_response = await self.smtp_verify(email, mx_host)
        details["smtp_status"] = smtp_status
        details["smtp_response"] = smtp_response

        # Step 5: Catch-all detection (only if SMTP says valid)
        is_catch_all = False
        if smtp_status == "valid":
            is_catch_all = await self.check_catch_all(domain, mx_host)
            details["catch_all"] = is_catch_all

        # Calculate confidence score
        if smtp_status == "valid" and not is_catch_all:
            confidence = 95.0
            status = "valid"
        elif smtp_status == "valid" and is_catch_all:
            confidence = 50.0
            status = "risky"
        elif smtp_status == "invalid":
            confidence = 0.0
            status = "invalid"
        elif smtp_status == "unknown":
            if smtp_response == "timeout":
                confidence = 30.0
            else:
                confidence = 40.0
            status = "unknown"
        else:
            confidence = 30.0
            status = "unknown"

        return VerificationResult(
            email=email,
            status=status,
            confidence=confidence,
            is_catch_all=is_catch_all,
            is_free_provider=is_free,
            mx_record=mx_host,
            smtp_response=smtp_response,
            details=details
        )

    async def verify_batch(self, emails: List[str]) -> List[VerificationResult]:
        """Verify multiple emails concurrently."""
        tasks = [self.verify_email(email) for email in emails]
        return await asyncio.gather(*tasks)


# Singleton instance
verifier = EmailVerifier()


async def init_verifier():
    """Initialize the verifier with disposable domains."""
    await verifier.load_disposable_domains()
