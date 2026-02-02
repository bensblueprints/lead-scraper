"""Lead Machine - Main FastAPI application."""

import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime

from app.core.config import settings
from app.models.database import init_db, get_db, Lead, WarmupAccount
from app.modules.verifier import verifier, init_verifier, VerificationResult
from app.modules.scraper import scraper, ScrapeResult
from app.modules.ghl import ghl_client, GHLResult
from app.modules.warmup import warmup_manager, encrypt_password, WarmupStats


# Pydantic models for API
class ScrapeRequest(BaseModel):
    domain: Optional[str] = None
    domains: Optional[List[str]] = None


class VerifyRequest(BaseModel):
    email: Optional[str] = None
    emails: Optional[List[str]] = None


class WarmupStartRequest(BaseModel):
    email: str
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    imap_host: str
    imap_port: int = 993
    imap_username: str
    imap_password: str


class WarmupStopRequest(BaseModel):
    email: str


class LeadResponse(BaseModel):
    email: str
    name: Optional[str]
    role: Optional[str]
    phone: Optional[str]
    source_url: str
    verification: dict
    ghl: dict


class ScrapeResponse(BaseModel):
    success: bool
    domain: str
    summary: dict
    leads: List[LeadResponse]
    errors: Optional[List[str]] = None


class VerifyResponse(BaseModel):
    email: str
    status: str
    confidence: float
    is_catch_all: bool
    is_free_provider: bool
    mx_record: Optional[str]
    details: dict


# Startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    print("Starting Lead Machine...")
    init_db()
    await init_verifier()
    print("Lead Machine started!")
    yield
    # Shutdown
    print("Shutting down Lead Machine...")


