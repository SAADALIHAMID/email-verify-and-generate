"""In-memory caching for verification results using fakeredis."""

import json
import logging
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any
# Hamein asli redis ki jagah fakeredis chahiye
from fakeredis import aioredis 
from app.config import settings
from app.schemas import VerificationResult
from app.models import VerificationStatus, ReasonCode

logger = logging.getLogger(__name__)

class VerificationCache:
    """In-memory cache for email verification results (No Redis Server Required)."""
    
    def __init__(self):
        # Hum direct FakeRedis use karenge jo memory mein chalega
        self._redis = aioredis.FakeRedis(decode_responses=True)
        self._connected = True # FakeRedis hamesha connected hota hai
    
    async def connect(self) -> bool:
        """Fake connection (Always returns True)."""
        self._connected = True
        logger.info("Using In-Memory FakeRedis cache (No server needed)")
        return True
    
    async def disconnect(self):
        """No-op disconnect."""
        self._connected = False
        logger.info("Disconnected from FakeRedis cache")

    def _generate_cache_key(self, email: str, domain: str) -> str:
        key_data = f"{email.lower()}|{domain.lower()}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"email_verify:{key_hash}"
    
    def _generate_domain_key(self, domain: str) -> str:
        return f"domain:{domain.lower()}"

    async def get(self, email: str, domain: str) -> Optional[VerificationResult]:
        try:
            cache_key = self._generate_cache_key(email, domain)
            cached_data = await self._redis.get(cache_key)
            
            if cached_data:
                data = json.loads(cached_data)
                result = VerificationResult(
                    email=data['email'],
                    status=VerificationStatus(data['status']),
                    reason_code=ReasonCode(data['reason_code']),
                    reasons=data['reasons'],
                    mx_records=data['mx_records'],
                    has_mx=data['has_mx'],
                    smtp_transcript=data['smtp_transcript'],
                    smtp_accepted=data['smtp_accepted'],
                    is_catch_all=data['is_catch_all'],
                    is_role_based=data['is_role_based'],
                    is_disposable=data['is_disposable'],
                    verification_duration_ms=data.get('verification_duration_ms'),
                    timestamp=datetime.fromisoformat(data['timestamp'])
                )
                logger.debug(f"Cache hit for {email}")
                return result
            return None
        except Exception as e:
            logger.error(f"Error getting cached result: {e}")
            return None

    async def set(self, email: str, domain: str, result: VerificationResult) -> bool:
        try:
            cache_key = self._generate_cache_key(email, domain)
            data = {
                'email': result.email,
                'status': result.status.value,
                'reason_code': result.reason_code.value,
                'reasons': result.reasons,
                'mx_records': result.mx_records,
                'has_mx': result.has_mx,
                'smtp_transcript': result.smtp_transcript,
                'smtp_accepted': result.smtp_accepted,
                'is_catch_all': result.is_catch_all,
                'is_role_based': result.is_role_based,
                'is_disposable': result.is_disposable,
                'verification_duration_ms': result.verification_duration_ms,
                'timestamp': result.timestamp.isoformat()
            }
            # Set memory cache
            await self._redis.set(cache_key, json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Error caching result: {e}")
            return False

    async def get_cache_stats(self) -> Dict[str, Any]:
        return {'connected': True, 'type': 'fakeredis-memory'}

    async def clear_all(self) -> bool:
        await self._redis.flushall()
        return True

# Global cache instance
cache = VerificationCache()

# Convenience functions
async def get_cached_result(email: str, domain: str): return await cache.get(email, domain)
async def cache_result(email: str, domain: str, result: VerificationResult): return await cache.set(email, domain, result)
async def get_cache_statistics(): return await cache.get_cache_stats()
async def clear_cache(): return await cache.clear_all()