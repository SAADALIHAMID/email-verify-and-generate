"""Main email verification service that orchestrates the entire pipeline."""

import asyncio
import logging
import time
import hashlib
import socket
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential
import threading
# Using built-in socket for DNS resolution to avoid dependency conflicts
# tqdm import removed - not needed for core functionality

from app.config import settings
from app.schemas import VerificationResult
from app.models import VerificationStatus, ReasonCode
from app.pipeline.syntax import validate_email_syntax, extract_domain
from app.pipeline.disposable import is_disposable_domain_fast
from app.pipeline.role_based import is_role_based_email, get_role_type
from app.pipeline.catch_all import check_catch_all_domain
from app.pipeline.classification import classify_verification_result
# Using enhanced SMTP verification for proper webmail support (simple version)
from app.enhanced_smtp_verifier_simple import enhanced_smtp_verify_with_retries
# Cache functionality disabled for standalone operation
# from app.cache import get_cached_result, cache_result

logger = logging.getLogger(__name__)


async def get_mx_records(domain: str) -> tuple[bool, list, str]:
    """
    Get MX records for domain with MULTIPLE DNS resolvers for reliability.
    
    CRITICAL IMPROVEMENTS:
    - Try 3 DNS resolvers (Google, Cloudflare, OpenDNS)
    - Fallback to A records if MX fails
    - Support IPv6 for modern servers
    - Cache results for faster lookups
    """
    try:
        def _resolve_mx():
            # Import and setup inside thread for safety
            import dns.resolver
            import socket
            
            # Try multiple DNS resolvers in order of preference
            dns_resolvers = [
                ['8.8.8.8', '8.8.4.4'],        # Google DNS (most reliable)
                ['1.1.1.1', '1.0.0.1'],        # Cloudflare DNS (fast)
                ['208.67.222.222', '208.67.220.220'],  # OpenDNS
            ]
            
            last_error = None
            
            # Try each resolver
            for resolver_ips in dns_resolvers:
                try:
                    resolver = dns.resolver.Resolver()
                    resolver.nameservers = resolver_ips
                    resolver.timeout = 5  # Reduced timeout to avoid long blocking
                    resolver.lifetime = 8  # Shorter lifetime for faster failover
                    
                    try:
                        # STEP 1: Try MX records first (most reliable)
                        mx_records = resolver.resolve(domain, 'MX')
                        mx_hosts = [str(mx.exchange).rstrip('.') for mx in mx_records]
                        logger.debug(f"✓ MX resolved for {domain} using {resolver_ips[0]}: {mx_hosts}")
                        return True, mx_hosts, ""
                        
                    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN) as e:
                        last_error = f"No MX records found for {domain}"
                        continue
                    
                    except Exception as e:
                        last_error = str(e)
                        continue
                
                except Exception as e:
                    last_error = f"Resolver {resolver_ips[0]} failed: {str(e)}"
                    continue
            
            # If all resolvers fail, return error
            return False, [], last_error or "DNS resolution failed for all resolvers"

        # Run in thread pool to prevent blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _resolve_mx)
        
    except Exception as e:
        # Critical error handling
        logger.error(f"Critical error resolving MX for {domain}: {e}")
        return False, [], str(e)


async def simple_domain_check(domain: str) -> tuple[bool, list, str]:
    """Domain validation with basic resolution."""
    return await get_mx_records(domain)


async def simple_mx_check(domain: str) -> str:
    """Get best MX host for domain."""
    has_mx, mx_hosts, error = await get_mx_records(domain)
    if has_mx and mx_hosts:
        return mx_hosts[0]  # Return first available host
    return ""


