"""
Lead Machine - Industry-Based Lead Database
Permanent storage with industry segmentation for sale/export
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Enum, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()

class Industry(enum.Enum):
    DOCTORS = "doctors"
    LAWYERS = "lawyers"
    DENTISTS = "dentists"
    CHIROPRACTORS = "chiropractors"
    REAL_ESTATE = "real_estate"
    RESTAURANTS = "restaurants"
    PLUMBERS = "plumbers"
    ELECTRICIANS = "electricians"
    HVAC = "hvac"
    ROOFING = "roofing"
    AUTO_REPAIR = "auto_repair"
    INSURANCE = "insurance"
    ACCOUNTANTS = "accountants"
    VETERINARIANS = "veterinarians"
    FITNESS = "fitness"

class EmailStatus(enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"

class Lead(Base):
    """Main lead storage - never deleted"""
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    company_name = Column(String(255))
    phone = Column(String(50))
    website = Column(String(500))
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(50))
    zip_code = Column(String(20))
    country = Column(String(100), default="USA")
    
    # Industry classification
    industry = Column(String(50), index=True, nullable=False)
    sub_industry = Column(String(100))
    
    # Verification status
    email_verified = Column(Boolean, default=False)
    email_verification_date = Column(DateTime)
    mx_records = Column(Text)
    smtp_valid = Column(Boolean)
    is_catchall = Column(Boolean)
    
    # Source tracking
    source_url = Column(String(500))
    source_type = Column(String(50))  # scraped, imported, manual
    scraped_at = Column(DateTime, default=datetime.utcnow)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags = Column(JSON)
    custom_fields = Column(JSON)
    
    # Relationships
    emails_sent = relationship("EmailCampaign", back_populates="lead")
    communications = relationship("Communication", back_populates="lead")

class EmailCampaign(Base):
    """Track emails sent to leads"""
    __tablename__ = "email_campaigns"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    campaign_name = Column(String(255))
    
    # Email content
    subject = Column(String(500))
    body_html = Column(Text)
    body_text = Column(Text)
    from_email = Column(String(255))
    from_name = Column(String(255))
    reply_to = Column(String(255))
    
    # Status tracking
    status = Column(String(50), default="pending")
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    opened_at = Column(DateTime)
    clicked_at = Column(DateTime)
    replied_at = Column(DateTime)
    bounced_at = Column(DateTime)
    bounce_reason = Column(Text)
    
    # Tracking IDs
    message_id = Column(String(255), unique=True)
    tracking_pixel_id = Column(String(255))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    lead = relationship("Lead", back_populates="emails_sent")

class Communication(Base):
    """Track all communications (responses, replies)"""
    __tablename__ = "communications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    
    # Message details
    direction = Column(String(20))  # inbound, outbound
    channel = Column(String(50))  # email, sms, call
    
    # Email specifics
    from_email = Column(String(255))
    to_email = Column(String(255))
    subject = Column(String(500))
    body_html = Column(Text)
    body_text = Column(Text)
    
    # Threading
    in_reply_to = Column(String(255))
    thread_id = Column(String(255))
    
    # Status
    is_read = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    sentiment = Column(String(50))  # positive, negative, neutral
    
    received_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    lead = relationship("Lead", back_populates="communications")

class SMTPAccount(Base):
    """SMTP accounts for sending emails"""
    __tablename__ = "smtp_accounts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    email = Column(String(255), unique=True)
    
    # SMTP settings (encrypted)
    smtp_host = Column(String(255))
    smtp_port = Column(Integer, default=587)
    smtp_username = Column(String(255))
    smtp_password_encrypted = Column(Text)
    use_tls = Column(Boolean, default=True)
    
    # IMAP settings for receiving
    imap_host = Column(String(255))
    imap_port = Column(Integer, default=993)
    imap_username = Column(String(255))
    imap_password_encrypted = Column(Text)
    
    # Limits and tracking
    daily_limit = Column(Integer, default=100)
    emails_sent_today = Column(Integer, default=0)
    last_reset_date = Column(DateTime)
    
    # Warmup status
    is_warming = Column(Boolean, default=False)
    warmup_day = Column(Integer, default=0)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ExportHistory(Base):
    """Track database exports for selling"""
    __tablename__ = "export_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    industry = Column(String(50))
    export_format = Column(String(20))  # csv, json, xlsx
    record_count = Column(Integer)
    file_path = Column(String(500))
    exported_at = Column(DateTime, default=datetime.utcnow)
    exported_by = Column(String(255))
