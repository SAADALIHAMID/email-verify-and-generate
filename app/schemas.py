"""Pydantic schemas for request/response models."""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr
from app.models import VerificationStatus, ReasonCode, JobStatus


class VerificationResult(BaseModel):
    """Result of email verification."""
    email: str
    status: VerificationStatus
    reason_code: ReasonCode
    reasons: List[str] = Field(default_factory=list)
    
    # DNS information
    mx_records: List[str] = Field(default_factory=list)
    has_mx: bool = False
    
    # SMTP information
    smtp_transcript: List[str] = Field(default_factory=list)
    smtp_accepted: bool = False
    
    # Detection flags
    is_catch_all: bool = False
    is_role_based: bool = False
    is_disposable: bool = False
    
    # Timing
    verification_duration_ms: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class VerifyEmailRequest(BaseModel):
    """Request to verify a single email."""
    email: str = Field(..., description="Email address to verify")


class VerifyEmailResponse(BaseModel):
    """Response for single email verification."""
    result: VerificationResult


class BulkVerifyRequest(BaseModel):
    """Request for bulk email verification."""
    emails: List[str] = Field(..., description="List of email addresses to verify")


class JobCreateResponse(BaseModel):
    """Response when creating a bulk verification job."""
    job_id: str
    total_count: int
    message: str


class JobStats(BaseModel):
    """Job statistics and counts."""
    total_count: int = 0
    processed_count: int = 0
    deliverable_count: int = 0
    invalid_count: int = 0
    risky_count: int = 0
    unknown_count: int = 0
    disposable_count: int = 0
    
    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_count == 0:
            return 0.0
        return (self.processed_count / self.total_count) * 100


class JobResponse(BaseModel):
    """Response for job status and metadata."""
    job_id: str
    status: JobStatus
    stats: JobStats
    
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    
    error_message: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class JobResultsResponse(BaseModel):
    """Response for paginated job results."""
    job_id: str
    results: List[VerificationResult]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime
    version: str
    database: str
    redis: str
    worker: str
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ExportFormat(str):
    """Export format enumeration."""
    ALL_CSV = "all.csv"
    DELIVERABLE_TXT = "deliverable.txt"
    INVALID_CSV = "invalid.csv"


class MetricsResponse(BaseModel):
    """Metrics response."""
    processed_total: int
    deliverable_total: int
    invalid_total: int
    risky_total: int
    unknown_total: int
    disposable_total: int
    
    # Per-status breakdown
    status_breakdown: Dict[str, int]
    
    # Recent activity (last 24h)
    recent_verifications: int
    recent_jobs: int
    
    # Cache statistics
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float


class DomainStats(BaseModel):
    """Domain-specific statistics."""
    domain: str
    total_verifications: int
    deliverable_count: int
    invalid_count: int
    risky_count: int
    unknown_count: int
    disposable_count: int
    
    deliverable_rate: float
    last_verified: Optional[datetime] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }