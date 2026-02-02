"""Database models and connection management."""

import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# Create data directory if it doesn't exist
os.makedirs("data", exist_ok=True)

# Create engine with SQLite
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Lead(Base):
    """Scraped lead model."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    domain = Column(String(255), index=True, nullable=False)
    name = Column(String(255), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    role = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    source_url = Column(String(500), nullable=True)

    # Verification data
    verification_status = Column(String(50), default="pending")
    confidence = Column(Float, default=0.0)
    is_catch_all = Column(Boolean, default=False)
    is_free_provider = Column(Boolean, default=False)
    mx_record = Column(String(255), nullable=True)

    # GHL data
    ghl_pushed = Column(Boolean, default=False)
    ghl_contact_id = Column(String(100), nullable=True)

    # Timestamps
    scraped_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VerificationCache(Base):
    """Cache for email verification results."""

    __tablename__ = "verification_cache"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    status = Column(String(50), nullable=False)
    confidence = Column(Float, default=0.0)
    is_catch_all = Column(Boolean, default=False)
    is_free_provider = Column(Boolean, default=False)
    mx_record = Column(String(255), nullable=True)
    smtp_response = Column(String(10), nullable=True)
    cached_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class DomainCache(Base):
    """Cache for scraped domains."""

    __tablename__ = "domain_cache"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, index=True, nullable=False)
    emails_found = Column(Integer, default=0)
    pages_crawled = Column(Integer, default=0)
    result_data = Column(JSON, nullable=True)
    cached_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class DNSCache(Base):
    """Cache for DNS lookups."""

    __tablename__ = "dns_cache"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, index=True, nullable=False)
    mx_records = Column(JSON, nullable=True)
    a_records = Column(JSON, nullable=True)
    cached_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class WarmupAccount(Base):
    """Email warmup account."""

    __tablename__ = "warmup_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    smtp_host = Column(String(255), nullable=False)
    smtp_port = Column(Integer, default=587)
    smtp_username = Column(String(255), nullable=False)
    smtp_password_encrypted = Column(Text, nullable=False)  # Encrypted
    imap_host = Column(String(255), nullable=False)
    imap_port = Column(Integer, default=993)
    imap_username = Column(String(255), nullable=False)
    imap_password_encrypted = Column(Text, nullable=False)  # Encrypted

    # Status
    is_active = Column(Boolean, default=True)
    warmup_started_at = Column(DateTime, nullable=True)
    current_daily_limit = Column(Integer, default=5)

    # Stats
    total_sent = Column(Integer, default=0)
    total_received = Column(Integer, default=0)
    total_replied = Column(Integer, default=0)
    spam_moves = Column(Integer, default=0)
    health_score = Column(Float, default=100.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WarmupEmail(Base):
    """Warmup email tracking."""

    __tablename__ = "warmup_emails"

    id = Column(Integer, primary_key=True, index=True)
    warmup_id = Column(String(100), unique=True, index=True, nullable=False)
    from_account_id = Column(Integer, nullable=False)
    to_account_id = Column(Integer, nullable=False)
    subject = Column(String(500), nullable=False)

    sent_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    replied_at = Column(DateTime, nullable=True)
    was_in_spam = Column(Boolean, default=False)
    moved_to_inbox = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
