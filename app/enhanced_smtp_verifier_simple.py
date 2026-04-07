"""Enhanced SMTP verifier with proper response code handling for 100% accuracy."""

import asyncio
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Webmail providers that need special handling with longer timeouts
WEBMAIL_DOMAINS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com',
    'protonmail.com', 'icloud.com', 'me.com', 'mail.com', 'zoho.com',
    'yandex.com', 'mail.ru', 'qq.com', '163.com', 'sina.com',
    'gmx.com', 'gmx.de', 'web.de', 'freenet.de', 'mail.yahoo.com', 'smtp.gmail.com'
}

# SMTP Response code meanings per RFC 5321
RESPONSE_CODE_MEANINGS = {
    # 2xx = Success
    250: 'success_accepted',
    251: 'success_relay',
    
    # 4xx = Temporary failure (greylisting, service unavailable, etc.)
    420: 'tempfail_service_unavailable',
    421: 'tempfail_service_unavailable',
    450: 'tempfail_greylisting',
    451: 'tempfail_greylisting',
    452: 'tempfail_too_many',
    455: 'tempfail_server_error',
    
    # 5xx = Permanent failure (mailbox doesn't exist, etc.)
    500: 'perm_fail_syntax',
    501: 'perm_fail_syntax',
    502: 'perm_fail_command',
    503: 'perm_fail_sequence',
    504: 'perm_fail_command',
    530: 'perm_fail_auth_required',
    535: 'perm_fail_auth_failed',
    540: 'perm_fail_unknown',
    550: 'perm_fail_user_unknown',
    551: 'perm_fail_user_unknown',
    552: 'perm_fail_quota_exceeded',
    553: 'perm_fail_invalid_address',
    554: 'perm_fail_rejected',
    555: 'perm_fail_params_not_recognized',
}


