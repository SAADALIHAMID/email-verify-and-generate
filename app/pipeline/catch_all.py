"""Catch-all domain detection using reputation-based approach (NOT random testing)."""

import asyncio
import logging
import random
import string
from typing import Tuple, List, Optional, Dict
from app.config import settings
from app.smtp_utils import smtp_verify_email

logger = logging.getLogger(__name__)

# Known catch-all domains (reputation-based)
KNOWN_CATCHALL_DOMAINS = {
    # Common mass email services
    'mailinator.com', 'tempmail.org', '10minutemail.com', 'guerrillamail.com',
    'yopmail.com', 'throwaway.email', 'getnada.com', 'maildrop.cc',
    'temp-mail.org', 'sharklasers.com', 'temp-mail.io',
    # Some corporate domains known to be catch-all
}

# Domains known to NOT be catch-all
KNOWN_NOT_CATCHALL_DOMAINS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
    'aol.com', 'protonmail.com', 'icloud.com', 'me.com', 'zoho.com',
    'yandex.com', 'mail.ru', 'mail.com', 'web.de', 'gmx.de', 'gmx.com',
    'company.com', 'business.com'  # Examples - not actual catch-alls
}


class CatchAllDetector:
    """Catch-all domain detector using REPUTATION-BASED approach (NOT random testing)."""
    
    def __init__(self):
        self._cache: Dict[str, Tuple[bool, float]] = {}  # domain -> (is_catch_all, timestamp)
        self._cache_ttl = 3600  # 1 hour cache
    
    def _is_cache_valid(self, timestamp: float) -> bool:
        """Check if cache entry is still valid."""
        import time
        return (time.time() - timestamp) < self._cache_ttl
    
    async def is_catch_all_domain(self, domain: str, mx_host: str) -> Tuple[bool, List[str]]:
        """
        REPUTATION-BASED catch-all detection (NOT random testing).
        
        IMPROVEMENTS:
        - Check reputation database first (known catch-all/not catch-all)
        - Avoid false positives from random testing
        - Cache results for 1 hour
        
        Args:
            domain: Domain to test
            mx_host: MX hostname to connect to
            
        Returns:
            Tuple of (is_catch_all, transcript)
        """
        import time
        
        # Check cache first
        if domain in self._cache:
            is_catch_all, timestamp = self._cache[domain]
            if self._is_cache_valid(timestamp):
                logger.debug(f"✓ Using cached catch-all result for {domain}: {is_catch_all}")
                return is_catch_all, [f"Cached result: catch-all={is_catch_all}"]
        
        transcripts = []
        
        # STEP 1: Check reputation database (most accurate)
        if domain in KNOWN_CATCHALL_DOMAINS:
            is_catch_all = True
            self._cache[domain] = (is_catch_all, time.time())
            transcripts.append(f"✓ Domain {domain} is in known catch-all list (reputation-based)")
            logger.debug(f"✓ Domain {domain} marked catch-all (reputation database)")
            return is_catch_all, transcripts
        
        if domain in KNOWN_NOT_CATCHALL_DOMAINS:
            is_catch_all = False
            self._cache[domain] = (is_catch_all, time.time())
            transcripts.append(f"✓ Domain {domain} is NOT catch-all (reputation database)")
            logger.debug(f"✓ Domain {domain} marked NOT catch-all (reputation database)")
            return is_catch_all, transcripts
        
        # STEP 2: SMARTER detection (not pure random, but contextual)
        # Only test if domain passes basic trust checks
        test_results = []
        
        try:
            # Use SPECIFIC test patterns that are more reliable
            test_patterns = [
                f"test-{int(time.time())}-noreply@{domain}",  # Looks like system account
                f"noreply-{random.randint(1000, 9999)}@{domain}",  # Looks like automated
            ]
            
            for test_email in test_patterns:
                logger.debug(f"Testing catch-all for {domain} with: {test_email}")
                
                try:
                    result = await smtp_verify_email(test_email, mx_host)
                    
                    # Only consider it catch-all if ALL tests pass
                    accepted = result.accepted and result.rcpt_to_code in [250, 251]
                    test_results.append(accepted)
                    transcripts.append(f"Test email {test_email}: {'accepted' if accepted else 'rejected'}")
                    
                    # If we get a permanent rejection, domain is NOT catch-all
                    if result.is_permanent_fail:
                        logger.debug(f"✓ Domain {domain} got permanent rejection - NOT catch-all")
                        break
                        
                except Exception as e:
                    logger.warning(f"Error testing catch-all pattern for {domain}: {e}")
                    transcripts.append(f"Error testing {test_email}: {str(e)}")
                    test_results.append(False)
        
        except Exception as e:
            logger.error(f"Error in catch-all detection for {domain}: {e}")
            transcripts.append(f"Catch-all detection failed: {str(e)}")
            # If detection fails, assume NOT catch-all (safer assumption)
            is_catch_all = False
        else:
            # Domain is catch-all only if ALL test patterns were accepted
            # This is MUCH stricter than the old logic
            is_catch_all = len(test_results) > 0 and all(test_results)
        
        # Cache result
        self._cache[domain] = (is_catch_all, time.time())
        
        logger.debug(f"✓ Catch-all detection for {domain}: {is_catch_all}")
        return is_catch_all, transcripts
    
    async def batch_check_catch_all(
        self, 
        domain_mx_pairs: List[Tuple[str, str]]
    ) -> Dict[str, Tuple[bool, List[str]]]:
        """
        Check multiple domains for catch-all behavior concurrently.
        
        Args:
            domain_mx_pairs: List of (domain, mx_host) tuples
            
        Returns:
            Dictionary mapping domain -> (is_catch_all, transcript)
        """
        # Limit concurrency to be respectful to mail servers
        semaphore = asyncio.Semaphore(min(5, settings.max_concurrency // 4))
        
        async def check_with_semaphore(domain: str, mx_host: str):
            async with semaphore:
                return domain, await self.is_catch_all_domain(domain, mx_host)
        
        tasks = [
            check_with_semaphore(domain, mx_host)
            for domain, mx_host in domain_mx_pairs
        ]
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            domain_results = {}
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Batch catch-all check error: {result}")
                    continue
                
                # Type narrowing: result is now guaranteed to be a valid result tuple
                # Result should be a tuple of (domain, (is_catch_all, transcript))
                try:
                    if isinstance(result, tuple) and len(result) == 2:
                        domain, catch_all_info = result
                        if isinstance(catch_all_info, tuple) and len(catch_all_info) == 2:
                            is_catch_all, transcript = catch_all_info
                            domain_results[domain] = (is_catch_all, transcript)
                        else:
                            logger.warning(f"Unexpected catch_all_info format: {catch_all_info}")
                    else:
                        logger.warning(f"Unexpected result format: {result}")
                except (ValueError, TypeError, AttributeError) as e:
                    logger.error(f"Failed to unpack result: {result}, error: {e}")
                    continue
            
            return domain_results
            
        except Exception as e:
            logger.error(f"Batch catch-all check failed: {e}")
            return {}
    
    def clear_cache(self) -> None:
        """Clear the catch-all detection cache."""
        self._cache.clear()
        logger.info("Catch-all detection cache cleared")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        import time
        current_time = time.time()
        
        valid_entries = sum(
            1 for _, timestamp in self._cache.values()
            if self._is_cache_valid(timestamp)
        )
        
        return {
            'total_entries': len(self._cache),
            'valid_entries': valid_entries,
            'expired_entries': len(self._cache) - valid_entries
        }


# Global instance
catch_all_detector = CatchAllDetector()


async def check_catch_all_domain(domain: str, mx_host: str) -> Tuple[bool, List[str]]:
    """
    Check if domain accepts catch-all emails (convenience function).
    
    Args:
        domain: Domain to test
        mx_host: MX hostname to connect to
        
    Returns:
        Tuple of (is_catch_all, transcript)
    """
    return await catch_all_detector.is_catch_all_domain(domain, mx_host)


def generate_test_emails(domain: str, count: int = 3) -> List[str]:
    """
    Generate test email addresses for catch-all detection.
    
    Args:
        domain: Domain to generate test emails for
        count: Number of test emails to generate
        
    Returns:
        List of test email addresses
    """
    test_emails = []
    
    for i in range(count):
        # Generate different types of random localparts
        if i == 0:
            # Pure random
            localpart = ''.join(random.choices(
                string.ascii_lowercase + string.digits, 
                k=settings.catch_all_random_localpart_len
            ))
        elif i == 1:
            # Random with common prefix
            localpart = 'test' + ''.join(random.choices(
                string.ascii_lowercase + string.digits, 
                k=settings.catch_all_random_localpart_len - 4
            ))
        else:
            # UUID-like format
            import uuid
            localpart = str(uuid.uuid4()).replace('-', '')[:16]
        
        test_emails.append(f"{localpart}@{domain}")
    
    return test_emails


async def verify_catch_all_with_confidence(
    domain: str, 
    mx_host: str, 
    confidence_threshold: float = 0.7
) -> Tuple[bool, float, List[str]]:
    """
    Verify catch-all behavior with confidence scoring.
    
    Args:
        domain: Domain to test
        mx_host: MX hostname to connect to
        confidence_threshold: Minimum confidence required
        
    Returns:
        Tuple of (is_catch_all, confidence_score, transcript)
    """
    test_emails = generate_test_emails(domain, count=3)
    results = []
    all_transcripts = []
    
    for email in test_emails:
        try:
            result = await smtp_verify_email(email, mx_host)
            results.append({
                'email': email,
                'accepted': result.accepted,
                'code': result.rcpt_to_code,
                'permanent_fail': result.is_permanent_fail
            })
            all_transcripts.extend(result.transcript)
            
            # If we get a definitive permanent failure, stop testing
            if result.is_permanent_fail and result.rcpt_to_code in [550, 551]:
                break
                
        except Exception as e:
            logger.error(f"Error testing {email}: {e}")
            all_transcripts.append(f"Error testing {email}: {str(e)}")
            results.append({
                'email': email,
                'accepted': False,
                'code': None,
                'permanent_fail': False
            })
    
    # Calculate confidence score
    if not results:
        return False, 0.0, all_transcripts
    
    accepted_count = sum(1 for r in results if r['accepted'])
    total_tests = len(results)
    
    # If all tests accepted, high confidence it's catch-all
    if accepted_count == total_tests:
        confidence = 0.95
    # If some accepted, medium confidence
    elif accepted_count > 0:
        confidence = 0.6 + (accepted_count / total_tests) * 0.3
    # If none accepted but no permanent failures, low confidence
    elif not any(r['permanent_fail'] for r in results):
        confidence = 0.3
    # If permanent failures, high confidence it's not catch-all
    else:
        confidence = 0.1
    
    is_catch_all = confidence >= confidence_threshold and accepted_count > 0
    
    logger.debug(
        f"Catch-all confidence for {domain}: {confidence:.2f} "
        f"({accepted_count}/{total_tests} accepted)"
    )
    
    return is_catch_all, confidence, all_transcripts