"""SMTP utilities for email verification - async SMTP handshake with aiosmtplib."""

import asyncio
import logging
import random
import string
from typing import List, Optional, Tuple, Dict, Any
import aiosmtplib
from aiosmtplib import SMTPException, SMTPConnectError, SMTPTimeoutError
from app.config import settings

logger = logging.getLogger(__name__)


class SMTPResult:
    """SMTP verification result container."""
    
    def __init__(self):
        self.connected: bool = False
        self.supports_starttls: bool = False
        self.used_starttls: bool = False
        self.helo_response: Optional[str] = None
        self.mail_from_response: Optional[str] = None
        self.rcpt_to_response: Optional[str] = None
        self.rcpt_to_code: Optional[int] = None
        self.accepted: bool = False
        self.transcript: List[str] = []
        self.error: Optional[str] = None
        self.is_tempfail: bool = False
        self.is_permanent_fail: bool = False


async def smtp_verify_email(email: str, mx_host: str) -> SMTPResult:
    """
    Verify email deliverability via SMTP handshake.
    
    Args:
        email: Email address to verify
        mx_host: MX hostname to connect to
        
    Returns:
        SMTPResult with verification details
    """
    result = SMTPResult()
    smtp = None
    
    try:
        # Create SMTP connection
        smtp = aiosmtplib.SMTP(
            hostname=mx_host,
            port=25,
            timeout=settings.smtp_connect_timeout,
            use_tls=False,  # We'll use STARTTLS if available
        )
        
        # Connect with timeout
        await asyncio.wait_for(
            smtp.connect(),
            timeout=settings.smtp_connect_timeout
        )
        result.connected = True
        result.transcript.append(f"Connected to {mx_host}:25")
        
        # Check for STARTTLS support
        if smtp.supports_extension("STARTTLS"):
            result.supports_starttls = True
            try:
                await asyncio.wait_for(
                    smtp.starttls(),
                    timeout=settings.smtp_op_timeout
                )
                result.used_starttls = True
                result.transcript.append("STARTTLS successful")
            except Exception as e:
                logger.debug(f"STARTTLS failed for {mx_host}: {e}")
                result.transcript.append(f"STARTTLS failed: {str(e)}")
        
        # HELO/EHLO
        try:
            helo_response = await asyncio.wait_for(
                smtp.ehlo(),
                timeout=settings.smtp_op_timeout
            )
            result.helo_response = str(helo_response)
            result.transcript.append(f"EHLO: {helo_response}")
        except Exception:
            # Fallback to HELO if EHLO fails
            try:
                helo_response = await asyncio.wait_for(
                    smtp.helo(),
                    timeout=settings.smtp_op_timeout
                )
                result.helo_response = str(helo_response)
                result.transcript.append(f"HELO: {helo_response}")
            except Exception as e:
                result.error = f"HELO/EHLO failed: {str(e)}"
                result.transcript.append(f"HELO/EHLO failed: {str(e)}")
                return result
        
        # MAIL FROM
        sender = f"postmaster@{settings.fake_local_domain}"
        try:
            mail_response = await asyncio.wait_for(
                smtp.mail(sender),
                timeout=settings.smtp_op_timeout
            )
            result.mail_from_response = str(mail_response)
            result.transcript.append(f"MAIL FROM <{sender}>: {mail_response}")
        except Exception as e:
            result.error = f"MAIL FROM failed: {str(e)}"
            result.transcript.append(f"MAIL FROM failed: {str(e)}")
            return result
        
        # RCPT TO - the actual verification
        try:
            rcpt_response = await asyncio.wait_for(
                smtp.rcpt(email),
                timeout=settings.smtp_op_timeout
            )
            result.rcpt_to_response = str(rcpt_response)
            result.rcpt_to_code = rcpt_response.code
            result.transcript.append(f"RCPT TO <{email}>: {rcpt_response}")
            
            # Analyze response code
            if 200 <= rcpt_response.code < 300:
                result.accepted = True
            elif 400 <= rcpt_response.code < 500:
                result.is_tempfail = True
            elif 500 <= rcpt_response.code < 600:
                result.is_permanent_fail = True
                
        except SMTPException as e:
            # Parse SMTP error codes from exception
            error_str = str(e)
            result.rcpt_to_response = error_str
            result.transcript.append(f"RCPT TO <{email}>: {error_str}")
            
            # Try to extract code from error message
            try:
                if hasattr(e, 'smtp_code'):
                    smtp_code = getattr(e, 'smtp_code', None)
                    if isinstance(smtp_code, int):
                        result.rcpt_to_code = smtp_code
                else:
                    # Try to parse code from error string
                    parts = error_str.split()
                    if parts and parts[0].isdigit():
                        result.rcpt_to_code = int(parts[0])
                
                if result.rcpt_to_code:
                    if 400 <= result.rcpt_to_code < 500:
                        result.is_tempfail = True
                    elif 500 <= result.rcpt_to_code < 600:
                        result.is_permanent_fail = True
                        
            except (ValueError, AttributeError):
                pass
            
            result.error = f"RCPT TO failed: {error_str}"
            
        except Exception as e:
            result.error = f"RCPT TO error: {str(e)}"
            result.transcript.append(f"RCPT TO error: {str(e)}")
        
    except SMTPConnectError as e:
        result.error = f"Connection failed: {str(e)}"
        result.transcript.append(f"Connection failed: {str(e)}")
        
    except SMTPTimeoutError as e:
        result.error = f"SMTP timeout: {str(e)}"
        result.transcript.append(f"SMTP timeout: {str(e)}")
        
    except asyncio.TimeoutError:
        result.error = "Operation timeout"
        result.transcript.append("Operation timeout")
        
    except Exception as e:
        result.error = f"SMTP error: {str(e)}"
        result.transcript.append(f"SMTP error: {str(e)}")
        
    finally:
        # Clean up connection
        if smtp and result.connected:
            try:
                await asyncio.wait_for(smtp.quit(), timeout=5)
                result.transcript.append("Connection closed")
            except Exception:
                pass  # Ignore cleanup errors
    
    return result


