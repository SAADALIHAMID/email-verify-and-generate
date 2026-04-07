"""API Key authentication and authorization system."""

import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from .models import APIKey, APIUsage
from .config import settings


class APIKeyAuth:
    """API Key authentication handler."""
    
    def __init__(self):
        self.security = HTTPBearer()
    
    @staticmethod
    def generate_api_key() -> tuple[str, str]:
        """Generate a new API key and its hash.
        
        Returns:
            tuple: (api_key, key_hash)
        """
        # Generate 32 random bytes, encode as hex
        api_key = f"evs_{secrets.token_hex(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return api_key, key_hash
    
    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Hash an API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    @staticmethod
    def get_key_prefix(api_key: str) -> str:
        """Get the first 8 characters for display purposes."""
        return api_key[:12] + "..."
    
    async def verify_api_key(
        self,
        request: Request,
        db: AsyncSession,
        credentials: Optional[HTTPAuthorizationCredentials] = None
    ) -> APIKey:
        """Verify API key from Authorization header or X-API-Key header."""
        
        # Try to get API key from different sources
        api_key = None
        
        # 1. From Authorization: Bearer token
        if credentials and credentials.scheme.lower() == "bearer":
            api_key = credentials.credentials
        
        # 2. From X-API-Key header
        if not api_key:
            api_key = request.headers.get("X-API-Key")
        
        # 3. From x-api-key header (case insensitive)
        if not api_key:
            api_key = request.headers.get("x-api-key")
        
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="API key required. Provide via 'Authorization: Bearer <key>' or 'X-API-Key: <key>' header"
            )
        
        # Hash the provided key
        key_hash = self.hash_api_key(api_key)
        
        # Look up the API key in database
        result = await db.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        api_key_obj = result.scalar_one_or_none()
        
        if not api_key_obj:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        if not api_key_obj.is_active:
            raise HTTPException(status_code=401, detail="API key is disabled")
        
        # Check expiration
        if api_key_obj.expires_at and api_key_obj.expires_at < datetime.utcnow():
            raise HTTPException(status_code=401, detail="API key has expired")
        
        # Update last used timestamp and increment request count
        await db.execute(
            update(APIKey)
            .where(APIKey.id == api_key_obj.id)
            .values(
                last_used_at=datetime.utcnow(),
                requests_count=APIKey.requests_count + 1
            )
        )
        
        return api_key_obj
    
    async def check_rate_limit(
        self,
        api_key: APIKey,
        db: AsyncSession,
        emails_count: int = 1
    ) -> None:
        """Check if API key has exceeded rate limits."""
        
        now = datetime.utcnow()
        
        # Check minute limit
        minute_ago = now - timedelta(minutes=1)
        result = await db.execute(
            select(APIUsage)
            .where(
                APIUsage.api_key_id == api_key.id,
                APIUsage.timestamp >= minute_ago
            )
        )
        recent_usage = result.scalars().all()
        minute_requests = len(recent_usage)
        minute_emails = sum(usage.emails_processed for usage in recent_usage)
        
        if minute_requests >= api_key.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {api_key.rate_limit_per_minute} requests per minute"
            )
        
        # Check hour limit
        hour_ago = now - timedelta(hours=1)
        result = await db.execute(
            select(APIUsage)
            .where(
                APIUsage.api_key_id == api_key.id,
                APIUsage.timestamp >= hour_ago
            )
        )
        hour_usage = result.scalars().all()
        hour_requests = len(hour_usage)
        
        if hour_requests >= api_key.rate_limit_per_hour:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {api_key.rate_limit_per_hour} requests per hour"
            )
        
        # Check day limit
        day_ago = now - timedelta(days=1)
        result = await db.execute(
            select(APIUsage)
            .where(
                APIUsage.api_key_id == api_key.id,
                APIUsage.timestamp >= day_ago
            )
        )
        day_usage = result.scalars().all()
        day_requests = len(day_usage)
        
        if day_requests >= api_key.rate_limit_per_day:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {api_key.rate_limit_per_day} requests per day"
            )
    
    async def log_api_usage(
        self,
        api_key: APIKey,
        request: Request,
        response_status: int,
        response_time_ms: float,
        emails_processed: int,
        db: AsyncSession
    ) -> None:
        """Log API usage for analytics."""
        
        usage = APIUsage(
            api_key_id=api_key.id,
            endpoint=str(request.url.path),
            method=request.method,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            status_code=response_status,
            response_time_ms=response_time_ms,
            emails_processed=emails_processed,
            timestamp=datetime.utcnow()
        )
        
        db.add(usage)
        await db.commit()
    
    def check_permissions(
        self,
        api_key: APIKey,
        endpoint: str,
        method: str = "GET"
    ) -> bool:
        """Check if API key has permission for specific endpoint."""
        
        # If no permissions specified, allow all
        if not api_key.permissions:
            return True
        
        # Check specific permissions
        permission_key = f"{method.upper()}:{endpoint}"
        return permission_key in api_key.permissions or "*" in api_key.permissions