# Create FastAPI app
app = FastAPI(
    title="Lead Machine",
    description="Email scraping, verification, and warmup system",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# API Key authentication
async def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from header."""
    if not settings.API_KEY:
        return True  # No API key configured, allow all
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# Health check endpoint
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Lead Machine",
        "version": settings.APP_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
    }


# Scrape endpoint
@app.post("/api/scrape", response_model=List[ScrapeResponse])
async def scrape_domains(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key),
):
    """
    Scrape domains for email addresses.
    Accepts single domain or list of domains.
    Verifies emails and pushes to GHL.
    """
    # Get domains list
    domains = []
    if request.domain:
        domains.append(request.domain)
    if request.domains:
        domains.extend(request.domains)

    if not domains:
        raise HTTPException(status_code=400, detail="No domains provided")

    results = []

    for domain in domains:
        try:
            # Scrape the domain
            scrape_result = await scraper.scrape_domain(domain)

            leads = []
            emails_valid = 0
            emails_pushed = 0

            for scraped_email in scrape_result.emails:
                # Verify the email
                verification = await verifier.verify_email(scraped_email.email)

                # Build lead response
                lead = LeadResponse(
                    email=scraped_email.email,
                    name=scraped_email.name,
                    role=scraped_email.role,
                    phone=scraped_email.phone,
                    source_url=scraped_email.source_url,
                    verification={
                        "status": verification.status,
                        "confidence": verification.confidence,
                        "is_catch_all": verification.is_catch_all,
                        "is_free_provider": verification.is_free_provider,
                    },
                    ghl={"pushed": False, "contact_id": None},
                )

                # Count valid emails
                if verification.status == "valid":
                    emails_valid += 1

                # Push to GHL if confidence >= 70%
                if verification.confidence >= 70:
                    ghl_result = await ghl_client.push_lead(
                        email=scraped_email.email,
                        first_name=scraped_email.first_name,
                        last_name=scraped_email.last_name,
                        phone=scraped_email.phone,
                        website=f"https://{domain}",
                        source_url=scraped_email.source_url,
                        job_title=scraped_email.role,
                        confidence=verification.confidence,
                        verification_status=verification.status,
                    )

                    if ghl_result.success:
                        lead.ghl = {
                            "pushed": True,
                            "contact_id": ghl_result.contact_id,
                        }
                        emails_pushed += 1

                leads.append(lead)

            results.append(ScrapeResponse(
                success=scrape_result.success,
                domain=domain,
                summary={
                    "pages_crawled": scrape_result.pages_crawled,
                    "emails_found": scrape_result.emails_found,
                    "emails_valid": emails_valid,
                    "emails_pushed_to_ghl": emails_pushed,
                },
                leads=leads,
                errors=scrape_result.errors if scrape_result.errors else None,
            ))

        except Exception as e:
            results.append(ScrapeResponse(
                success=False,
                domain=domain,
                summary={
                    "pages_crawled": 0,
                    "emails_found": 0,
                    "emails_valid": 0,
                    "emails_pushed_to_ghl": 0,
                },
                leads=[],
                errors=[str(e)],
            ))

    return results


# Verify endpoint
@app.post("/api/verify", response_model=List[VerifyResponse])
async def verify_emails(
    request: VerifyRequest,
    _: bool = Depends(verify_api_key),
):
    """
    Verify email addresses.
    Accepts single email or list of emails.
    """
    emails = []
    if request.email:
        emails.append(request.email)
    if request.emails:
        emails.extend(request.emails)

    if not emails:
        raise HTTPException(status_code=400, detail="No emails provided")

    results = []

    for email in emails:
        try:
            verification = await verifier.verify_email(email)
            results.append(VerifyResponse(
                email=verification.email,
                status=verification.status,
                confidence=verification.confidence,
                is_catch_all=verification.is_catch_all,
                is_free_provider=verification.is_free_provider,
                mx_record=verification.mx_record,
                details=verification.details,
            ))
        except Exception as e:
            results.append(VerifyResponse(
                email=email,
                status="error",
                confidence=0.0,
                is_catch_all=False,
                is_free_provider=False,
                mx_record=None,
                details={"error": str(e)},
            ))

    return results


# Warmup endpoints
@app.post("/api/warmup/start")
async def start_warmup(
    request: WarmupStartRequest,
    _: bool = Depends(verify_api_key),
):
    """Start email warmup for an account."""
    try:
        # Encrypt passwords
        smtp_password_encrypted = encrypt_password(request.smtp_password)
        imap_password_encrypted = encrypt_password(request.imap_password)

        # Store account (in production, save to database)
        account = {
            "email": request.email,
            "smtp_host": request.smtp_host,
            "smtp_port": request.smtp_port,
            "smtp_username": request.smtp_username,
            "smtp_password_encrypted": smtp_password_encrypted,
            "imap_host": request.imap_host,
            "imap_port": request.imap_port,
            "imap_username": request.imap_username,
            "imap_password_encrypted": imap_password_encrypted,
            "is_active": True,
            "warmup_started_at": datetime.utcnow(),
            "total_sent": 0,
            "total_received": 0,
            "total_replied": 0,
            "spam_moves": 0,
        }

        warmup_manager.accounts[request.email] = account

        return {
            "success": True,
            "message": f"Warmup started for {request.email}",
            "daily_limit": warmup_manager.get_daily_limit(0),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/warmup/stop")
async def stop_warmup(
    request: WarmupStopRequest,
    _: bool = Depends(verify_api_key),
):
    """Stop email warmup for an account."""
    if request.email in warmup_manager.accounts:
        warmup_manager.accounts[request.email]["is_active"] = False
        return {
            "success": True,
            "message": f"Warmup stopped for {request.email}",
        }
    else:
        raise HTTPException(status_code=404, detail="Account not found")


@app.get("/api/warmup/status")
async def get_warmup_status(
    _: bool = Depends(verify_api_key),
):
    """Get warmup status for all accounts."""
    accounts = []

    for email, account in warmup_manager.accounts.items():
        started_at = account.get("warmup_started_at", datetime.utcnow())
        days_active = (datetime.utcnow() - started_at).days

        total_sent = account.get("total_sent", 0)
        total_received = account.get("total_received", 0)
        total_replied = account.get("total_replied", 0)
        spam_moves = account.get("spam_moves", 0)

        reply_rate = total_replied / max(total_sent, 1) * 100

        health_score = warmup_manager.calculate_health_score(account)

        accounts.append({
            "email": email,
            "is_active": account.get("is_active", False),
            "days_active": days_active,
            "current_daily_limit": warmup_manager.get_daily_limit(days_active),
            "total_sent": total_sent,
            "total_received": total_received,
            "total_replied": total_replied,
            "reply_rate": round(reply_rate, 2),
            "spam_moves": spam_moves,
            "health_score": round(health_score, 2),
        })

    return {
        "accounts": accounts,
        "total_accounts": len(accounts),
        "active_accounts": sum(1 for a in accounts if a["is_active"]),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
