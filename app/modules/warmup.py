"""Email warmup system module."""

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import aiosmtplib
import aioimaplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet

from app.core.config import settings


# Warmup email templates
EMAIL_TEMPLATES = [
    {
        "subject": "Quick follow-up on our meeting",
        "body": "Hi,\n\nJust wanted to follow up on our conversation from earlier. Let me know if you need any additional information.\n\nBest regards"
    },
    {
        "subject": "Project update",
        "body": "Hello,\n\nI wanted to give you a quick update on the project we discussed. Everything is progressing well and we should be on track for the deadline.\n\nThanks"
    },
    {
        "subject": "Question about the proposal",
        "body": "Hi there,\n\nI had a quick question about the proposal you sent over. Do you have a few minutes to chat this week?\n\nBest"
    },
    {
        "subject": "Thank you for your time",
        "body": "Hello,\n\nThank you for taking the time to speak with me today. I really appreciate your insights and look forward to working together.\n\nKind regards"
    },
    {
        "subject": "Re: Schedule confirmation",
        "body": "Thanks for confirming! I've added it to my calendar. See you then.\n\nBest"
    },
    {
        "subject": "Document attached",
        "body": "Hi,\n\nPlease find the document we discussed attached to this email. Let me know if you have any questions.\n\nThanks"
    },
    {
        "subject": "Checking in",
        "body": "Hello,\n\nJust checking in to see how things are going on your end. Hope all is well!\n\nBest regards"
    },
    {
        "subject": "Quick question",
        "body": "Hi,\n\nI have a quick question for you. When you get a chance, could you let me know your thoughts on the timeline?\n\nThanks"
    },
    {
        "subject": "Re: Next steps",
        "body": "Sounds great! I'll start working on that right away and get back to you by end of week.\n\nBest"
    },
    {
        "subject": "Availability next week",
        "body": "Hello,\n\nWould you be available for a call next week? I'd like to discuss a few things in more detail.\n\nLet me know what works for you.\n\nThanks"
    },
    {
        "subject": "Re: Budget discussion",
        "body": "Thanks for the update on the budget. I'll review the numbers and get back to you with my thoughts.\n\nBest"
    },
    {
        "subject": "Meeting notes",
        "body": "Hi,\n\nHere are the notes from our meeting today. Please review and let me know if I missed anything.\n\nThanks"
    },
    {
        "subject": "Introduction",
        "body": "Hello,\n\nI hope this email finds you well. I wanted to introduce myself and our services that might be relevant to your business.\n\nLooking forward to connecting.\n\nBest regards"
    },
    {
        "subject": "Re: Timeline update",
        "body": "Got it, thanks for the update! I'll adjust our schedule accordingly.\n\nBest"
    },
    {
        "subject": "Feedback request",
        "body": "Hi,\n\nI was wondering if you had a chance to review the materials I sent over. Would love to hear your feedback when you have a moment.\n\nThanks"
    },
]

# Rampup schedule (week -> daily emails)
WARMUP_SCHEDULE = {
    1: 5,
    2: 10,
    3: 15,
    4: 20,
    5: 30,
    6: 40,  # 6+ weeks
}


@dataclass
class WarmupStats:
    """Warmup statistics for an account."""
    email: str
    is_active: bool
    days_active: int
    current_daily_limit: int
    total_sent: int
    total_received: int
    total_replied: int
    reply_rate: float
    spam_moves: int
    health_score: float


def get_encryption_key() -> bytes:
    """Get or generate encryption key."""
    if settings.ENCRYPTION_KEY:
        return settings.ENCRYPTION_KEY.encode()
    # Generate a key (in production, this should be persisted)
    return Fernet.generate_key()


def encrypt_password(password: str) -> str:
    """Encrypt a password."""
    f = Fernet(get_encryption_key())
    return f.encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """Decrypt a password."""
    f = Fernet(get_encryption_key())
    return f.decrypt(encrypted.encode()).decode()