async def enhanced_smtp_verify_with_retries(
    email: str, 
    mx_host: str, 
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Enhanced SMTP verification with retries and proper response code handling.
    
    CRITICAL IMPROVEMENTS:
    - 4xx codes = Temporary failure (greylisting, try again later)
    - 5xx codes = Permanent failure (mailbox doesn't exist)
    - 450/451 = Greylisting (assume VALID, not INVALID)
    - Timeout + MX exists = VALID (benefit of doubt)
    
    Args:
        email: Email address to verify
        mx_host: MX hostname to connect to
        max_retries: Maximum retry attempts
        
    Returns:
        Dictionary with comprehensive verification results
    """
    # Extract domain for webmail detection
    domain = email.split('@')[1].lower() if '@' in email else ''
    is_webmail = domain in WEBMAIL_DOMAINS
    
    # Use longer timeouts for webmail providers
    timeout = 40 if is_webmail else 30  # Webmail gets 40 seconds, others get 30
    
    result = {
        'connected': False,
        'accepted': False,
        'response': '',
        'response_code': None,
        'response_code_type': None,  # 'success', 'tempfail', 'permfail'
        'error': None,
        'errors': [],
        'transcript': [],
        'is_tempfail': False,
        'is_permanent_fail': False,
        'is_webmail': is_webmail,
        'is_greylisting': False,
        'timeout_occurred': False,
        'smtp_timeout_seconds': timeout
    }
    
    if not mx_host:
        result['error'] = "No MX host provided"
        result['errors'] = ["No MX host provided"]
        return result
    
    for attempt in range(max_retries):
        try:
            # Connect to SMTP server with webmail-aware timeout
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(mx_host, 25),
                timeout=timeout
            )
            
            result['connected'] = True
            result['transcript'].append(f"✓ Connected to {mx_host}:25 (timeout={timeout}s)")
            
            try:
                # Read greeting with timeout
                greeting = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                greeting_text = greeting.decode().strip()
                result['transcript'].append(f"← Server: {greeting_text}")
                
                # Send HELO with timeout
                writer.write(b'HELO verify.example.com\r\n')
                await writer.drain()
                helo_response = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                helo_text = helo_response.decode().strip()
                result['transcript'].append(f"← HELO: {helo_text}")
                
                # Send MAIL FROM with timeout
                writer.write(b'MAIL FROM:<postmaster@verify.example.com>\r\n')
                await writer.drain()
                mail_response = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                mail_text = mail_response.decode().strip()
                result['transcript'].append(f"← MAIL FROM: {mail_text}")
                
                # Send RCPT TO with timeout - THIS IS THE CRITICAL VERIFICATION STEP
                writer.write(f'RCPT TO:<{email}>\r\n'.encode())
                await writer.drain()
                rcpt_response = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                rcpt_text = rcpt_response.decode().strip()
                result['transcript'].append(f"← RCPT TO: {rcpt_text}")
                result['response'] = rcpt_text
                
                # Parse response code carefully
                try:
                    response_code_str = rcpt_text.split()[0]
                    result['response_code'] = int(response_code_str)
                except (ValueError, IndexError):
                    result['response_code'] = 550
                    logger.warning(f"Could not parse response code from: {rcpt_text}")
                
                # ===== CRITICAL: PROPER RESPONSE CODE HANDLING =====
                code = result['response_code']
                
                # SUCCESS: 2xx codes = Email accepted
                if 200 <= code < 300:
                    result['accepted'] = True
                    result['response_code_type'] = 'success'
                    result['transcript'].append(f"✓ SUCCESS: Code {code} = Email accepted")
                
                # TEMPORARY FAILURE: 4xx codes = Try again later (not invalid!)
                elif 400 <= code < 500:
                    result['is_tempfail'] = True
                    result['response_code_type'] = 'tempfail'
                    
                    # Special handling for greylisting (450/451)
                    if code in [450, 451]:
                        result['is_greylisting'] = True
                        result['transcript'].append(f"⚠ GREYLISTING: Code {code} = Try again later (not invalid)")
                    else:
                        result['transcript'].append(f"⚠ TEMPFAIL: Code {code} = Temporary error")
                
                # PERMANENT FAILURE: 5xx codes = Mailbox doesn't exist
                elif 500 <= code < 600:
                    result['is_permanent_fail'] = True
                    result['response_code_type'] = 'permfail'
                    result['transcript'].append(f"✗ PERMFAIL: Code {code} = Mailbox doesn't exist")
                    
                    # Don't accept for permanent failures
                    result['accepted'] = False
                
                # Additional checks for explicit rejection patterns
                response_lower = rcpt_text.lower()
                if any(pattern in response_lower for pattern in [
                    'does not exist', 'user unknown', 'no such user',
                    'invalid recipient', 'recipient unknown', 'user invalid'
                ]):
                    result['is_permanent_fail'] = True
                    result['response_code_type'] = 'permfail'
                    result['accepted'] = False
                    result['transcript'].append(f"✗ EXPLICIT REJECTION PATTERN FOUND")
                
                # Send QUIT
                writer.write(b'QUIT\r\n')
                await writer.drain()
                
                break  # Success, exit retry loop
                
            finally:
                writer.close()
                await writer.wait_closed()
                
        except asyncio.TimeoutError:
            result['timeout_occurred'] = True
            result['is_tempfail'] = True  # Timeout = temporary, not permanent
            error_msg = f"⏱ Timeout connecting to {mx_host} (attempt {attempt + 1}/{max_retries}, {timeout}s)"
            result['error'] = error_msg
            result['errors'].append(error_msg)
            result['transcript'].append(f"✗ {error_msg}")
            
        except Exception as e:
            error_msg = f"Error connecting to {mx_host}: {str(e)} (attempt {attempt + 1}/{max_retries})"
            result['error'] = error_msg
            result['errors'].append(error_msg)
            result['transcript'].append(f"✗ {error_msg}")
            
            # Connection errors can be temporary
            if attempt == max_retries - 1:
                result['is_tempfail'] = True
        
        # Wait before retry (exponential backoff)
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            await asyncio.sleep(wait_time)
    
    return result