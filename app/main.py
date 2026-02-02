"""
Lead Machine v2.0 - Complete Lead Scraping, Email & CRM Platform
With industry-based databases, SMTP platform, and communications tracking
"""
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
import logging
import os

from app.core.config import settings
from app.modules.verifier import EmailVerifier
from app.modules.scraper import WebsiteScraper
from app.modules.ghl import GHLClient
from app.modules.warmup import EmailWarmup
from app.modules.smtp_platform import SMTPPlatform, EMAIL_TEMPLATES
from app.models.leads_db import Lead, EmailCampaign, Communication, SMTPAccount, ExportHistory, Industry

# Database setup
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from app.models.leads_db import Base

engine = create_engine(settings.DATABASE_URL, echo=False)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Lead Machine v2.0",
    description="Complete lead scraping, email campaigns, and CRM platform with industry databases",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize modules
verifier = EmailVerifier()
scraper = WebsiteScraper()
ghl_client = GHLClient(settings.GHL_API_KEY, settings.GHL_LOCATION_ID)
warmup = EmailWarmup(settings.ENCRYPTION_KEY)
smtp_platform = SMTPPlatform(settings.ENCRYPTION_KEY)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# API Key verification
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# ============ REQUEST/RESPONSE MODELS ============

class ScrapeRequest(BaseModel):
    url: str
    industry: str
    verify_emails: bool = True
    push_to_ghl: bool = False
    save_to_db: bool = True

class VerifyRequest(BaseModel):
    emails: List[EmailStr]

class LeadCreate(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    industry: str
    city: Optional[str] = None
    state: Optional[str] = None

class EmailCampaignCreate(BaseModel):
    industry: str
    subject: str
    body_html: str
    body_text: Optional[str] = None
    from_name: str = "Ben"
    smtp_account_id: int
    daily_limit: int = 50
    delay_seconds: int = 10

class SMTPAccountCreate(BaseModel):
    name: str
    email: EmailStr
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    imap_host: str
    imap_port: int = 993
    imap_username: str
    imap_password: str
    use_tls: bool = True
    daily_limit: int = 100

class ExportRequest(BaseModel):
    industry: str
    format: str = "csv"  # csv, json, xlsx

# ============ HEALTH & STATUS ============

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Lead Machine",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": ["scraping", "verification", "smtp", "campaigns", "communications"]
    }

# ============ SCRAPING ENDPOINTS ============

@app.post("/api/scrape", dependencies=[Depends(verify_api_key)])
async def scrape_website(request: ScrapeRequest, db: Session = Depends(get_db)):
    """Scrape emails from URL and save to industry database"""
    try:
        # Validate industry
        valid_industries = [i.value for i in Industry]
        if request.industry not in valid_industries:
            raise HTTPException(400, f"Invalid industry. Must be one of: {valid_industries}")
        
        # Scrape
        emails = await scraper.scrape_emails(request.url)
        
        results = {
            "url": request.url,
            "industry": request.industry,
            "emails_found": len(emails),
            "verified_emails": [],
            "saved_leads": 0
        }
        
        # Verify if requested
        if request.verify_emails:
            for email_addr in emails:
                verification = await verifier.verify_email(email_addr)
                if verification.get("is_valid"):
                    results["verified_emails"].append(verification)
        
        # Save to database
        if request.save_to_db:
            for email_data in (results["verified_emails"] or [{"email": e} for e in emails]):
                # Check if exists
                existing = db.query(Lead).filter(Lead.email == email_data.get("email")).first()
                if not existing:
                    lead = Lead(
                        email=email_data.get("email"),
                        industry=request.industry,
                        source_url=request.url,
                        source_type="scraped",
                        email_verified=email_data.get("is_valid", False),
                        email_verification_date=datetime.utcnow() if email_data.get("is_valid") else None,
                        mx_records=str(email_data.get("mx_records", [])),
                        smtp_valid=email_data.get("smtp_valid"),
                        is_catchall=email_data.get("is_catchall")
                    )
                    db.add(lead)
                    results["saved_leads"] += 1
            
            db.commit()
        
        # Push to GHL if requested
        if request.push_to_ghl:
            for email_data in results["verified_emails"]:
                await ghl_client.create_contact({
                    "email": email_data["email"],
                    "tags": [request.industry, "lead-machine"]
                })
        
        return results
        
    except Exception as e:
        logger.error(f"Scrape error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/verify", dependencies=[Depends(verify_api_key)])
