"""
Lead Machine - SMTP Email Platform
Handles email sending, receiving, and tracking
"""
import asyncio
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid
import hashlib
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

class SMTPPlatform:
    """Complete SMTP email platform for sending and receiving"""
    
    def __init__(self, encryption_key: str):
        self.fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        self.tracking_base_url = "http://100.122.165.61:8000/api/track"
    
    def encrypt_password(self, password: str) -> str:
        """Encrypt password for storage"""
        return self.fernet.encrypt(password.encode()).decode()
    
    def decrypt_password(self, encrypted: str) -> str:
        """Decrypt password for use"""
        return self.fernet.decrypt(encrypted.encode()).decode()
    
    def generate_tracking_pixel(self, campaign_id: int, lead_id: int) -> str:
        """Generate tracking pixel HTML"""
        pixel_id = hashlib.md5(f"{campaign_id}-{lead_id}-{datetime.utcnow().isoformat()}".encode()).hexdigest()
        return f'<img src="{self.tracking_base_url}/open/{pixel_id}" width="1" height="1" style="display:none" />'
    
    def generate_click_tracking_url(self, campaign_id: int, lead_id: int, original_url: str) -> str:
        """Generate click tracking URL"""
        click_id = hashlib.md5(f"{campaign_id}-{lead_id}-{original_url}".encode()).hexdigest()
        return f"{self.tracking_base_url}/click/{click_id}?url={original_url}"
    
    async def send_email(
        self,
        smtp_config: Dict[str, Any],
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str = None,
        from_name: str = None,
        reply_to: str = None,
        campaign_id: int = None,
        lead_id: int = None
    ) -> Dict[str, Any]:
        """Send email via SMTP with tracking"""
        try:
            # Decrypt password
            password = self.decrypt_password(smtp_config['smtp_password_encrypted'])
            
            # Create message
            msg = MIMEMultipart('alternative')
            message_id = make_msgid()
            
            msg['Message-ID'] = message_id
            msg['Subject'] = subject
            msg['From'] = f"{from_name or smtp_config['name']} <{smtp_config['email']}>"
            msg['To'] = to_email
            msg['Date'] = formatdate(localtime=True)
            
            if reply_to:
                msg['Reply-To'] = reply_to
            
            # Add tracking pixel to HTML
            if campaign_id and lead_id:
                tracking_pixel = self.generate_tracking_pixel(campaign_id, lead_id)
                body_html = body_html + tracking_pixel
            
            # Attach parts
            if body_text:
                msg.attach(MIMEText(body_text, 'plain'))
            msg.attach(MIMEText(body_html, 'html'))
            
            # Send via SMTP
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._send_smtp,
                smtp_config['smtp_host'],
                smtp_config['smtp_port'],
                smtp_config['smtp_username'],
                password,
                smtp_config['email'],
                to_email,
                msg.as_string(),
                smtp_config.get('use_tls', True)
            )
            
            return {
                "success": True,
                "message_id": message_id,
                "sent_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _send_smtp(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        to_email: str,
        message: str,
        use_tls: bool
    ):
        """Synchronous SMTP send"""
        if use_tls:
            server = smtplib.SMTP(host, port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port)
        
        server.login(username, password)
        server.sendmail(from_email, to_email, message)
        server.quit()
    
    async def check_inbox(
        self,
        imap_config: Dict[str, Any],
        folder: str = "INBOX",
        unseen_only: bool = True,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Check inbox for responses"""
        try:
            password = self.decrypt_password(imap_config['imap_password_encrypted'])
            
            loop = asyncio.get_event_loop()
            messages = await loop.run_in_executor(
                None,
                self._fetch_emails,
                imap_config['imap_host'],
                imap_config['imap_port'],
                imap_config['imap_username'],
                password,
                folder,
                unseen_only,
                limit
            )
            
            return messages
            
        except Exception as e:
            logger.error(f"Failed to check inbox: {e}")
            return []
    
    def _fetch_emails(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        folder: str,
        unseen_only: bool,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Synchronous IMAP fetch"""
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(username, password)
        mail.select(folder)
        
        search_criteria = "(UNSEEN)" if unseen_only else "ALL"
        _, message_numbers = mail.search(None, search_criteria)
        
        messages = []
        for num in message_numbers[0].split()[-limit:]:
            _, msg_data = mail.fetch(num, "(RFC822)")
            email_body = msg_data[0][1]
            msg = email.message_from_bytes(email_body)
            
            # Extract body
            body_text = ""
            body_html = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body_text = part.get_payload(decode=True).decode()
                    elif part.get_content_type() == "text/html":
                        body_html = part.get_payload(decode=True).decode()
            else:
                body_text = msg.get_payload(decode=True).decode()
            
            messages.append({
                "message_id": msg.get("Message-ID"),
                "from_email": msg.get("From"),
                "to_email": msg.get("To"),
                "subject": msg.get("Subject"),
                "date": msg.get("Date"),
                "in_reply_to": msg.get("In-Reply-To"),
                "body_text": body_text,
                "body_html": body_html
            })
        
        mail.close()
        mail.logout()
        
        return messages
    
    async def send_bulk_campaign(
        self,
        smtp_config: Dict[str, Any],
        leads: List[Dict[str, Any]],
        subject_template: str,
        body_html_template: str,
        body_text_template: str = None,
        delay_seconds: int = 5,
        daily_limit: int = 100
    ) -> Dict[str, Any]:
        """Send bulk email campaign with rate limiting"""
        results = {
            "total": len(leads),
            "sent": 0,
            "failed": 0,
            "errors": []
        }
        
        for i, lead in enumerate(leads):
            if i >= daily_limit:
                results["stopped_at_limit"] = True
                break
            
            # Personalize templates
            subject = self._personalize(subject_template, lead)
            body_html = self._personalize(body_html_template, lead)
            body_text = self._personalize(body_text_template, lead) if body_text_template else None
            
            result = await self.send_email(
                smtp_config=smtp_config,
                to_email=lead['email'],
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                campaign_id=lead.get('campaign_id'),
                lead_id=lead.get('id')
            )
            
            if result['success']:
                results['sent'] += 1
            else:
                results['failed'] += 1
                results['errors'].append({
                    "email": lead['email'],
                    "error": result.get('error')
                })
            
            # Rate limiting
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        
        return results
    
    def _personalize(self, template: str, lead: Dict[str, Any]) -> str:
        """Personalize template with lead data"""
        replacements = {
            "{{first_name}}": lead.get('first_name', ''),
            "{{last_name}}": lead.get('last_name', ''),
            "{{company_name}}": lead.get('company_name', ''),
            "{{email}}": lead.get('email', ''),
            "{{website}}": lead.get('website', ''),
            "{{city}}": lead.get('city', ''),
            "{{state}}": lead.get('state', ''),
        }
        
        result = template
        for key, value in replacements.items():
            result = result.replace(key, value or '')
        
        return result


# Email templates for different industries
EMAIL_TEMPLATES = {
    "doctors": {
        "subject": "Grow Your Medical Practice with Proven Marketing",
        "body_html": """
        <html>
        <body>
        <p>Hi {{first_name}},</p>
        <p>I noticed {{company_name}} and wanted to reach out about helping you attract more patients.</p>
        <p>We specialize in medical practice marketing and have helped practices like yours increase patient bookings by 40%.</p>
        <p>Would you be open to a quick 15-minute call this week?</p>
        <p>Best regards,<br>Ben</p>
        </body>
        </html>
        """
    },
    "lawyers": {
        "subject": "Get More Cases for {{company_name}}",
        "body_html": """
        <html>
        <body>
        <p>Hi {{first_name}},</p>
        <p>Law firms like {{company_name}} are our specialty.</p>
        <p>We help attorneys generate qualified leads and increase case volume through targeted digital marketing.</p>
        <p>Interested in learning how we can help your firm?</p>
        <p>Best regards,<br>Ben</p>
        </body>
        </html>
        """
    },
    "dentists": {
        "subject": "Fill Your Dental Chairs with New Patients",
        "body_html": """
        <html>
        <body>
        <p>Hi {{first_name}},</p>
        <p>I work with dental practices like {{company_name}} to attract high-value patients.</p>
        <p>Our clients typically see a 3x ROI within 90 days.</p>
        <p>Would love to share some strategies that could work for your practice.</p>
        <p>Best regards,<br>Ben</p>
        </body>
        </html>
        """
    }
}