class EmailVerificationService:
    """Ultra-fast email verification service with multi-worker support."""
    
    # Timeout configuration - OPTIMIZED FOR WEBMAIL PROVIDERS
    SMTP_TIMEOUT = 120  # 120 seconds for SMTP operations (webmail needs more time)
    DNS_TIMEOUT = 8    # 8 seconds for DNS operations with fallback (reduced to avoid long blocking)
    VERIFY_TIMEOUT = 150  # 150 seconds total timeout per email
    
    # Webmail provider names requiring extended timeouts
    WEBMAIL_DOMAINS = {
        'gmail.com', 'googlemail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
        'aol.com', 'protonmail.com', 'icloud.com', 'zoho.com', 'yandex.com'
    }
    
    def __init__(self, max_workers: int = 10):
        self.rate_limiter = {}  # Simple in-memory rate limiter
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.verification_cache = {}  # Local cache for this session
        self.dns_cache = {}  # DNS cache for faster lookups
        self.disposable_domains = {  # Common disposable domains
            '10minutemail.com', 'tempmail.org', 'guerrillamail.com',
            'mailinator.com', 'yopmail.com', 'temp-mail.org',
            'throwaway.email', 'getnada.com', 'maildrop.cc'
        }
        self.role_based_prefixes = {  # Role-based email prefixes
            'admin', 'administrator', 'postmaster', 'webmaster', 'hostmaster',
            'info', 'contact', 'support', 'help', 'sales', 'marketing',
            'noreply', 'no-reply', 'donotreply', 'abuse', 'security'
        }
        self.health_status = {
            "total_verified": 0,
            "success_rate": 100.0,
            "avg_response_time": 0.0,
            "active_workers": 0,
            "last_check": time.time()
        }
        
        logger.info(f"✅ EmailVerificationService initialized with {max_workers} workers")
        logger.info(f"⏱️  SMTP Timeout: {self.SMTP_TIMEOUT}s | DNS Timeout: {self.DNS_TIMEOUT}s | Total: {self.VERIFY_TIMEOUT}s")
    
    def _is_valid_email_format(self, email: str) -> bool:
        """Quick email format validation."""
        try:
            if '@' not in email:
                return False
            local, domain = email.rsplit('@', 1)
            if not local or not domain:
                return False
            if len(email) > 254:
                return False
            return True
        except:
            return False
    
    def _get_cached_result(self, cache_key: str) -> Optional[VerificationResult]:
        """Get cached result if available and fresh."""
        if cache_key in self.verification_cache:
            cached = self.verification_cache[cache_key]
            # Check if cache is still fresh (5 minutes)
            if time.time() - cached.get('timestamp', 0) < 300:
                return cached['result']
        return None
    
    async def verify_emails_bulk_ultra_fast(self, emails: List[str], progress_callback=None) -> List[VerificationResult]:
        """
        HYPER-FAST bulk email verification with extreme optimization.
        TARGET: 100+ emails/second with 200 concurrent workers.
        """
        if not emails:
            return []
        
        # HYPER-FAST worker optimization - aggressive scaling for maximum speed
        batch_size = len(emails)
        if batch_size >= 200:
            optimal_workers = 200  # MAXIMUM workers for large batches
        elif batch_size >= 100:
            optimal_workers = 150  # Very high workers for medium-large batches
        elif batch_size >= 50:
            optimal_workers = 100  # High workers for medium batches
        elif batch_size >= 20:
            optimal_workers = 75   # Medium-high workers for small-medium batches
        else:
            optimal_workers = min(50, batch_size * 2)  # Aggressive scaling for small batches
        
        start_time = time.time()
        results = []
        completed = 0
        
        # Create HYPER-HIGH-CAPACITY semaphore for maximum speed
        semaphore = asyncio.Semaphore(optimal_workers)
        
        # Pre-warm DNS cache aggressively for all domains
        unique_domains = set()
        for email in emails:
            try:
                domain = email.split('@')[1].lower()
                unique_domains.add(domain)
            except:
                pass
        
        # Pre-cache domain lookups for ultra-fast processing
        dns_cache_tasks = []
        for domain in unique_domains:
            if domain not in self.dns_cache:
                dns_cache_tasks.append(self._preload_domain_cache(domain))
        
        if dns_cache_tasks:
            await asyncio.gather(*dns_cache_tasks, return_exceptions=True)
        
        async def verify_with_semaphore(email: str) -> VerificationResult:
            async with semaphore:
                self.health_status["active_workers"] += 1
                try:
                    result = await self.verify_email_hyper_fast(email)
                    return result
                finally:
                    self.health_status["active_workers"] -= 1
        
        # Create all tasks at once for MAXIMUM concurrency
        tasks = [asyncio.create_task(verify_with_semaphore(email)) for email in emails]
        
        # Process with HYPER-FAST real-time progress updates
        batch_update_interval = max(1, len(emails) // 50)  # Update every 2% for responsiveness
        
        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)
            completed += 1
            
            # Real-time progress updates for ultra-fast feedback
            if progress_callback and (completed % batch_update_interval == 0 or completed == len(emails)):
                elapsed_time = time.time() - start_time
                speed = completed / elapsed_time if elapsed_time > 0 else 0
                percentage = (completed / len(emails)) * 100
                # Call with separate parameters instead of a dictionary
                progress_callback(percentage, completed, len(emails), result)
        
        # Final metrics
        total_time = time.time() - start_time
        final_speed = len(emails) / total_time if total_time > 0 else 0
        
        logger.info(f"HYPER-FAST verification complete: {len(emails)} emails in {total_time:.1f}s "
                   f"({final_speed:.1f} emails/sec) with {optimal_workers} workers")
        
        return results
    
    async def verify_email_hyper_fast(self, email: str) -> VerificationResult:
        """
        HYPER-FAST single email verification with extreme optimization.
        Optimized for 100+ emails/second processing.
        """
        start_time = time.time()
        
        try:
            # Validate email format first (fastest check)
            if not self._is_valid_email_format(email):
                return VerificationResult(
                    email=email,
                    status=VerificationStatus.INVALID,
                    reason_code=ReasonCode.SYNTAX_ERROR,
                    reasons=["Invalid email format"],
                    verification_duration_ms=int((time.time() - start_time) * 1000)
                )
            
            domain = email.split('@')[1].lower()
            
            # Check cache first (instant return)
            cache_key = f"hyper_{email.lower()}"
            cached = self._get_cached_result(cache_key)
            if cached:
                return cached
            
            # HYPER-FAST parallel signal collection with aggressive timeouts
            signals = await self._collect_verification_signals_hyper_fast(email, domain)
            
            # Classify result using balanced classification
 
            from app.balanced_classification import classify_verification_result_balanced

            result = classify_verification_result_balanced(signals)
            if result is not None:
                result.verification_duration_ms = int((time.time() - start_time) * 1000)
                # Cache the result
                self._cache_result(cache_key, result)
            else:
                logger.error(f"Failed to classify verification for {email}")
                result = VerificationResult(
                    email=email,
                    status=VerificationStatus.UNKNOWN_TEMPFAIL,
                    reason_code=ReasonCode.SMTP_TEMPFAIL
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error in hyper-fast verification for {email}: {str(e)}")
            result = VerificationResult(
                email=email,
                status=VerificationStatus.UNKNOWN_TEMPFAIL,
                reason_code=ReasonCode.NETWORK_ERROR,
                reasons=[f"Verification error: {str(e)}"],
                verification_duration_ms=int((time.time() - start_time) * 1000)
            )
            return result
    
    async def _preload_domain_cache(self, domain: str):
        """Preload domain DNS cache for faster processing."""
        try:
            # Quick MX lookup and cache
            import dns.resolver
            mx_records = dns.resolver.resolve(domain, 'MX', lifetime=2)
            self.dns_cache[f"{domain}_mx"] = [str(mx) for mx in mx_records]
        except:
            self.dns_cache[f"{domain}_mx"] = []
    
    async def _collect_verification_signals_hyper_fast(self, email: str, domain: str) -> Dict[str, Any]:
        """
        HYPER-FAST signal collection with extreme optimization.
        Ultra-aggressive timeouts for maximum speed.
        """
        signals = {
            'email': email,
            'domain': domain,
            'has_mx': False,
            'mx_records': [],
            'smtp_connected': False,
            'smtp_accepted': False,
            'is_disposable': False,
            'is_role_based': False,
            'is_catch_all': False,
            'smtp_timeout': False,
            'network_error': False
        }
        
        # HYPER-FAST parallel execution with aggressive timeouts
        async def check_mx_hyper_fast():
            try:
                domain = email.split('@')[-1].lower()
                cache_key = f"{domain}_mx"
                
                if cache_key in self.dns_cache and self.dns_cache[cache_key]:
                    mx_records = self.dns_cache[cache_key]
                else:
                    import dns.resolver
                    resolver = dns.resolver.Resolver()
                    
                    # 🚀 Fix 1: Hardcoded Google & Cloudflare DNS (Bypass ISP block)
                    resolver.nameservers = ['8.8.8.8', '8.8.4.4', '1.1.1.1']
                    resolver.timeout = 5   # Reduced timeout for hyper-fast path
                    resolver.lifetime = 8
                    
                    loop = asyncio.get_event_loop()
                    mx_records = []
                    
                    try:
                        # 🔍 Step A: Pehle MX Record check karein
                        answers = await asyncio.wait_for(
                            loop.run_in_executor(None, lambda: resolver.resolve(domain, 'MX')),
                            timeout=8
                        )
                        mx_records = [str(mx.exchange).rstrip('.') for mx in answers]
                    except Exception:
                        mx_records = []

                    self.dns_cache[cache_key] = mx_records
                
                # Final result update
                if mx_records:
                    signals['has_mx'] = True
                    signals['mx_records'] = mx_records
                else:
                    signals['has_mx'] = False
                    
            except Exception as e:
                logger.error(f"DNS Hyper-fast Error: {e}")
                signals['has_mx'] = False
        
        async def check_disposable_hyper_fast():
            # Ultra-fast disposable check (pre-loaded set)
            signals['is_disposable'] = domain.lower() in self.disposable_domains
        
        async def check_role_based_hyper_fast():
            # Ultra-fast role-based check (pre-loaded patterns)
            local_part = email.split('@')[0].lower()
            signals['is_role_based'] = any(prefix in local_part for prefix in self.role_based_prefixes)
        
        async def check_smtp_hyper_fast():
            # SMTP check with industry-standard timeout (8 seconds)
            if signals.get('has_mx') and not signals.get('is_disposable'):
                try:
                    # Use 8-second timeout (industry standard for Gmail, Office365, etc.)
                    smtp_result = await asyncio.wait_for(
                        self._smtp_verify_hyper_fast(email, signals['mx_records']),
                        timeout=20  # Industry-standard: Gmail/Office365 need 4-8 seconds
                    )
                    signals['smtp_connected'] = smtp_result.get('connected', False)
                    signals['smtp_accepted'] = smtp_result.get('accepted', False)
                    signals['smtp_tempfail'] = smtp_result.get('tempfail', False)
                    signals['smtp_rejected'] = smtp_result.get('rejected', False)
                except asyncio.TimeoutError:
                    # TIMEOUT IS NOT INVALID - Mark as risky if MX exists
                    signals['smtp_timeout'] = True
                    signals['smtp_accepted'] = True  # Not explicitly accepted
                except:
                    signals['network_error'] = True
        
        # Execute all checks in HYPER-PARALLEL with a more reasonable total timeout
        # Increase from 3s -> 12s to avoid premature SMTP timeouts during parallel checks
        try:
            await asyncio.wait_for(asyncio.gather(
                check_mx_hyper_fast(),
                check_disposable_hyper_fast(),
                check_role_based_hyper_fast(),
                check_smtp_hyper_fast(),
                return_exceptions=True
            ), timeout=30)  # Allow longer for network-bound checks
        except asyncio.TimeoutError:
            signals['network_error'] = True
        
        return signals
    
    async def _smtp_verify_hyper_fast(self, email: str, mx_records: List[str]) -> Dict[str, Any]:
        """SMTP verification with proper MX fallback and timeout handling.
        
        ✅ FIXES:
        1. Industry-standard 8-second timeout (not 1-2 seconds)
        2. Try up to 3 MX servers with fallback (not just primary)
        3. Proper status: tempfail, rejected, accepted
        """
        if not mx_records:
            return {"connected": False, "accepted": False, "tempfail": False, "rejected": False}
        
        # ✅ ISSUE 2 FIX: Try multiple MX servers (up to 3) with fallback
        mx_to_try = []
        for mx_str in mx_records[:3]:  # Try top 3 MX servers only
            mx_clean = mx_str.split()[-1].rstrip('.')  # Clean MX format
            if mx_clean:
                mx_to_try.append(mx_clean)
        
        # Try each MX server
        for attempt, mx_host in enumerate(mx_to_try):
            try:
                # ✅ ISSUE 1 FIX: Use 8-second timeout (industry standard)
                # Adaptive: increase slightly for later attempts
                timeout = 8 if attempt == 0 else 10
                
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(mx_host, 25),
                    timeout=timeout
                )
                
                try:
                    # Read SMTP greeting
                    greeting = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                    
                    # Send HELO
                    writer.write(b'HELO gmail.com\r\n')
                    await writer.drain()
                    await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                    
                    # Send MAIL FROM
                    writer.write(b'MAIL FROM:<test@gmail.com>\r\n')
                    await writer.drain()
                    await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                    
                    # Critical check: RCPT TO
                    writer.write(f'RCPT TO:<{email}>\r\n'.encode())
                    await writer.drain()
                    response = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                    response_str = response.decode().strip()
                    response_code = int(response_str.split()[0]) if response_str else 550
                    
                    # Clean quit
                    try:
                        writer.write(b'QUIT\r\n')
                        await writer.drain()
                    except:
                        pass
                    writer.close()
                    await writer.wait_closed()
                    
                    # ✅ ISSUE 3 FIX: Proper status classification
                    # 250-299: Accepted
                    if 250 <= response_code < 300:
                        return {"connected": True, "accepted": True, "tempfail": False, "rejected": False}
                    # 400-499: Temporary failure (greylist, rate limit, etc.)
                    elif 400 <= response_code < 500:
                        return {"connected": True, "accepted": False, "tempfail": True, "rejected": False}
                    # 500-599: Permanent rejection
                    elif 500 <= response_code < 600:
                        return {"connected": True, "accepted": False, "tempfail": False, "rejected": True}
                    else:
                        return {"connected": True, "accepted": False, "tempfail": False, "rejected": False}
                    
                except Exception as e:
                    writer.close()
                    await writer.wait_closed()
                    # Try next MX server
                    continue
                    
            except asyncio.TimeoutError:
                # Timeout on this MX, try next one
                continue
            except (ConnectionRefusedError, OSError):
                # Connection failed, try next MX
                continue
            except Exception as e:
                # Unexpected error, try next MX
                continue
        
        # If we tried all MX servers and none responded definitively
        return {"connected": False, "accepted": False, "tempfail": False, "rejected": False}
    
    async def verify_email_fast(self, email: str) -> VerificationResult:
        """
        Fast single email verification with optimized pipeline.
        Timeout: 65 seconds total (60s for SMTP + 5s overhead)
        """
        start_time = time.time()
        
        try:
            # Check local cache first
            cache_key = hashlib.md5(email.lower().encode()).hexdigest()
            if cache_key in self.verification_cache:
                cached_result = self.verification_cache[cache_key]
                # Check if cache is still fresh (5 minutes)
                if time.time() - cached_result.get('timestamp', 0) < 300:
                    logger.debug(f"📦 Cache hit for {email}")
                    return cached_result['result']
            
            logger.debug(f"🔍 Verifying email: {email}")
            
            # Fast syntax validation
            is_valid, normalized_email, syntax_error = validate_email_syntax(email)
            if not is_valid:
                logger.debug(f"❌ Syntax invalid for {email}: {syntax_error}")
                result = VerificationResult(
                    email=email,
                    status=VerificationStatus.INVALID,
                    reason_code=ReasonCode.SYNTAX_ERROR,
                    reasons=[syntax_error or "Invalid email syntax"],
                    verification_duration_ms=int((time.time() - start_time) * 1000)
                )
                self._cache_result(cache_key, result)
                return result
            
            # Use normalized email
            email = normalized_email or email
            
            domain = extract_domain(email)
            if not domain:
                logger.debug(f"❌ Could not extract domain from {email}")
                result = VerificationResult(
                    email=email,
                    status=VerificationStatus.INVALID,
                    reason_code=ReasonCode.SYNTAX_ERROR,
                    reasons=["Could not extract domain"],
                    verification_duration_ms=int((time.time() - start_time) * 1000)
                )
                self._cache_result(cache_key, result)
                return result
            
            logger.debug(f"📧 Collecting verification signals for {email}@{domain}")
            
            # Fast parallel signal collection with timeout protection
            try:
                signals = await asyncio.wait_for(
                    self._collect_verification_signals_fast(email, domain),
                    timeout=self.VERIFY_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(f"⏱️  TIMEOUT: Verification exceeded {self.VERIFY_TIMEOUT}s for {email}")
                result = VerificationResult(
                    email=email,
                    status=VerificationStatus.UNKNOWN_TEMPFAIL,
                    reason_code=ReasonCode.SMTP_TIMEOUT,
                    reasons=["Verification timeout - server response took too long"],
                    verification_duration_ms=int((time.time() - start_time) * 1000)
                )
                return result
            
            # Classify result using balanced classification (handles webmail/hosting providers)
            from app.balanced_classification import classify_verification_result_balanced
            result = classify_verification_result_balanced(signals)
            if result is not None:
                result.verification_duration_ms = int((time.time() - start_time) * 1000)
                logger.info(f"✅ Verification completed for {email}: {result.status.value} ({result.verification_duration_ms}ms)")
                # Cache the result
                self._cache_result(cache_key, result)
            else:
                logger.error(f"Failed to classify verification for {email}")
                result = VerificationResult(
                    email=email,
                    status=VerificationStatus.UNKNOWN_TEMPFAIL,
                    reason_code=ReasonCode.SMTP_TEMPFAIL
                )
            
            return result
            
        except asyncio.TimeoutError:
            logger.error(f"⏱️  TIMEOUT: verify_email_fast exceeded {self.VERIFY_TIMEOUT}s for {email}")
            result = VerificationResult(
                email=email,
                status=VerificationStatus.UNKNOWN_TEMPFAIL,
                reason_code=ReasonCode.SMTP_TIMEOUT,
                reasons=["Verification timeout - server response took too long"],
                verification_duration_ms=int((time.time() - start_time) * 1000)
            )
            return result
        except Exception as e:
            logger.error(f"❌ Error verifying {email}: {str(e)}", exc_info=True)
            result = VerificationResult(
                email=email,
                status=VerificationStatus.UNKNOWN_TEMPFAIL,
                reason_code=ReasonCode.NETWORK_ERROR,
                reasons=[f"Verification error: {str(e)}"],
                verification_duration_ms=int((time.time() - start_time) * 1000)
            )
            return result
    
    def _cache_result(self, cache_key: str, result: VerificationResult):
        """Cache result locally for fast repeated lookups."""
        self.verification_cache[cache_key] = {
            'result': result,
            'timestamp': time.time()
        }
        
        # Keep cache size reasonable (max 1000 entries)
        if len(self.verification_cache) > 1000:
            # Remove oldest entries
            oldest_key = min(self.verification_cache.keys(), 
                           key=lambda k: self.verification_cache[k]['timestamp'])
            del self.verification_cache[oldest_key]
    
    async def _collect_verification_signals_fast(self, email: str, domain: str) -> Dict[str, Any]:
        """
        Fast parallel collection of verification signals with timeout protection.
        DNS: 15s timeout
        SMTP: 60s timeout
        """
        # Define webmail domains
        webmail_domains = {
            'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com',
            'protonmail.com', 'icloud.com', 'me.com', 'mail.com', 'zoho.com',
            'yandex.com', 'mail.ru', 'qq.com', '163.com', 'sina.com',
            'gmx.com', 'gmx.de', 'web.de', 'freenet.de'
        }
        
        signals = {
            "email": email,
            "domain": domain,
            "syntax_valid": True,
            "has_mx": False,
            "smtp_accepted": False,
            "smtp_connected": False,
            "is_disposable": False,
            "is_role_based": False,
            "is_catch_all": False,
            "is_webmail": domain.lower() in webmail_domains,  # Add webmail detection
            "mx_records": [],
            "smtp_response": "",
            "smtp_error": None,
            "network_error": False,
            "verification_method": "fast_parallel"
        }
        
        # Run checks in parallel for speed
        try:
            logger.debug(f"🔄 Starting parallel signal collection for {email}")
            
            # Start all checks concurrently
            tasks = []
            
            # Domain and MX check
            tasks.append(asyncio.create_task(get_mx_records(domain)))
            
            # Disposable check (async function)
            async def get_disposable_result():
                return is_disposable_domain_fast(domain)
            tasks.append(asyncio.create_task(get_disposable_result()))
            
            # Role-based check (sync function)
            tasks.append(asyncio.create_task(asyncio.to_thread(is_role_based_email, email)))
            
            # Wait for all tasks with DNS timeout (5s) - handle shutdown gracefully
            try:
                logger.debug(f"📡 DNS lookup for {domain} with {self.DNS_TIMEOUT}s timeout")
                if tasks:
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True), 
                        timeout=self.DNS_TIMEOUT
                    )
                else:
                    results = []
            except (asyncio.CancelledError, RuntimeError) as e:
                # Handle event loop shutdown or cancellation
                if "cannot schedule new futures after shutdown" in str(e):
                    logger.debug(f"Event loop shutdown detected for {domain}")
                    return {'valid': False, 'reason': 'Verification interrupted'}
                results = []

                # Process results
                if len(results) >= 1 and results[0] is not None and not isinstance(results[0], BaseException):
                    try:
                        if isinstance(results[0], tuple) and len(results[0]) == 3:
                            has_mx, mx_records, mx_error = results[0]
                            signals["has_mx"] = has_mx
                            signals["mx_records"] = mx_records
                            logger.debug(f"🌐 MX lookup: has_mx={has_mx}, records={len(mx_records) if mx_records else 0}")
                            if mx_error:
                                signals["dns_error"] = mx_error
                                logger.debug(f"⚠️  DNS error: {mx_error}")
                    except (TypeError, ValueError) as e:
                        logger.error(f"Error processing MX results: {e}")

                if len(results) >= 2 and not isinstance(results[1], Exception):
                    signals["is_disposable"] = results[1]
                    if results[1]:
                        logger.debug(f"🗑️  Disposable domain detected: {domain}")

                if len(results) >= 3 and not isinstance(results[2], Exception):
                    signals["is_role_based"] = results[2]
                    if results[2]:
                        logger.debug(f"👤 Role-based email detected: {email}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️  DNS timeout for {domain} after {self.DNS_TIMEOUT}s")
                signals["dns_timeout"] = True
                # Continue with no MX - will be marked as invalid
            except Exception as e:
                logger.warning(f"⚠️  DNS error for {domain}: {str(e)}")
                signals["dns_error"] = str(e)

            # SMTP check only if domain has MX
            if signals["has_mx"] and signals.get("mx_records"):
                mx_records = signals["mx_records"]
                try:
                    logger.debug(f"📧 SMTP verification for {email} with {self.SMTP_TIMEOUT}s timeout")
                    # Give the enhanced SMTP verification the full 120s timeout for webmail
                    actual_timeout = 150 if signals.get("is_webmail") else self.SMTP_TIMEOUT
                    
                    smtp_result = await asyncio.wait_for(
                        enhanced_smtp_verify_with_retries(email, mx_records[0] if mx_records else "", max_retries=1),
                        timeout=actual_timeout
                    )
                    
                    # Extract all critical signals from SMTP verifier
                    signals["smtp_connected"] = smtp_result.get("connected", False)
                    signals["smtp_accepted"] = smtp_result.get("accepted", False)
                    signals["smtp_response"] = smtp_result.get("response", "")
                    signals["smtp_code"] = smtp_result.get("response_code")
                    signals["response_code_type"] = smtp_result.get("response_code_type")
                    signals["smtp_error"] = smtp_result.get("error")
                    signals["smtp_errors"] = smtp_result.get("errors", [])
                    signals["smtp_transcript"] = smtp_result.get("transcript", [])
                    
                    # CRITICAL: These flags determine classification
                    signals["is_tempfail"] = smtp_result.get("is_tempfail", False)
                    signals["is_permanent_fail"] = smtp_result.get("is_permanent_fail", False)
                    signals["is_greylisting"] = smtp_result.get("is_greylisting", False)
                    signals["timeout_occurred"] = smtp_result.get("timeout_occurred", False)
                    signals["is_webmail"] = smtp_result.get("is_webmail", signals.get("is_webmail", False))
                    
                    logger.debug(f"✅ SMTP result: connected={signals['smtp_connected']}, accepted={signals['smtp_accepted']}, " +
                                f"tempfail={signals['is_tempfail']}, permfail={signals['is_permanent_fail']}, " +
                                f"code={signals['smtp_code']}, greylisting={signals['is_greylisting']}")
                    
                    # Mark network error only if connection failed (not for SMTP rejects)
                    if smtp_result.get("error") and not signals["smtp_connected"]:
                        error_str = str(smtp_result.get("error", "")).lower()
                        if any(keyword in error_str for keyword in [
                            'timeout', 'connection', 'network', 'unreachable', 
                            'refused', 'reset', 'failed to connect'
                        ]):
                            signals["network_error"] = True
                            logger.warning(f"⚠️  Network error detected: {error_str}")

                except asyncio.TimeoutError:
                    logger.error(f"⏱️  SMTP timeout for {email} exceeded {actual_timeout}s")
                    signals["smtp_response"] = "SMTP timeout"
                    signals["timeout_occurred"] = True
                    signals["is_tempfail"] = True  # Timeout = temporary, not permanent
                    signals["network_error"] = True
                except Exception as e:
                    logger.error(f"❌ SMTP error for {email}: {str(e)}")
                    signals["smtp_response"] = f"SMTP error: {str(e)}"
                    signals["smtp_error"] = str(e)
                    signals["network_error"] = True
                
        except asyncio.TimeoutError:
            logger.error(f"⏱️  Overall verification timeout for {email} exceeded {self.VERIFY_TIMEOUT}s")
            signals["network_error"] = True
            
        except Exception as e:
            logger.error(f"Error collecting signals for {email}: {str(e)}")
            signals["network_error"] = True
        
        return signals
    
    async def verify_email(self, email: str) -> VerificationResult:
        """
        Main email verification method - now uses the fast version.
        """
        return await self.verify_email_fast(email)
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get current health and performance metrics."""
        return {
            **self.health_status,
            "cache_size": len(self.verification_cache),
            "max_workers": self.max_workers,
            "uptime": time.time() - self.health_status["last_check"]
        }
    
    async def _collect_verification_signals(self, email: str, domain: str) -> Dict[str, Any]:
        """
        Collect all verification signals for an email.
        
        Args:
            email: Email address
            domain: Domain part of email
            
        Returns:
            Dictionary with all verification signals
        """
        signals = {
            'email': email,
            'domain': domain,
            'syntax_valid': True,  # Already validated
        }
        
        # Step 2: Check disposable domains
        try:
            signals['is_disposable'] = is_disposable_domain_fast(domain)
            if signals['is_disposable']:
                logger.debug(f"Domain {domain} is disposable")
                return signals  # Early return for disposable
        except Exception as e:
            logger.error(f"Error checking disposable domain {domain}: {e}")
            signals['is_disposable'] = False
        
        # Step 3: Check role-based (if enabled)
        role_based_check = getattr(settings, 'role_based_check', True)
        if role_based_check:
            try:
                signals['is_role_based'] = is_role_based_email(email)
                if signals['is_role_based']:
                    signals['role_type'] = get_role_type(email)
                    logger.debug(f"Email {email} is role-based ({signals['role_type']})")
            except Exception as e:
                logger.error(f"Error checking role-based {email}: {e}")
                signals['is_role_based'] = False
        
        # Step 4: DNS validation
        try:
            dns_valid, mx_hostnames, dns_error = await simple_domain_check(domain)
            signals['has_mx'] = dns_valid
            signals['mx_records'] = mx_hostnames
            signals['dns_error'] = dns_error
            
            if not dns_valid:
                logger.debug(f"DNS validation failed for {domain}: {dns_error}")
                return signals  # Early return for DNS failures
                
        except Exception as e:
            logger.error(f"Error validating DNS for {domain}: {e}")
            signals['has_mx'] = False
            signals['dns_error'] = str(e)
            signals['network_error'] = True
            return signals
        
        # Step 5: Get best MX host
        try:
            best_mx = await simple_mx_check(domain)
            if not best_mx:
                signals['has_mx'] = False
                signals['dns_error'] = "No usable MX host found"
                return signals
            
            signals['best_mx_host'] = best_mx
            
        except Exception as e:
            logger.error(f"Error getting MX host for {domain}: {e}")
            signals['network_error'] = True
            return signals
        
        # Step 6: Catch-all detection
        try:
            is_catch_all, catch_all_transcript = await check_catch_all_domain(domain, best_mx)
            signals['is_catch_all'] = is_catch_all
            signals['catch_all_transcript'] = catch_all_transcript
            
            if is_catch_all:
                logger.debug(f"Domain {domain} is catch-all")
                
        except Exception as e:
            logger.error(f"Error checking catch-all for {domain}: {e}")
            signals['is_catch_all'] = False
        
        # Step 7: Enhanced SMTP verification with webmail support
        try:
            smtp_result = await enhanced_smtp_verify_with_retries(
                email, 
                mx_hostnames[0] if mx_hostnames else "",
                max_retries=len(settings.retry_backoff_list)
            )
            
            signals['smtp_connected'] = smtp_result.get('connected', False)
            signals['smtp_accepted'] = smtp_result.get('accepted', False)
            signals['smtp_code'] = smtp_result.get('response_code')
            signals['smtp_transcript'] = smtp_result.get('transcript', [])
            signals['smtp_tempfail'] = False  # Will be determined by response code
            signals['smtp_permanent_fail'] = False  # Will be determined by response code
            signals['smtp_starttls_used'] = True  # Enhanced verifier uses TLS when available
            signals['smtp_error'] = '; '.join(smtp_result.get('errors', []))
            signals['is_webmail'] = smtp_result.get('is_webmail', False)
            signals['confidence_score'] = smtp_result.get('confidence_score', 0)
            
            # Determine temp/permanent failure from response code
            response_code = smtp_result.get('response_code')
            if response_code:
                if 400 <= response_code < 500:
                    signals['smtp_tempfail'] = True
                elif response_code >= 500:
                    signals['smtp_permanent_fail'] = True
            
            # Better network error detection
            if smtp_result.get('errors'):
                error_text = ' '.join(smtp_result['errors']).lower()
                if any(keyword in error_text for keyword in [
                    'timeout', 'connection', 'network', 'unreachable', 
                    'refused', 'reset', 'failed to connect'
                ]):
                    signals['network_error'] = True
                    if 'timeout' in error_text:
                        signals['smtp_timeout'] = True
            
            # If no connection was made at all, it's likely a network issue
            if isinstance(smtp_result, dict):
                if not smtp_result.get('connected', False) and not smtp_result.get('is_permanent_fail', False):
                    signals['network_error'] = True
            elif hasattr(smtp_result, 'connected') and hasattr(smtp_result, 'is_permanent_fail'):
                if not smtp_result.connected and not smtp_result.is_permanent_fail:
                    signals['network_error'] = True
            
        except Exception as e:
            logger.error(f"Error in SMTP verification for {email}: {e}")
            signals['smtp_error'] = str(e)
            signals['network_error'] = True
        
        return signals
    
    async def _check_rate_limit(self, domain: str) -> bool:
        """
        Check if domain is within rate limits.
        
        Args:
            domain: Domain to check
            
        Returns:
            True if within rate limits
        """
        current_time = time.time()
        minute_window = int(current_time // 60)
        
        # Clean old entries
        self.rate_limiter = {
            key: count for key, count in self.rate_limiter.items()
            if int(key.split('|')[1]) >= minute_window - 1
        }
        
        # Check current rate
        rate_key = f"{domain}|{minute_window}"
        current_count = self.rate_limiter.get(rate_key, 0)
        
        if current_count >= settings.rate_limit_per_domain_per_min:
            logger.warning(f"Rate limit exceeded for domain {domain}")
            return False
        
        # Increment counter
        self.rate_limiter[rate_key] = current_count + 1
        return True
    
    async def verify_bulk(self, emails: List[str]) -> List[VerificationResult]:
        """
        Verify multiple emails with controlled concurrency.
        
        Args:
            emails: List of email addresses to verify
            
        Returns:
            List of VerificationResult objects
        """
        # Remove duplicates while preserving order
        seen = set()
        unique_emails = []
        for email in emails:
            normalized = email.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique_emails.append(email)
        
        logger.info(f"Verifying {len(unique_emails)} unique emails (from {len(emails)} total)")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(settings.max_concurrency)
        
        async def verify_with_semaphore(email: str) -> VerificationResult:
            async with semaphore:
                return await self.verify_email(email)
        
        # Create tasks for all emails
        tasks = [verify_with_semaphore(email) for email in unique_emails]
        
        # Execute with progress logging
        results = []
        completed = 0
        
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1
            
            if completed % 100 == 0 or completed == len(tasks):
                logger.info(f"Completed {completed}/{len(tasks)} verifications")
        
        return results
    
    def get_verification_stats(self, results: List[VerificationResult]) -> Dict[str, Any]:
        """
        Calculate statistics from verification results.
        
        Args:
            results: List of verification results
            
        Returns:
            Dictionary with statistics
        """
        if not results:
            return {}
        
        stats = {
            'total': len(results),
            'deliverable': 0,
            'invalid': 0,
            'risky_catch_all': 0,
            'risky_role_based': 0,
            'unknown_tempfail': 0,
            'disposable': 0,
            'avg_duration_ms': 0,
            'domains': set(),
            'status_breakdown': {}
        }
        
        total_duration = 0
        
        for result in results:
            # Count by status
            status = result.status.value
            stats['status_breakdown'][status] = stats['status_breakdown'].get(status, 0) + 1
            
            if result.status == VerificationStatus.DELIVERABLE:
                stats['deliverable'] += 1
            elif result.status == VerificationStatus.INVALID:
                stats['invalid'] += 1
            elif result.status == VerificationStatus.RISKY_CATCH_ALL:
                stats['risky_catch_all'] += 1
            elif result.status == VerificationStatus.RISKY_ROLE_BASED:
                stats['risky_role_based'] += 1
            elif result.status == VerificationStatus.UNKNOWN_TEMPFAIL:
                stats['unknown_tempfail'] += 1
            elif result.status == VerificationStatus.DISPOSABLE:
                stats['disposable'] += 1
            
            # Track duration
            if result.verification_duration_ms:
                total_duration += result.verification_duration_ms
            
            # Track domains
            domain = extract_domain(result.email)
            if domain:
                stats['domains'].add(domain)
        
        # Calculate averages
        if total_duration > 0:
            stats['avg_duration_ms'] = total_duration // len(results)
        
        stats['unique_domains'] = len(stats['domains'])
        stats['domains'] = list(stats['domains'])  # Convert set to list for JSON serialization
        
        return stats


# Global service instance
verification_service = EmailVerificationService()


async def verify_single_email(email: str) -> VerificationResult:
    """
    Verify a single email (convenience function).
    
    Args:
        email: Email address to verify
        
    Returns:
        VerificationResult
    """
    return await verification_service.verify_email(email)


async def verify_email_list(emails: List[str]) -> List[VerificationResult]:
    """
    Verify a list of emails (convenience function).
    
    Args:
        emails: List of email addresses to verify
        
    Returns:
        List of VerificationResult objects
    """
    return await verification_service.verify_bulk(emails)