"""GoHighLevel integration module."""

import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class GHLContact:
    """GHL contact data."""
    id: Optional[str] = None
    email: str = ""
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    companyName: Optional[str] = None
    website: Optional[str] = None
    source: str = "Lead Machine"
    tags: List[str] = None
    customFields: Dict[str, Any] = None


@dataclass
class GHLResult:
    """Result from GHL operation."""
    success: bool
    contact_id: Optional[str] = None
    action: str = ""  # created, updated, skipped
    error: Optional[str] = None


class GHLClient:
    """GoHighLevel API client."""

    def __init__(self):
        self.api_url = settings.GHL_API_URL
        self.api_key = settings.GHL_API_KEY
        self.location_id = settings.GHL_LOCATION_ID

    def _get_headers(self) -> Dict[str, str]:
        """Get API headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Version": "2021-07-28",
        }

    async def find_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find existing contact by email."""
        if not self.api_key or not self.location_id:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/contacts/lookup",
                    headers=self._get_headers(),
                    params={
                        "locationId": self.location_id,
                        "email": email,
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    contacts = data.get("contacts", [])
                    if contacts:
                        return contacts[0]
        except Exception as e:
            print(f"GHL lookup error: {e}")

        return None

    async def create_contact(self, contact: GHLContact) -> GHLResult:
        """Create a new contact in GHL."""
        if not self.api_key or not self.location_id:
            return GHLResult(
                success=False,
                error="GHL API credentials not configured"
            )

        try:
            payload = {
                "locationId": self.location_id,
                "email": contact.email,
                "source": contact.source,
            }

            if contact.firstName:
                payload["firstName"] = contact.firstName
            if contact.lastName:
                payload["lastName"] = contact.lastName
            if contact.phone:
                payload["phone"] = contact.phone
            if contact.companyName:
                payload["companyName"] = contact.companyName
            if contact.website:
                payload["website"] = contact.website
            if contact.tags:
                payload["tags"] = contact.tags
            if contact.customFields:
                payload["customFields"] = contact.customFields

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/contacts/",
                    headers=self._get_headers(),
                    json=payload,
                    timeout=30,
                )

                if response.status_code in [200, 201]:
                    data = response.json()
                    return GHLResult(
                        success=True,
                        contact_id=data.get("contact", {}).get("id"),
                        action="created"
                    )
                else:
                    return GHLResult(
                        success=False,
                        error=f"API error: {response.status_code} - {response.text[:200]}"
                    )

        except Exception as e:
            return GHLResult(
                success=False,
                error=f"Exception: {str(e)}"
            )

    async def update_contact(self, contact_id: str, contact: GHLContact) -> GHLResult:
        """Update an existing contact in GHL."""
        if not self.api_key:
            return GHLResult(
                success=False,
                error="GHL API credentials not configured"
            )

        try:
            payload = {}

            if contact.firstName:
                payload["firstName"] = contact.firstName
            if contact.lastName:
                payload["lastName"] = contact.lastName
            if contact.phone:
                payload["phone"] = contact.phone
            if contact.companyName:
                payload["companyName"] = contact.companyName
            if contact.website:
                payload["website"] = contact.website
            if contact.tags:
                payload["tags"] = contact.tags
            if contact.customFields:
                payload["customFields"] = contact.customFields

            if not payload:
                return GHLResult(
                    success=True,
                    contact_id=contact_id,
                    action="skipped"
                )

            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self.api_url}/contacts/{contact_id}",
                    headers=self._get_headers(),
                    json=payload,
                    timeout=30,
                )

                if response.status_code in [200, 201]:
                    return GHLResult(
                        success=True,
                        contact_id=contact_id,
                        action="updated"
                    )
                else:
                    return GHLResult(
                        success=False,
                        contact_id=contact_id,
                        error=f"API error: {response.status_code}"
                    )

        except Exception as e:
            return GHLResult(
                success=False,
                error=f"Exception: {str(e)}"
            )

    async def push_lead(
        self,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        company_name: Optional[str] = None,
        website: Optional[str] = None,
        source_url: Optional[str] = None,
        job_title: Optional[str] = None,
        confidence: float = 0.0,
        verification_status: str = "unknown",
    ) -> GHLResult:
        """Push a lead to GHL, creating or updating as needed."""

        # Build tags
        tags = ["scraped-lead", f"verification-{verification_status}"]
        if confidence >= 90:
            tags.append("high-confidence")
        elif confidence >= 70:
            tags.append("medium-confidence")
        else:
            tags.append("low-confidence")

        # Build custom fields
        custom_fields = [
            {"key": "lead_source_url", "value": source_url or ""},
            {"key": "email_confidence", "value": str(int(confidence))},
            {"key": "job_title", "value": job_title or ""},
            {"key": "verification_status", "value": verification_status},
            {"key": "scraped_date", "value": datetime.utcnow().isoformat()},
        ]

        contact = GHLContact(
            email=email,
            firstName=first_name,
            lastName=last_name,
            phone=phone,
            companyName=company_name,
            website=website,
            source="Lead Machine",
            tags=tags,
            customFields=custom_fields,
        )

        # Check if contact exists
        existing = await self.find_contact_by_email(email)

        if existing:
            contact_id = existing.get("id")
            return await self.update_contact(contact_id, contact)
        else:
            return await self.create_contact(contact)


# Singleton instance
ghl_client = GHLClient()