class WarmupManager:
    """Email warmup manager."""

    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self._running = False

    def get_daily_limit(self, days_active: int) -> int:
        """Get daily email limit based on warmup progress."""
        week = (days_active // 7) + 1
        if week >= 6:
            return WARMUP_SCHEDULE[6]
        return WARMUP_SCHEDULE.get(week, 5)

    def generate_warmup_id(self) -> str:
        """Generate unique warmup email ID."""
        return f"leadmachine-{uuid.uuid4().hex[:16]}"

    def get_random_template(self) -> Dict[str, str]:
        """Get a random email template."""
        return random.choice(EMAIL_TEMPLATES)

    async def send_warmup_email(
        self,
        from_account: Dict[str, Any],
        to_email: str,
        warmup_id: str,
    ) -> bool:
        """Send a warmup email."""
        try:
            template = self.get_random_template()

            # Create message
            msg = MIMEMultipart()
            msg['From'] = from_account['email']
            msg['To'] = to_email
            msg['Subject'] = template['subject']
            msg['X-Warmup-ID'] = warmup_id

            body = template['body']
            msg.attach(MIMEText(body, 'plain'))

            # Decrypt password
            password = decrypt_password(from_account['smtp_password_encrypted'])

            # Send via SMTP
            await aiosmtplib.send(
                msg,
                hostname=from_account['smtp_host'],
                port=from_account['smtp_port'],
                username=from_account['smtp_username'],
                password=password,
                use_tls=True,
                timeout=30,
            )

            return True

        except Exception as e:
            print(f"Failed to send warmup email: {e}")
            return False

    async def check_inbox(self, account: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check inbox for warmup emails."""
        warmup_emails = []

        try:
            password = decrypt_password(account['imap_password_encrypted'])

            imap = aioimaplib.IMAP4_SSL(
                host=account['imap_host'],
                port=account['imap_port'],
                timeout=30,
            )

            await imap.wait_hello_from_server()
            await imap.login(account['imap_username'], password)

            # Check INBOX
            await imap.select('INBOX')

            # Search for warmup emails
            _, data = await imap.search('HEADER X-Warmup-ID leadmachine-')

            for msg_id in data[0].split():
                _, msg_data = await imap.fetch(str(msg_id), '(RFC822)')
                # Parse email and extract warmup ID
                # This is simplified - in production, parse the full email
                warmup_emails.append({
                    'msg_id': msg_id,
                    'in_spam': False,
                })

            # Also check Spam/Junk folder
            try:
                await imap.select('[Gmail]/Spam')  # Gmail
                _, data = await imap.search('HEADER X-Warmup-ID leadmachine-')

                for msg_id in data[0].split():
                    warmup_emails.append({
                        'msg_id': msg_id,
                        'in_spam': True,
                    })
            except:
                try:
                    await imap.select('Junk')  # Other providers
                    _, data = await imap.search('HEADER X-Warmup-ID leadmachine-')

                    for msg_id in data[0].split():
                        warmup_emails.append({
                            'msg_id': msg_id,
                            'in_spam': True,
                        })
                except:
                    pass

            await imap.logout()

        except Exception as e:
            print(f"Failed to check inbox: {e}")

        return warmup_emails

    async def move_to_inbox(self, account: Dict[str, Any], msg_id: str) -> bool:
        """Move email from spam to inbox."""
        try:
            password = decrypt_password(account['imap_password_encrypted'])

            imap = aioimaplib.IMAP4_SSL(
                host=account['imap_host'],
                port=account['imap_port'],
            )

            await imap.wait_hello_from_server()
            await imap.login(account['imap_username'], password)

            # Try Gmail spam folder
            try:
                await imap.select('[Gmail]/Spam')
                await imap.copy(str(msg_id), 'INBOX')
                await imap.store(str(msg_id), '+FLAGS', '\\Deleted')
            except:
                # Try generic Junk folder
                await imap.select('Junk')
                await imap.copy(str(msg_id), 'INBOX')
                await imap.store(str(msg_id), '+FLAGS', '\\Deleted')

            await imap.expunge()
            await imap.logout()

            return True

        except Exception as e:
            print(f"Failed to move email: {e}")
            return False

    async def send_reply(
        self,
        account: Dict[str, Any],
        to_email: str,
        original_subject: str,
    ) -> bool:
        """Send a reply to a warmup email."""
        try:
            # Random reply templates
            replies = [
                "Thanks for following up!",
                "Got it, thank you!",
                "Sounds good, I'll take a look.",
                "Thanks for the update!",
                "Great, I'll get back to you soon.",
            ]

            msg = MIMEText(random.choice(replies))
            msg['From'] = account['email']
            msg['To'] = to_email
            msg['Subject'] = f"Re: {original_subject}"

            password = decrypt_password(account['smtp_password_encrypted'])

            await aiosmtplib.send(
                msg,
                hostname=account['smtp_host'],
                port=account['smtp_port'],
                username=account['smtp_username'],
                password=password,
                use_tls=True,
            )

            return True

        except Exception as e:
            print(f"Failed to send reply: {e}")
            return False

    def calculate_health_score(self, stats: Dict[str, Any]) -> float:
        """Calculate account health score."""
        score = 100.0

        # Deduct for spam moves
        spam_rate = stats.get('spam_moves', 0) / max(stats.get('total_received', 1), 1)
        score -= spam_rate * 30

        # Boost for good reply rate
        if stats.get('total_sent', 0) > 10:
            reply_rate = stats.get('total_replied', 0) / stats.get('total_sent', 1)
            if reply_rate >= 0.5:
                score += 10
            elif reply_rate < 0.2:
                score -= 10

        return max(0, min(100, score))


# Singleton instance
warmup_manager = WarmupManager()