async def check_catch_all(domain: str, mx_host: str) -> Tuple[bool, List[str]]:
    """
    Check if domain accepts catch-all emails by testing a random address.
    
    Args:
        domain: Domain to test
        mx_host: MX hostname to connect to
        
    Returns:
        Tuple of (is_catch_all, transcript)
    """
    # Generate random localpart
    random_localpart = ''.join(
        random.choices(
            string.ascii_lowercase + string.digits,
            k=settings.catch_all_random_localpart_len
        )
    )
    random_email = f"{random_localpart}@{domain}"
    
    logger.debug(f"Testing catch-all for {domain} with {random_email}")
    
    result = await smtp_verify_email(random_email, mx_host)
    
    # If random email is accepted, likely catch-all
    is_catch_all = result.accepted and result.rcpt_to_code in [250, 251]
    
    return is_catch_all, result.transcript


async def smtp_verify_with_retries(
    email: str, 
    mx_hosts: List[str],
    max_retries: int = 3,
    timeout: int = 10
) -> Dict[str, Any]:
    """
    Verify email with multiple MX hosts and retry logic.
    Returns a simplified result dict for compatibility.
    
    Args:
        email: Email address to verify
        mx_hosts: List of MX hostnames (in priority order)
        max_retries: Maximum retry attempts
        timeout: Timeout for operations
        
    Returns:
        Dict with verification results
    """
    if not mx_hosts:
        return {
            "connected": False,
            "accepted": False,
            "response": "No MX hosts available",
            "error": "No MX hosts available"
        }
    
    last_result = {
        "connected": False,
        "accepted": False,
        "response": "No response",
        "error": "No attempts made"
    }
    
    for mx_host in mx_hosts:
        for attempt in range(max_retries):
            try:
                result = await smtp_verify_email(email, mx_host)
                
                # Convert SMTPResult to dict for compatibility
                result_dict = {
                    "connected": result.connected,
                    "accepted": result.accepted,
                    "response": result.rcpt_to_response or "No response",
                    "error": result.error,
                    "code": result.rcpt_to_code,
                    "is_tempfail": result.is_tempfail,
                    "is_permanent_fail": result.is_permanent_fail
                }
                
                # If successful or permanent failure, return immediately
                if result.accepted or result.is_permanent_fail:
                    return result_dict
                
                # If tempfail, try next attempt with backoff
                if result.is_tempfail and attempt < max_retries - 1:
                    backoff_seconds = settings.retry_backoff_list[
                        min(attempt, len(settings.retry_backoff_list) - 1)
                    ]
                    logger.debug(
                        f"Tempfail for {email} at {mx_host}, "
                        f"retrying in {backoff_seconds}s"
                    )
                    await asyncio.sleep(backoff_seconds)
                    continue
                
                # Keep the best result so far
                if result.connected or not last_result["connected"]:
                    last_result = result_dict
                    
            except Exception as e:
                logger.error(f"SMTP verification error for {email} at {mx_host}: {e}")
                if not last_result.get("error"):
                    last_result["error"] = str(e)
        
        # If we got a connection but tempfail, try next MX host
        if last_result["connected"] and not last_result.get("is_tempfail"):
            break
    
    return last_result


