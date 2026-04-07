"""SQLAlchemy models for the email verification system."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Text, JSON, 
    ForeignKey, Index, Enum as SQLEnum, Float
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from enum import Enum


Base = declarative_base()


class VerificationStatus(str, Enum):
    """Email verification status enumeration."""
    DELIVERABLE = "DELIVERABLE"
    INVALID = "INVALID"
    RISKY_CATCH_ALL = "RISKY_CATCH_ALL"
    RISKY_ROLE_BASED = "RISKY_ROLE_BASED"
    UNKNOWN_TEMPFAIL = "UNKNOWN_TEMPFAIL"
    DISPOSABLE = "DISPOSABLE"


class ReasonCode(str, Enum):
    """Reason codes for verification results."""
    SYNTAX_ERROR = "SYNTAX_ERROR"
    NO_MX_RECORD = "NO_MX_RECORD"
    SMTP_USER_UNKNOWN = "SMTP_USER_UNKNOWN"
    SMTP_TEMPFAIL = "SMTP_TEMPFAIL"
    SMTP_ACCEPTED = "SMTP_ACCEPTED"
    CATCH_ALL_DETECTED = "CATCH_ALL_DETECTED"
    ROLE_BASED_ADDRESS = "ROLE_BASED_ADDRESS"
    DISPOSABLE_DOMAIN = "DISPOSABLE_DOMAIN"
    DNS_TIMEOUT = "DNS_TIMEOUT"
    SMTP_TIMEOUT = "SMTP_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"


class JobStatus(str, Enum):
    """Job processing status enumeration."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Job(Base):
    """Bulk verification job model."""
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True)
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, nullable=False)
    total_count = Column(Integer, default=0, nullable=False)
    processed_count = Column(Integer, default=0, nullable=False)
    deliverable_count = Column(Integer, default=0, nullable=False)
    invalid_count = Column(Integer, default=0, nullable=False)
    risky_count = Column(Integer, default=0, nullable=False)
    unknown_count = Column(Integer, default=0, nullable=False)
    disposable_count = Column(Integer, default=0, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    
    config_snapshot = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Relationship to email verifications
    verifications = relationship("EmailVerification", back_populates="job")
    
    __table_args__ = (
        Index("idx_job_status", "status"),
        Index("idx_job_created_at", "created_at"),
    )


class EmailVerification(Base):
    """Individual email verification result model."""
    __tablename__ = "email_verifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=True)
    
    email = Column(String, nullable=False)
    email_hash = Column(String, nullable=False)  # For privacy in logs
    domain = Column(String, nullable=False)
    
    status = Column(SQLEnum(VerificationStatus), nullable=False)
    reason_code = Column(SQLEnum(ReasonCode), nullable=False)
    reasons = Column(JSON, nullable=False, default=list)  # List of reason strings
    
    # DNS results
    mx_records = Column(JSON, nullable=False, default=list)
    has_mx = Column(Boolean, default=False, nullable=False)
    
    # SMTP results
    smtp_transcript = Column(JSON, nullable=False, default=list)
    smtp_accepted = Column(Boolean, default=False, nullable=False)
    
    # Detection flags
    is_catch_all = Column(Boolean, default=False, nullable=False)
    is_role_based = Column(Boolean, default=False, nullable=False)
    is_disposable = Column(Boolean, default=False, nullable=False)
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    verification_duration_ms = Column(Integer, nullable=True)
    
    # Relationship to job
    job = relationship("Job", back_populates="verifications")
    
    __table_args__ = (
        Index("idx_email_verification_email", "email"),
        Index("idx_email_verification_domain", "domain"),
        Index("idx_email_verification_status", "status"),
        Index("idx_email_verification_job_id", "job_id"),
        Index("idx_email_verification_created_at", "created_at"),
    )


class ResultCache(Base):
    """Cache for verification results to avoid re-verification."""
    __tablename__ = "result_cache"
    
    cache_key = Column(String, primary_key=True)  # email|mx_fingerprint
    email = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    
    result_data = Column(JSON, nullable=False)  # Serialized VerificationResult
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    
    __table_args__ = (
        Index("idx_cache_email", "email"),
        Index("idx_cache_domain", "domain"),
        Index("idx_cache_expires_at", "expires_at"),
    )


class APIKey(Base):
    """API key model for authentication."""
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String, nullable=False, unique=True)  # Hashed API key
    key_prefix = Column(String, nullable=False)  # First 8 chars for display
    
    name = Column(String, nullable=False)  # Human-readable name
    description = Column(Text, nullable=True)
    
    # Usage tracking
    requests_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    
    # Rate limiting
    rate_limit_per_minute = Column(Integer, default=60, nullable=False)
    rate_limit_per_hour = Column(Integer, default=1000, nullable=False)
    rate_limit_per_day = Column(Integer, default=10000, nullable=False)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration
    
    # Permissions (JSON list of allowed endpoints/actions)
    permissions = Column(JSON, nullable=False, default=list)
    
    __table_args__ = (
        Index("idx_api_key_hash", "key_hash"),
        Index("idx_api_key_active", "is_active"),
        Index("idx_api_key_created_at", "created_at"),
    )


class APIUsage(Base):
    """Track API usage for analytics and rate limiting."""
    __tablename__ = "api_usage"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    
    endpoint = Column(String, nullable=False)
    method = Column(String, nullable=False)  # GET, POST, etc.
    
    # Request details
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    # Response details
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=False)
    
    # Billing/usage
    emails_processed = Column(Integer, default=0, nullable=False)
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    api_key = relationship("APIKey")
    
    __table_args__ = (
        Index("idx_api_usage_key_id", "api_key_id"),
        Index("idx_api_usage_timestamp", "timestamp"),
        Index("idx_api_usage_endpoint", "endpoint"),
    )