"""Basic metrics collection and reporting for email verification system."""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from collections import defaultdict, deque
import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collect and store metrics for the email verification system."""
    
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._connected = False
        
        # In-memory counters (fallback if Redis unavailable)
        self._counters = defaultdict(int)
        self._timings = defaultdict(deque)
        self._last_reset = time.time()
    
    async def connect(self) -> bool:
        """Connect to Redis for metrics storage."""
        try:
            self._redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            await self._redis.ping()
            self._connected = True
            logger.info("Connected to Redis for metrics")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to connect to Redis for metrics: {e}")
            self._connected = False
            return False
    
    async def increment_counter(self, metric_name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        try:
            if self._connected and self._redis:
                # Store in Redis with timestamp
                key = f"metrics:counter:{metric_name}"
                if tags:
                    tag_str = ','.join(f"{k}={v}" for k, v in sorted(tags.items()))
                    key = f"{key}:{tag_str}"
                
                await self._redis.hincrby(key, "value", value)  # type: ignore
                await self._redis.hset(key, "last_updated", str(int(time.time())))  # type: ignore
                await self._redis.expire(key, 86400 * 7)  # 7 days TTL
            else:
                # Fallback to in-memory
                self._counters[metric_name] += value
                
        except Exception as e:
            logger.error(f"Error incrementing counter {metric_name}: {e}")
            # Fallback to in-memory
            self._counters[metric_name] += value
    
    async def record_timing(self, metric_name: str, duration_ms: int, tags: Optional[Dict[str, str]] = None):
        """Record a timing metric."""
        try:
            if self._connected:
                # Store timing in Redis sorted set for percentile calculations
                key = f"metrics:timing:{metric_name}"
                if tags:
                    tag_str = ','.join(f"{k}={v}" for k, v in sorted(tags.items()))
                    key = f"{key}:{tag_str}"
                
                timestamp = time.time()
                if self._redis:
                    await self._redis.zadd(key, {str(timestamp): duration_ms})  # type: ignore
                    await self._redis.expire(key, 86400)  # 1 day TTL for timings
            else:
                # Fallback to in-memory (keep last 1000 values)
                if len(self._timings[metric_name]) >= 1000:
                    self._timings[metric_name].popleft()
                self._timings[metric_name].append(duration_ms)
                
        except Exception as e:
            logger.error(f"Error recording timing {metric_name}: {e}")
            # Fallback to in-memory
            if len(self._timings[metric_name]) >= 1000:
                self._timings[metric_name].popleft()
            self._timings[metric_name].append(duration_ms)
    
    async def get_counter_value(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """Get current counter value."""
        try:
            if self._connected:
                key = f"metrics:counter:{metric_name}"
                if tags:
                    tag_str = ','.join(f"{k}={v}" for k, v in sorted(tags.items()))
                    key = f"{key}:{tag_str}"
                
                if self._redis:
                    value = await self._redis.hget(key, "value")  # type: ignore
                    return int(value) if value else 0
                else:
                    return self._counters.get(metric_name, 0)
            else:
                return self._counters.get(metric_name, 0)
                
        except Exception as e:
            logger.error(f"Error getting counter {metric_name}: {e}")
            return self._counters.get(metric_name, 0)
    
    async def get_timing_stats(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        """Get timing statistics (avg, min, max, p95, p99)."""
        try:
            if self._connected:
                key = f"metrics:timing:{metric_name}"
                if tags:
                    tag_str = ','.join(f"{k}={v}" for k, v in sorted(tags.items()))
                    key = f"{key}:{tag_str}"
                
                # Get all timings from last 24 hours
                yesterday = time.time() - 86400
                if self._redis:
                    timings = await self._redis.zrangebyscore(key, yesterday, '+inf')  # type: ignore
                
                if not timings:
                    return {}
                
                values = [float(t) for t in timings]
            else:
                values = list(self._timings.get(metric_name, []))
                
            if not values:
                return {}
            
            values.sort()
            count = len(values)
            
            return {
                'count': count,
                'avg': sum(values) / count,
                'min': values[0],
                'max': values[-1],
                'p50': values[int(count * 0.5)],
                'p95': values[int(count * 0.95)],
                'p99': values[int(count * 0.99)]
            }
            
        except Exception as e:
            logger.error(f"Error getting timing stats {metric_name}: {e}")
            return {}
    
    async def get_all_metrics(self) -> Dict[str, Any]:
        """Get all collected metrics."""
        metrics = {
            'counters': {},
            'timings': {},
            'timestamp': datetime.utcnow().isoformat()
        }
        
        try:
            if self._connected:
                # Get all counter keys
                if self._redis:
                    counter_keys = await self._redis.keys("metrics:counter:*")  # type: ignore
                    for key in counter_keys:
                        metric_name = key.replace("metrics:counter:", "")
                        value = await self._redis.hget(key, "value")  # type: ignore
                        metrics['counters'][metric_name] = int(value) if value else 0
                
                # Get timing stats for common metrics
                if self._redis:
                    timing_keys = await self._redis.keys("metrics:timing:*")  # type: ignore
                processed_timings = set()
                
                for key in timing_keys:
                    metric_name = key.replace("metrics:timing:", "")
                    # Remove tag suffixes for grouping
                    base_name = metric_name.split(':')[0]
                    
                    if base_name not in processed_timings:
                        stats = await self.get_timing_stats(base_name)
                        if stats:
                            metrics['timings'][base_name] = stats
                        processed_timings.add(base_name)
            else:
                # Use in-memory data
                metrics['counters'] = dict(self._counters)
                
                for metric_name, values in self._timings.items():
                    if values:
                        values_list = list(values)
                        values_list.sort()
                        count = len(values_list)
                        
                        metrics['timings'][metric_name] = {
                            'count': count,
                            'avg': sum(values_list) / count,
                            'min': values_list[0],
                            'max': values_list[-1],
                            'p95': values_list[int(count * 0.95)] if count > 0 else 0,
                            'p99': values_list[int(count * 0.99)] if count > 0 else 0
                        }
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting all metrics: {e}")
            return metrics


# Global metrics collector
metrics = MetricsCollector()


# Convenience functions for common metrics
async def record_verification_start():
    """Record that a verification started."""
    await metrics.increment_counter("verifications_started")


async def record_verification_complete(status: str, duration_ms: int):
    """Record verification completion."""
    await metrics.increment_counter("verifications_completed")
    await metrics.increment_counter("verifications_by_status", tags={"status": status})
    await metrics.record_timing("verification_duration", duration_ms)


async def record_api_request(method: str, endpoint: str, status_code: int, duration_ms: int):
    """Record API request metrics."""
    await metrics.increment_counter("api_requests_total")
    await metrics.increment_counter("api_requests_by_method", tags={"method": method})
    await metrics.increment_counter("api_requests_by_status", tags={"status": str(status_code)})
    await metrics.record_timing("api_request_duration", duration_ms, tags={"endpoint": endpoint})


async def record_job_created(email_count: int):
    """Record job creation."""
    await metrics.increment_counter("jobs_created")
    await metrics.increment_counter("emails_queued", email_count)


async def record_job_completed(job_id: str, email_count: int, duration_ms: int):
    """Record job completion."""
    await metrics.increment_counter("jobs_completed")
    await metrics.increment_counter("emails_processed", email_count)
    await metrics.record_timing("job_duration", duration_ms)


async def record_cache_hit():
    """Record cache hit."""
    await metrics.increment_counter("cache_hits")


async def record_cache_miss():
    """Record cache miss."""
    await metrics.increment_counter("cache_misses")


async def record_dns_lookup(success: bool, duration_ms: int):
    """Record DNS lookup metrics."""
    status = "success" if success else "failure"
    await metrics.increment_counter("dns_lookups", tags={"status": status})
    await metrics.record_timing("dns_lookup_duration", duration_ms)


async def record_smtp_connection(success: bool, duration_ms: int):
    """Record SMTP connection metrics."""
    status = "success" if success else "failure"
    await metrics.increment_counter("smtp_connections", tags={"status": status})
    await metrics.record_timing("smtp_connection_duration", duration_ms)


async def get_system_metrics() -> Dict[str, Any]:
    """Get comprehensive system metrics."""
    if not metrics._connected:
        await metrics.connect()
    
    all_metrics = await metrics.get_all_metrics()
    
    # Calculate derived metrics
    counters = all_metrics.get('counters', {})
    
    # Cache hit rate
    cache_hits = counters.get('cache_hits', 0)
    cache_misses = counters.get('cache_misses', 0)
    total_cache_requests = cache_hits + cache_misses
    cache_hit_rate = (cache_hits / total_cache_requests * 100) if total_cache_requests > 0 else 0
    
    # Success rates
    verifications_completed = counters.get('verifications_completed', 0)
    deliverable = counters.get('verifications_by_status:status=DELIVERABLE', 0)
    invalid = counters.get('verifications_by_status:status=INVALID', 0)
    
    success_rate = (deliverable / verifications_completed * 100) if verifications_completed > 0 else 0
    
    # Add derived metrics
    all_metrics['derived'] = {
        'cache_hit_rate': cache_hit_rate,
        'verification_success_rate': success_rate,
        'total_cache_requests': total_cache_requests,
        'total_verifications': verifications_completed
    }
    
    return all_metrics


class MetricsMiddleware:
    """Middleware to automatically collect API metrics."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        
        # Wrap send to capture response
        status_code = 500  # Default to error
        
        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
        
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Record metrics
            duration_ms = int((time.time() - start_time) * 1000)
            method = scope.get("method", "UNKNOWN")
            path = scope.get("path", "/")
            
            # Normalize path (remove IDs, etc.)
            normalized_path = self._normalize_path(path)
            
            await record_api_request(method, normalized_path, status_code, duration_ms)
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for metrics (remove variable parts)."""
        # Replace UUIDs and IDs with placeholders
        import re
        
        # Replace UUIDs
        path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/{id}', path)
        
        # Replace numeric IDs
        path = re.sub(r'/\d+', '/{id}', path)
        
        return path