# Global instance
api_auth = APIKeyAuth()


async def get_current_api_key(
    request: Request,
    db
) -> APIKey:
    """Dependency to get current authenticated API key."""
    from fastapi.security import HTTPBearer
    security = HTTPBearer()
    
    # Try to get credentials
    try:
        from fastapi import Depends
        # This is a simplified version - in practice, use the verify_api_key method
        return await api_auth.verify_api_key(request, db)
    except Exception:
        # Fallback to direct header parsing
        api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required")
        
        key_hash = api_auth.hash_api_key(api_key)
        result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
        api_key_obj = result.scalar_one_or_none()
        
        if not api_key_obj or not api_key_obj.is_active:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        return api_key_obj


async def require_api_key(
    request: Request
) -> str:
    """Dependency that extracts and validates API key format. Allows localhost bypass for development."""
    
    # Allow localhost bypass for development
    client_ip = request.client.host if request.client else None
    if client_ip in ['127.0.0.1', 'localhost', '::1']:
        # Return a dummy key for localhost connections
        return "evs_localhost_development_bypass_00000000000000000000000000000000"
    
    # Try different header formats
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header[7:]  # Remove "Bearer " prefix
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide via 'X-API-Key' header or 'Authorization: Bearer' header"
        )
    
    # Basic format validation
    if not api_key.startswith("evs_") or len(api_key) != 68:
        raise HTTPException(status_code=401, detail="Invalid API key format")
    
    return api_key


async def validate_api_key_with_db(api_key_str: str, db: AsyncSession, request: Request) -> APIKey:
    """Validate API key with database and check permissions/rate limits. Allows localhost bypass for development."""
    
    # Allow localhost bypass for development
    client_ip = request.client.host if request.client else None
    if client_ip in ['127.0.0.1', 'localhost', '::1']:
        # Return a mock API key object for localhost
        return APIKey(
            id="localhost",
            name="Localhost Development",
            key_hash="localhost",
            is_active=True,
            rate_limit_per_hour=10000,
            rate_limit_per_day=100000,
            requests_count=0,
            last_used_at=None,
            expires_at=None,
            created_at=datetime.utcnow(),
            permissions=["*"]
        )
    
    # Hash the API key for database lookup
    key_hash = hashlib.sha256(api_key_str.encode()).hexdigest()
    
    # Look up the API key in database
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash)
    )
    api_key_obj = result.scalar_one_or_none()
    
    if not api_key_obj:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not api_key_obj.is_active:
        raise HTTPException(status_code=401, detail="API key is disabled")
    
    # Check expiration
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key has expired")
    
    # Check permissions
    if not api_auth.check_permissions(api_key_obj, request.url.path, request.method):
        raise HTTPException(
            status_code=403,
            detail="API key does not have permission for this endpoint"
        )
    
    # Check rate limits
    await api_auth.check_rate_limit(api_key_obj, db)
    
    # Update last used timestamp and increment request count
    await db.execute(
        update(APIKey)
        .where(APIKey.id == api_key_obj.id)
        .values(
            last_used_at=datetime.utcnow(),
            requests_count=APIKey.requests_count + 1
        )
    )
    
    return api_key_obj