def parse_smtp_response(response: str) -> Dict[str, Any]:
    """
    Parse SMTP response for useful information.
    
    Args:
        response: SMTP response string
        
    Returns:
        Dictionary with parsed information
    """
    info = {
        'code': None,
        'message': '',
        'enhanced_code': None,
        'is_user_unknown': False,
        'is_mailbox_full': False,
        'is_policy_rejection': False,
    }
    
    if not response:
        return info
    
    parts = response.split(' ', 1)
    if parts and parts[0].isdigit():
        info['code'] = int(parts[0])
        if len(parts) > 1:
            info['message'] = parts[1]
    
    # Look for enhanced status codes (RFC 3463)
    if '.' in response:
        for part in response.split():
            if '.' in part and len(part.split('.')) == 3:
                try:
                    # Validate enhanced code format
                    class_code, subject, detail = part.split('.')
                    if (class_code.isdigit() and subject.isdigit() and 
                        detail.isdigit()):
                        info['enhanced_code'] = part
                        break
                except ValueError:
                    pass
    
    # Analyze message content for common patterns
    message_lower = info['message'].lower()
    
    if any(phrase in message_lower for phrase in [
        'user unknown', 'no such user', 'user not found',
        'recipient unknown', 'invalid recipient', 'no mailbox'
    ]):
        info['is_user_unknown'] = True
    
    if any(phrase in message_lower for phrase in [
        'mailbox full', 'quota exceeded', 'insufficient storage'
    ]):
        info['is_mailbox_full'] = True
    
    if any(phrase in message_lower for phrase in [
        'policy', 'blocked', 'rejected', 'spam', 'blacklist'
    ]):
        info['is_policy_rejection'] = True
    
    return info


async def batch_smtp_verify(
    email_mx_pairs: List[Tuple[str, str]],
    concurrency_limit: Optional[int] = None
) -> Dict[str, SMTPResult]:
    """
    Verify multiple emails concurrently.
    
    Args:
        email_mx_pairs: List of (email, mx_host) tuples
        concurrency_limit: Maximum concurrent connections
        
    Returns:
        Dictionary mapping email -> SMTPResult
    """
    if concurrency_limit is None:
        concurrency_limit = min(20, settings.max_concurrency)
    
    semaphore = asyncio.Semaphore(concurrency_limit)
    
    async def verify_with_semaphore(email: str, mx_host: str) -> Tuple[str, SMTPResult]:
        async with semaphore:
            result = await smtp_verify_email(email, mx_host)
            return email, result
    
    # Create tasks
    tasks = [
        verify_with_semaphore(email, mx_host) 
        for email, mx_host in email_mx_pairs
    ]
    
    # Execute with timeout
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=settings.smtp_op_timeout * 3
        )
        
        # Process results
        email_results = {}
        for result in results:
            if result is None:
                logger.error(f"Batch SMTP verification error: {result}")
                continue
            if isinstance(result, tuple) and len(result) == 2:
                email, smtp_result = result
                email_results[email] = smtp_result
            else:
                logger.error(f"Batch SMTP verification error: {result}")
                continue
            
        return email_results
        
    except asyncio.TimeoutError:
        logger.error("Batch SMTP verification timeout")
        return {}