async def verify_emails(request: VerifyRequest):
    """Verify a list of emails"""
    results = []
    for email in request.emails:
        verification = await verifier.verify_email(email)
        results.append(verification)
    return {"results": results}

# ============ LEAD DATABASE ENDPOINTS ============

@app.get("/api/leads", dependencies=[Depends(verify_api_key)])
async def get_leads(
    industry: Optional[str] = None,
    verified_only: bool = False,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get leads from database"""
    query = db.query(Lead)
    
    if industry:
        query = query.filter(Lead.industry == industry)
    if verified_only:
        query = query.filter(Lead.email_verified == True)
    
    total = query.count()
    leads = query.offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "leads": [
            {
                "id": l.id,
                "email": l.email,
                "first_name": l.first_name,
                "last_name": l.last_name,
                "company_name": l.company_name,
                "industry": l.industry,
                "email_verified": l.email_verified,
                "source_url": l.source_url,
                "created_at": l.created_at.isoformat() if l.created_at else None
            }
            for l in leads
        ]
    }

@app.post("/api/leads", dependencies=[Depends(verify_api_key)])
async def create_lead(lead_data: LeadCreate, db: Session = Depends(get_db)):
    """Manually add a lead"""
    existing = db.query(Lead).filter(Lead.email == lead_data.email).first()
    if existing:
        raise HTTPException(400, "Lead with this email already exists")
    
    lead = Lead(**lead_data.dict(), source_type="manual")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    
    return {"id": lead.id, "email": lead.email, "industry": lead.industry}

@app.get("/api/leads/stats", dependencies=[Depends(verify_api_key)])
async def get_lead_stats(db: Session = Depends(get_db)):
    """Get lead statistics by industry"""
    stats = db.query(
        Lead.industry,
        func.count(Lead.id).label("total"),
        func.sum(Lead.email_verified.cast(Integer)).label("verified")
    ).group_by(Lead.industry).all()
    
    return {
        "industries": [
            {
                "industry": s[0],
                "total_leads": s[1],
                "verified_leads": s[2] or 0
            }
            for s in stats
        ],
        "total_all": db.query(Lead).count()
    }

@app.post("/api/leads/export", dependencies=[Depends(verify_api_key)])
async def export_leads(request: ExportRequest, db: Session = Depends(get_db)):
    """Export leads by industry for sale"""
    query = db.query(Lead).filter(Lead.industry == request.industry)
    leads = query.all()
    
    if not leads:
        raise HTTPException(404, "No leads found for this industry")
    
    # Generate export data
    export_data = [
        {
            "email": l.email,
            "first_name": l.first_name,
            "last_name": l.last_name,
            "company_name": l.company_name,
            "phone": l.phone,
            "website": l.website,
            "city": l.city,
            "state": l.state,
            "verified": l.email_verified
        }
        for l in leads
    ]
    
    # Record export
    export_record = ExportHistory(
        industry=request.industry,
        export_format=request.format,
        record_count=len(export_data),
        exported_at=datetime.utcnow()
    )
    db.add(export_record)
    db.commit()
    
    return {
        "industry": request.industry,
        "format": request.format,
        "record_count": len(export_data),
        "data": export_data
    }

# ============ SMTP ACCOUNT ENDPOINTS ============

@app.post("/api/smtp/accounts", dependencies=[Depends(verify_api_key)])
async def create_smtp_account(account: SMTPAccountCreate, db: Session = Depends(get_db)):
    """Add SMTP account for sending emails"""
    smtp_account = SMTPAccount(
        name=account.name,
        email=account.email,
        smtp_host=account.smtp_host,
        smtp_port=account.smtp_port,
        smtp_username=account.smtp_username,
        smtp_password_encrypted=smtp_platform.encrypt_password(account.smtp_password),
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        imap_username=account.imap_username,
        imap_password_encrypted=smtp_platform.encrypt_password(account.imap_password),
        use_tls=account.use_tls,
        daily_limit=account.daily_limit
    )
    db.add(smtp_account)
    db.commit()
    db.refresh(smtp_account)
    
    return {"id": smtp_account.id, "email": smtp_account.email}

@app.get("/api/smtp/accounts", dependencies=[Depends(verify_api_key)])
async def list_smtp_accounts(db: Session = Depends(get_db)):
    """List all SMTP accounts"""
    accounts = db.query(SMTPAccount).all()
    return {
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "email": a.email,
                "daily_limit": a.daily_limit,
                "emails_sent_today": a.emails_sent_today,
                "is_active": a.is_active,
                "is_warming": a.is_warming
            }
            for a in accounts
        ]
    }

# ============ EMAIL CAMPAIGN ENDPOINTS ============

@app.post("/api/campaigns/send", dependencies=[Depends(verify_api_key)])
async def send_campaign(
    request: EmailCampaignCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Send email campaign to industry leads"""
    # Get SMTP account
    smtp_account = db.query(SMTPAccount).filter(SMTPAccount.id == request.smtp_account_id).first()
    if not smtp_account:
        raise HTTPException(404, "SMTP account not found")
    
    # Get leads for industry
    leads = db.query(Lead).filter(
        Lead.industry == request.industry,
        Lead.email_verified == True
    ).limit(request.daily_limit).all()
    
    if not leads:
        raise HTTPException(404, "No verified leads found for this industry")
    
    # Prepare SMTP config
    smtp_config = {
        "name": smtp_account.name,
        "email": smtp_account.email,
        "smtp_host": smtp_account.smtp_host,
        "smtp_port": smtp_account.smtp_port,
        "smtp_username": smtp_account.smtp_username,
        "smtp_password_encrypted": smtp_account.smtp_password_encrypted,
        "use_tls": smtp_account.use_tls
    }
    
    # Prepare leads data
    leads_data = [
        {
            "id": l.id,
            "email": l.email,
            "first_name": l.first_name or "",
            "last_name": l.last_name or "",
            "company_name": l.company_name or ""
        }
        for l in leads
    ]
    
    # Start campaign in background
    background_tasks.add_task(
        run_campaign,
        smtp_config,
        leads_data,
        request.subject,
        request.body_html,
        request.body_text,
        request.delay_seconds,
        request.daily_limit,
        db
    )
    
    return {
        "status": "started",
        "industry": request.industry,
        "leads_count": len(leads_data),
        "smtp_account": smtp_account.email
    }

async def run_campaign(
    smtp_config: Dict,
    leads: List[Dict],
    subject: str,
    body_html: str,
    body_text: Optional[str],
    delay: int,
    limit: int,
    db: Session
):
    """Background task to run email campaign"""
    results = await smtp_platform.send_bulk_campaign(
        smtp_config=smtp_config,
        leads=leads,
        subject_template=subject,
        body_html_template=body_html,
        body_text_template=body_text,
        delay_seconds=delay,
        daily_limit=limit
    )
    logger.info(f"Campaign completed: {results}")

@app.get("/api/campaigns/templates", dependencies=[Depends(verify_api_key)])
async def get_email_templates():
    """Get pre-built email templates by industry"""
    return {"templates": EMAIL_TEMPLATES}

# ============ COMMUNICATIONS ENDPOINTS ============

@app.get("/api/communications", dependencies=[Depends(verify_api_key)])
async def get_communications(
    direction: Optional[str] = None,
    is_read: Optional[bool] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """Get communications/responses"""
    query = db.query(Communication)
    
    if direction:
        query = query.filter(Communication.direction == direction)
    if is_read is not None:
        query = query.filter(Communication.is_read == is_read)
    
    comms = query.order_by(Communication.received_at.desc()).limit(limit).all()
    
    return {
        "communications": [
            {
                "id": c.id,
                "lead_id": c.lead_id,
                "direction": c.direction,
                "from_email": c.from_email,
                "to_email": c.to_email,
                "subject": c.subject,
                "body_text": c.body_text[:500] if c.body_text else None,
                "is_read": c.is_read,
                "is_starred": c.is_starred,
                "received_at": c.received_at.isoformat() if c.received_at else None
            }
            for c in comms
        ]
    }

@app.post("/api/communications/check-inbox", dependencies=[Depends(verify_api_key)])
async def check_inbox_for_responses(smtp_account_id: int, db: Session = Depends(get_db)):
    """Check inbox for responses and save to communications"""
    smtp_account = db.query(SMTPAccount).filter(SMTPAccount.id == smtp_account_id).first()
    if not smtp_account:
        raise HTTPException(404, "SMTP account not found")
    
    imap_config = {
        "imap_host": smtp_account.imap_host,
        "imap_port": smtp_account.imap_port,
        "imap_username": smtp_account.imap_username,
        "imap_password_encrypted": smtp_account.imap_password_encrypted
    }
    
    messages = await smtp_platform.check_inbox(imap_config)
    
    saved = 0
    for msg in messages:
        # Try to find matching lead
        lead = db.query(Lead).filter(Lead.email == msg.get("from_email")).first()
        
        comm = Communication(
            lead_id=lead.id if lead else None,
            direction="inbound",
            channel="email",
            from_email=msg.get("from_email"),
            to_email=msg.get("to_email"),
            subject=msg.get("subject"),
            body_text=msg.get("body_text"),
            body_html=msg.get("body_html"),
            in_reply_to=msg.get("in_reply_to"),
            received_at=datetime.utcnow()
        )
        db.add(comm)
        saved += 1
    
    db.commit()
    
    return {"messages_found": len(messages), "saved": saved}

@app.patch("/api/communications/{comm_id}", dependencies=[Depends(verify_api_key)])
async def update_communication(
    comm_id: int,
    is_read: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """Mark communication as read/starred"""
    comm = db.query(Communication).filter(Communication.id == comm_id).first()
    if not comm:
        raise HTTPException(404, "Communication not found")
    
    if is_read is not None:
        comm.is_read = is_read
    if is_starred is not None:
        comm.is_starred = is_starred
    
    db.commit()
    return {"id": comm_id, "is_read": comm.is_read, "is_starred": comm.is_starred}

# ============ WARMUP ENDPOINTS ============

@app.post("/api/warmup/start", dependencies=[Depends(verify_api_key)])
async def start_warmup(smtp_account_id: int, db: Session = Depends(get_db)):
    """Start email warmup for SMTP account"""
    account = db.query(SMTPAccount).filter(SMTPAccount.id == smtp_account_id).first()
    if not account:
        raise HTTPException(404, "SMTP account not found")
    
    account.is_warming = True
    db.commit()
    
    return {"status": "warmup started", "account": account.email}

@app.post("/api/warmup/stop", dependencies=[Depends(verify_api_key)])
async def stop_warmup(smtp_account_id: int, db: Session = Depends(get_db)):
    """Stop email warmup"""
    account = db.query(SMTPAccount).filter(SMTPAccount.id == smtp_account_id).first()
    if not account:
        raise HTTPException(404, "SMTP account not found")
    
    account.is_warming = False
    db.commit()
    
    return {"status": "warmup stopped", "account": account.email}

@app.get("/api/warmup/status", dependencies=[Depends(verify_api_key)])
async def warmup_status(db: Session = Depends(get_db)):
    """Get warmup status for all accounts"""
    accounts = db.query(SMTPAccount).filter(SMTPAccount.is_warming == True).all()
    return {
        "warming_accounts": [
            {
                "id": a.id,
                "email": a.email,
                "warmup_day": a.warmup_day,
                "emails_sent_today": a.emails_sent_today
            }
            for a in accounts
        ]
    }

# ============ TRACKING ENDPOINTS ============

@app.get("/api/track/open/{pixel_id}")
async def track_open(pixel_id: str, db: Session = Depends(get_db)):
    """Track email opens via pixel"""
    # In production, decode pixel_id to get campaign/lead info
    logger.info(f"Email opened: {pixel_id}")
    # Return 1x1 transparent GIF
    from fastapi.responses import Response
    return Response(
        content=b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b',
        media_type="image/gif"
    )

@app.get("/api/track/click/{click_id}")
async def track_click(click_id: str, url: str, db: Session = Depends(get_db)):
    """Track link clicks and redirect"""
    logger.info(f"Link clicked: {click_id} -> {url}")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=url)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
