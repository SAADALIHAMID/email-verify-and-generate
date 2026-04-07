"""
ENHANCED Email Verification System - Production Grade
- Proper SMTP response code handling (550, 4xx, 2xx)
- MX record validation with multiple DNS servers
- Catch-all detection with real test emails
- Disposable domain detection
- Role-based email detection
- Comprehensive error handling
"""

import asyncio
import logging
import socket
import time
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re

logger = logging.getLogger(__name__)

# ========== CONSTANTS ==========

# SMTP Response Code Categories
SMTP_CODES = {
    'ACCEPTED': [250, 251, 252],          # 2xx - Email accepted
    'TEMPFAIL': [421, 450, 451, 452],     # 4xx - Temporary failure
    'REJECTED': [500, 501, 502, 503, 504, 505, 510, 511, 550, 551, 552, 553, 554, 555],  # 5xx - Permanent rejection
    'USER_UNKNOWN': [550, 551],           # Specific: User doesn't exist
    'INVALID_ADDRESS': [553, 555],        # Specific: Invalid format
}

# SMTP Response Messages Indicating Invalid User
INVALID_USER_INDICATORS = [
    'user unknown',
    'user not found',
    'no such user',
    'recipient unknown',
    'address rejected',
    'invalid address',
    'unknown user',
    'does not exist',
    'not a valid',
    'mailbox not found',
]

# Webmail providers with special handling
WEBMAIL_PROVIDERS = {
    'gmail.com': {
        'mx_servers': ['gmail-smtp-in.l.google.com', 'alt1.gmail-smtp-in.l.google.com'],
        'ports': [25, 587],
        'timeout': 40,
        'strict_verification': True,
    },
    'googlemail.com': {
        'mx_servers': ['gmail-smtp-in.l.google.com', 'alt1.gmail-smtp-in.l.google.com'],
        'ports': [25, 587],
        'timeout': 40,
        'strict_verification': True,
    },
    'yahoo.com': {
        'mx_servers': ['mta5.am0.yahoodns.net', 'mta6.am0.yahoodns.net'],
        'ports': [25, 587],
        'timeout': 50,
        'strict_verification': False,  # May have greylisting
    },
    'outlook.com': {
        'mx_servers': ['outlook-com.olc.protection.outlook.com'],
        'ports': [25, 587],
        'timeout': 45,
        'strict_verification': True,
    },
    'hotmail.com': {
        'mx_servers': ['hotmail-com.olc.protection.outlook.com'],
        'ports': [25, 587],
        'timeout': 45,
        'strict_verification': True,
    },
    'icloud.com': {
        'mx_servers': ['mx01.mail.icloud.com', 'mx02.mail.icloud.com'],
        'ports': [25, 587],
        'timeout': 45,
        'strict_verification': True,
    },
    'aol.com': {
        'mx_servers': ['mta7.am0.yahoodns.net'],
        'ports': [25, 587],
        'timeout': 50,
        'strict_verification': False,
    },
    'zoho.com': {
        'mx_servers': ['mx.zoho.com', 'mx2.zoho.com'],
        'ports': [25, 587],
        'timeout': 35,
        'strict_verification': True,
    },
    'protonmail.com': {
        'mx_servers': ['mail.protonmail.ch'],
        'ports': [25],
        'timeout': 30,
        'strict_verification': False,  # Blocks SMTP verification
    }
}


def load_disposable_domains() -> set:
    """Load disposable email domains from file."""
    try:
        domains_file = Path(__file__).parent / 'disposable_domains.txt'
        if domains_file.exists():
            with open(domains_file, 'r', encoding='utf-8') as f:
                domains = {line.strip().lower() for line in f if line.strip() and not line.startswith('#')}
                logger.info(f"Loaded {len(domains)} disposable domains")
                return domains
    except Exception as e:
        logger.error(f"Error loading disposable domains: {e}")
    return set()


def load_role_based_prefixes() -> set:
    """Load role-based email prefixes from file."""
    try:
        prefixes_file = Path(__file__).parent / 'role_based_prefixes.txt'
        if prefixes_file.exists():
            with open(prefixes_file, 'r', encoding='utf-8') as f:
                prefixes = {line.strip().lower() for line in f if line.strip() and not line.startswith('#')}
                logger.info(f"Loaded {len(prefixes)} role-based prefixes")
                return prefixes
    except Exception as e:
        logger.error(f"Error loading role-based prefixes: {e}")
    return set()


# Cache databases (loaded on first use)
_disposable_domains: Optional[set] = None
_role_based_prefixes: Optional[set] = None

def get_disposable_domains() -> set:
    global _disposable_domains
    if _disposable_domains is None:
        _disposable_domains = load_disposable_domains()
    return _disposable_domains

def get_role_based_prefixes() -> set:
    global _role_based_prefixes
    if _role_based_prefixes is None:
        _role_based_prefixes = load_role_based_prefixes()
    return _role_based_prefixes


async def get_mx_records_reliable(domain: str, timeout: int = 15) -> Tuple[bool, List[str], str]:
    """
    Get MX records for a domain with multiple DNS servers.
    
    Returns:
        (success: bool, mx_hosts: List[str], error: str)
    """
    try:
        import dns.resolver
        
        # Try multiple DNS servers in order
        dns_servers = [
            ('8.8.8.8', 'Google DNS'),
            ('8.8.4.4', 'Google DNS 2'),
            ('1.1.1.1', 'Cloudflare DNS'),
            ('1.0.0.1', 'Cloudflare DNS 2'),
        ]
        
        for dns_ip, dns_name in dns_servers:
            try:
                resolver = dns.resolver.Resolver()
                resolver.nameservers = [dns_ip]
                resolver.timeout = timeout
                resolver.lifetime = timeout + 5
                
                # Try MX records first
                try:
                    mx_records = resolver.resolve(domain, 'MX', lifetime=timeout)
                    mx_hosts = sorted(
                        [str(mx.exchange).rstrip('.') for mx in mx_records],
                        key=lambda x: 0
                    )
                    if mx_hosts:
                        logger.info(f"✅ MX Records found for {domain} using {dns_name}: {mx_hosts}")
                        return True, mx_hosts, ""
                except Exception as mx_error:
                    logger.debug(f"No MX records for {domain} using {dns_name}: {mx_error}")
                    
            except Exception as e:
                logger.debug(f"DNS server {dns_name} failed: {e}")
                continue
        
        return False, [], "No DNS server could resolve MX records"
        
    except ImportError:
        logger.error("dns.resolver not available - install dnspython")
        return False, [], "DNS resolver library not available"
    except Exception as e:
        logger.error(f"Error getting MX records for {domain}: {e}")
        return False, [], str(e)


def parse_smtp_response_code(response: str) -> Tuple[int, str]:
    """
    Parse SMTP response code and message.
    
    Args:
        response: SMTP response string (e.g., "250 OK" or "550 User unknown")
    
    Returns:
        (code: int, message: str)
    """
    parts = response.split(None, 1)
    try:
        code = int(parts[0]) if parts else 0
        message = parts[1] if len(parts) > 1 else ""
        return code, message
    except (ValueError, IndexError):
        return 0, response


def is_invalid_user_response(code: Optional[int], message: str) -> bool:
    """
    Check if SMTP response indicates user doesn't exist.
    
    Args:
        code: SMTP response code (or None)
        message: SMTP response message
    
    Returns:
        True if response indicates user unknown/invalid
    """
    # Check if code is None
    if code is None:
        return False
    
    # Check if it's a rejection code
    if code not in SMTP_CODES['REJECTED']:
        return False
    
    # Check if message indicates user unknown
    message_lower = message.lower()
    for indicator in INVALID_USER_INDICATORS:
        if indicator in message_lower:
            return True
    
    # 550/551 codes are usually user unknown
    return code in SMTP_CODES['USER_UNKNOWN']


async def smtp_verify_email(
    email: str, 
    mx_host: str, 
    timeout: int = 30,
    use_helo: bool = True
) -> Dict[str, Any]:
    """
    Verify email using SMTP protocol with proper response code handling.
    
    Args:
        email: Email address to verify
        mx_host: SMTP server hostname
        timeout: Connection timeout in seconds
        use_helo: Use HELO instead of EHLO for older servers
    
    Returns:
        Dictionary with SMTP verification results
    """
    result = {
        'connected': False,
        'accepted': False,
        'rejected': False,
        'tempfail': False,
        'response_code': None,
        'response_text': '',
        'error': None,
        'is_timeout': False,
        'transcript': []
    }
    
    if not mx_host:
        result['error'] = "No MX host provided"
        return result
    
    try:
        try:
            # Connect to SMTP server on port 25
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(mx_host, 25),
                timeout=timeout
            )
            
            result['connected'] = True
            logger.debug(f"✅ Connected to {mx_host}:25 for {email}")
            
            try:
                # Read greeting
                greeting = await asyncio.wait_for(
                    reader.readuntil(b'\n'),
                    timeout=timeout
                )
                greeting_text = greeting.decode().strip()
                result['transcript'].append(f"[Server] {greeting_text}")
                logger.debug(f"Server greeting: {greeting_text}")
                
                # Send EHLO/HELO with a more realistic hostname
                helo_hostname = "mail.verification-platform.com"
                helo_cmd = f'HELO {helo_hostname}\r\n'.encode() if use_helo else f'EHLO {helo_hostname}\r\n'.encode()
                writer.write(helo_cmd)
                await writer.drain()
                result['transcript'].append(f"[Client] {'HELO' if use_helo else 'EHLO'} {helo_hostname}")
                
                # Read EHLO/HELO response
                ehlo_response = b''
                while True:
                    line = await asyncio.wait_for(
                        reader.readuntil(b'\n'),
                        timeout=timeout
                    )
                    ehlo_response += line
                    line_text = line.decode().strip()
                    result['transcript'].append(f"[Server] {line_text}")
                    if line.startswith(b'250 '):
                        break
                    elif not line.startswith(b'250-'):
                        break
                
                # Send MAIL FROM with a more realistic sender
                writer.write(b'MAIL FROM:<verify@verification-platform.com>\r\n')
                await writer.drain()
                result['transcript'].append("[Client] MAIL FROM:<verify@verification-platform.com>")
                
                mail_response = await asyncio.wait_for(
                    reader.readuntil(b'\n'),
                    timeout=timeout
                )
                mail_text = mail_response.decode().strip()
                result['transcript'].append(f"[Server] {mail_text}")
                logger.debug(f"MAIL FROM response: {mail_text}")
                
                # Send RCPT TO (THE CRITICAL TEST)
                writer.write(f'RCPT TO:<{email}>\r\n'.encode())
                await writer.drain()
                result['transcript'].append(f"[Client] RCPT TO:<{email}>")
                
                rcpt_response = await asyncio.wait_for(
                    reader.readuntil(b'\n'),
                    timeout=timeout
                )
                rcpt_text = rcpt_response.decode().strip()
                result['transcript'].append(f"[Server] {rcpt_text}")
                logger.debug(f"RCPT TO response: {rcpt_text}")
                
                result['response_text'] = rcpt_text
                
                # Parse response code
                code, message = parse_smtp_response_code(rcpt_text)
                result['response_code'] = code
                
                # Determine result based on code
                if code in SMTP_CODES['ACCEPTED']:
                    result['accepted'] = True
                    logger.info(f"✅ SMTP Accepted: {email} (Code: {code})")
                
                elif code in SMTP_CODES['TEMPFAIL']:
                    result['tempfail'] = True
                    logger.warning(f"⚠️  SMTP Tempfail: {email} (Code: {code})")
                
                elif code in SMTP_CODES['REJECTED']:
                    result['rejected'] = True
                    logger.warning(f"❌ SMTP Rejected: {email} (Code: {code}) - {message}")
                    
                    # Check if it's specifically a "user unknown" response
                    if is_invalid_user_response(code, message):
                        logger.warning(f"⚠️  User doesn't exist: {email}")
                
                else:
                    # Unknown code
                    result['rejected'] = True
                    logger.warning(f"❌ Unknown SMTP code: {code}")
                
                # Send QUIT
                try:
                    writer.write(b'QUIT\r\n')
                    await writer.drain()
                except:
                    pass
                
            finally:
                # Close connection
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass
        
        except asyncio.TimeoutError:
            result['is_timeout'] = True
            result['error'] = f"SMTP timeout after {timeout}s on {mx_host}"
            logger.warning(f"⏱️  SMTP Timeout for {email} on {mx_host}")
        
        except ConnectionRefusedError:
            result['error'] = f"Connection refused by {mx_host}:25"
            logger.warning(f"Connection refused: {mx_host}")
        
        except ConnectionResetError:
            result['error'] = f"Connection reset by {mx_host}:25"
            logger.warning(f"Connection reset: {mx_host}")
        
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"SMTP error for {email} on {mx_host}: {e}")
    
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Unexpected error in smtp_verify_email: {e}")
    
    return result


async def batch_smtp_verify(
    emails: List[str],
    mx_host: str,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Verify multiple emails for the SAME domain in a SINGLE SMTP connection.
    MUCH faster than individual checks.
    
    Returns a dict mapping email -> (bool, response_code, response_text)
    """
    results = {}
    if not mx_host:
        return results
    
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25), timeout=timeout
        )
        try:
            # Greet
            await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
            
            # HELO/EHLO
            helo_hostname = "mail.verification-platform.com"
            writer.write(f'EHLO {helo_hostname}\r\n'.encode())
            await writer.drain()
            while True:
                line = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                if b'250 ' in line or not b'250-' in line: break
            
            # MAIL FROM
            writer.write(b'MAIL FROM:<verify@verification-platform.com>\r\n')
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
            
            # RCPT TO for each pattern
            for email in emails:
                writer.write(f'RCPT TO:<{email}>\r\n'.encode())
                await writer.drain()
                resp = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=timeout)
                resp_text = resp.decode().strip()
                code, msg = parse_smtp_response_code(resp_text)
                
                results[email] = {
                    'accepted': code in [250, 251, 252],
                    'rejected': code in SMTP_CODES['REJECTED'],
                    'code': code,
                    'text': resp_text,
                    'status': 'INVALID' if code in [550, 551] else 'RISKY' if code >= 400 else 'DELIVERABLE' if code < 300 else 'UNKNOWN'
                }
                
                # Remove break to check ALL patterns as per user request
                # if results[email]['accepted']:
                #     break
            
            writer.write(b'QUIT\r\n')
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    except Exception as e:
        logger.debug(f"Batch SMTP failure on {mx_host}: {e}")
    
    return results


async def detect_catch_all(domain: str, mx_records: List[str], timeout: int = 12) -> Tuple[bool, str]:
    """
    Check if a domain is a catch-all server (accepts all email addresses).
    Uses a 'Triple Random Check' for maximum accuracy against lying servers.
    """
    if not mx_records:
        return False, "No MX records"
    
    import random
    import string
    
    # 🕵️ TRIPLE RANDOM CHECK PATTERNS:
    # 1. High-entropy random string (Long)
    # 2. Short numeric random string (pattern-based)
    # 3. Common 'test' prefix pattern
    test_patterns = [
        ''.join(random.choices(string.ascii_lowercase + string.digits, k=25)), # verify-test-sd92...
        'test.' + ''.join(random.choices(string.digits, k=5)),                  # test.12345
        'random.user'                                                          # random.user
    ]
    
    accepted_count = 0
    accepted_patterns = []
    
    try:
        # Try verifying each pattern with the first MX server
        for p in test_patterns:
            test_email = f"{p}@{domain}"
            res = await smtp_verify_email(test_email, mx_records[0], timeout=timeout)
            if res['accepted']:
                accepted_count += 1
                accepted_patterns.append(test_email)
            
            # SMALL DELAY between tests to avoid rate limits
            await asyncio.sleep(0.5)
            
        # If ANY of the three random patterns are accepted, it's a catch-all
        if accepted_count > 0:
            return True, f"Catch-all detected: Server accepted {accepted_count}/3 fake patterns (e.g. {accepted_patterns[0]})"
            
        return False, ""
    except Exception as e:
        logger.debug(f"Catch-all detection failed for {domain}: {e}")
        return False, ""


async def verify_email_enhanced(email: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Enhanced email verification using 4-layer approach.
    
    Layers:
    1. Syntax check
    2. MX record validation
    3. SMTP handshake
    4. Catch-all/Disposable/Role-based detection
    
    Args:
        email: Email address to verify
        timeout: Total verification timeout
    
    Returns:
        Comprehensive verification result dictionary
    """
    start_time = time.time()
    
    result = {
        'email': email,
        'valid': False,
        'status': 'UNKNOWN',
        'reason': 'Unknown',
        'confidence': 0,
        
        # Layer results
        'syntax_valid': False,
        'has_mx': False,
        'smtp_accepted': False,
        'smtp_rejected': False,
        'smtp_timeout': False,
        'is_catch_all': False,
        'is_disposable': False,
        'is_role_based': False,
        
        # Details
        'mx_records': [],
        'smtp_response_code': None,
        'smtp_response_text': '',
        'smtp_transcript': [],
        'domain': '',
        'local_part': '',
        
        'duration_ms': 0,
        'steps': []
    }
    
    try:
        # ========== LAYER 1: SYNTAX CHECK ==========
        if '@' not in email or len(email) > 254 or email.startswith('@') or email.endswith('@'):
            result['reason'] = 'Invalid email syntax'
            result['steps'].append('❌ Syntax check: FAILED')
            result['status'] = 'INVALID'
            result['confidence'] = 100
            result['valid'] = False
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['syntax_valid'] = True
        result['steps'].append('✅ Syntax check: PASSED')
        
        # Extract domain and local part
        try:
            local, domain = email.rsplit('@', 1)
            domain = domain.lower()
            result['domain'] = domain
            result['local_part'] = local
        except:
            result['reason'] = 'Invalid email format'
            result['steps'].append('❌ Domain extraction: FAILED')
            result['status'] = 'INVALID'
            result['confidence'] = 100
            result['valid'] = False
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['steps'].append(f'✅ Domain extraction: {domain}')
        
        # ========== LAYER 2: MX RECORD VALIDATION ==========
        logger.info(f"🔍 Checking MX records for {domain}")
        has_mx, mx_records, mx_error = await get_mx_records_reliable(domain, timeout=15)
        
        if not has_mx or not mx_records:
            result['reason'] = f'No MX records found'
            result['steps'].append(f'❌ MX Resolution: FAILED - {mx_error}')
            result['status'] = 'INVALID'
            result['confidence'] = 100
            result['valid'] = False
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['has_mx'] = True
        result['mx_records'] = mx_records
        result['steps'].append(f'✅ MX Resolution: Found {len(mx_records)} record(s)')
        logger.info(f"✅ Found {len(mx_records)} MX records for {domain}: {mx_records}")
        
        # ========== CHECK 4A: DISPOSABLE DOMAIN ==========
        disposable_domains = get_disposable_domains()
        if domain in disposable_domains:
            result['is_disposable'] = True
            result['reason'] = 'Disposable/temporary email domain'
            result['steps'].append('🗑️  Disposable domain detected')
            result['status'] = 'DISPOSABLE'
            result['confidence'] = 100
            result['valid'] = False
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['steps'].append('✅ Not a disposable domain')
        
        # ========== CHECK 4B: ROLE-BASED EMAIL ==========
        role_based_prefixes = get_role_based_prefixes()
        if local.lower() in role_based_prefixes:
            result['is_role_based'] = True
            result['steps'].append(f'⚠️  Role-based email detected: {local}')
        
        # ========== CHECK 4C: EARLY CATCH-ALL DETECTION ==========
        # Check if domain is catch-all BEFORE we do SMTP verification
        logger.info(f"🔍 Checking for catch-all server on {domain}")
        is_catch_all, catch_all_reason = await detect_catch_all(domain, mx_records, timeout=10)
        
        if is_catch_all:
            # Domain is catch-all - cannot verify individual users
            result['is_catch_all'] = True
            result['valid'] = False
            result['status'] = 'RISKY_CATCH_ALL'
            result['confidence'] = 70
            result['reason'] = f'Catch-all server detected - accepts all emails to {domain}'
            result['steps'].append('🔴 Catch-all server detected - cannot verify individual users')
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            logger.warning(f"⚠️  RISKY_CATCH_ALL: {email} - {catch_all_reason}")
            return result
        
        result['steps'].append('✅ Not a catch-all server')
        
        # ========== LAYER 3: SMTP HANDSHAKE ==========
        logger.info(f"🔄 Starting SMTP verification for {email}")
        result['steps'].append('🔄 SMTP Verification: Starting...')
        
        # Try each MX record
        smtp_success = False
        last_error = None
        smtp_connection_refused = False  # Track if all servers refused connection
        
        for idx, mx_host in enumerate(mx_records[:3]):  # Try first 3 MX servers
            logger.info(f"Trying MX server {idx+1}/{len(mx_records)}: {mx_host}")
            
            try:
                smtp_result = await asyncio.wait_for(
                    smtp_verify_email(email, mx_host, timeout=timeout),
                    timeout=timeout + 5
                )
                
                result['smtp_transcript'] = smtp_result.get('transcript', [])
                
                if smtp_result['accepted']:
                    # Email accepted by SMTP
                    result['smtp_accepted'] = True
                    result['smtp_response_code'] = smtp_result.get('response_code')
                    result['smtp_response_text'] = smtp_result.get('response_text', '')
                    result['steps'].append(f'✅ SMTP Accepted: {mx_host} (Code: {smtp_result.get("response_code")})')
                    logger.info(f"✅ Email accepted by {mx_host}")
                    smtp_success = True
                    break
                
                elif smtp_result['rejected']:
                    # Email explicitly rejected
                    result['smtp_rejected'] = True
                    result['smtp_response_code'] = smtp_result.get('response_code')
                    result['smtp_response_text'] = smtp_result.get('response_text', '')
                    result['steps'].append(f'❌ SMTP Rejected: {mx_host} (Code: {smtp_result.get("response_code")})')
                    logger.warning(f"❌ Email rejected by {mx_host}: {smtp_result.get('response_text', '')}")
                    
                    # If it's a definitive rejection, stop trying
                    code = smtp_result.get('response_code')
                    message = smtp_result.get('response_text', '')
                    if code is not None and is_invalid_user_response(code, message):
                        logger.info(f"User doesn't exist on {mx_host} - stopping verification")
                        break  # No need to try other servers
                    
                elif smtp_result['is_timeout']:
                    result['smtp_timeout'] = True
                    result['steps'].append(f'⏱️  Timeout on {mx_host}, trying next...')
                    last_error = f"Timeout: {smtp_result.get('error', 'Unknown')}"
                    continue
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on MX {mx_host}")
                result['smtp_timeout'] = True
                result['steps'].append(f'⏱️  Timeout on {mx_host}')
                last_error = f"Timeout on {mx_host}"
                continue
            
            except (ConnectionRefusedError, ConnectionResetError) as e:
                logger.warning(f"Connection refused/reset by {mx_host}: {e}")
                smtp_connection_refused = True
                result['steps'].append(f'🚫 Connection refused by {mx_host}')
                last_error = str(e)
                continue
            
            except Exception as e:
                logger.error(f"Error with MX {mx_host}: {e}")
                result['steps'].append(f'⚠️  Error with {mx_host}: {str(e)[:50]}')
                last_error = str(e)
                continue
        
        # ========== FINAL DECISION LOGIC ==========
        
        if result['smtp_rejected']:
            # SMTP server explicitly rejected the email
            code = result.get('smtp_response_code')
            message = result.get('smtp_response_text', '')

            if code is not None and is_invalid_user_response(code, message):
                # User doesn't exist
                result['valid'] = False
                result['status'] = 'INVALID'
                result['confidence'] = 99
                result['reason'] = f'SMTP rejected: User does not exist (Code {code})'
                result['steps'].append(f'❌ FINAL: User unknown = INVALID')
                logger.info(f"❌ INVALID: {email} - User unknown/address rejected")
            else:
                # Other rejection
                result['valid'] = False
                result['status'] = 'INVALID'
                result['confidence'] = 98
                result['reason'] = f'SMTP rejected: {message}'
                result['steps'].append(f'❌ FINAL: SMTP rejected = INVALID')
                logger.info(f"❌ INVALID: {email} - {message}")

        elif result['smtp_accepted']:
            # SMTP explicitly accepted
            result['valid'] = True
            result['status'] = 'DELIVERABLE'
            result['confidence'] = 99
            result['reason'] = 'SMTP accepted - email is valid'
            result['steps'].append('✅ FINAL: SMTP accepted = DELIVERABLE')
            logger.info(f"✅ DELIVERABLE: {email}")

        elif result['is_catch_all']:
            # Catch-all domain detected
            result['valid'] = False
            result['status'] = 'RISKY_CATCH_ALL'
            result['confidence'] = 70
            result['reason'] = f'Catch-all server detected - accepts all emails to {result["domain"]}'
            result['steps'].append('🔴 FINAL: Catch-all domain = RISKY')
            logger.warning(f"⚠️  RISKY_CATCH_ALL: {email} - Catch-all domain")

        elif result['smtp_timeout']:
            # Timeout - server didn't respond within timeout period
            result['valid'] = False
            result['status'] = 'RISKY_TEMPFAIL'
            result['confidence'] = 20
            result['reason'] = 'SMTP server timeout - unable to verify (IP may be blocked/greylisted)'
            result['steps'].append('⏱️  FINAL: SMTP timeout = UNDETERMINED (unable to verify)')
            logger.warning(f"⚠️  RISKY_TEMPFAIL: {email} - Server timeout (possible greylisting)")

        elif smtp_connection_refused:
            # All SMTP servers refused connection
            result['valid'] = False
            result['status'] = 'RISKY_BLOCKED'
            result['confidence'] = 20
            result['reason'] = 'SMTP servers refused connection - our IP may be blocked'
            result['steps'].append('🚫 FINAL: Connection refused = IP blocked (unable to verify)')
            logger.warning(f"⚠️  RISKY_BLOCKED: {email} - Server blocked our IP")

        else:
            # MX exists but SMTP never connected or gave no definitive response
            result['valid'] = False
            result['status'] = 'RISKY_UNVERIFIED'
            result['confidence'] = 20
            result['reason'] = 'SMTP connection failed - unable to verify user existence'
            result['steps'].append('❌ FINAL: No SMTP response = UNVERIFIED (connection refused or blocked)')
            logger.warning(f"⚠️  RISKY_UNVERIFIED: {email} - No SMTP response")
        
        result['duration_ms'] = int((time.time() - start_time) * 1000)
        
        # Log final result
        logger.info(f"📊 Result for {email}: {result['status']} (Confidence: {result['confidence']}%)")
        
        return result
    
    except Exception as e:
        logger.error(f"Error in verify_email_enhanced: {e}", exc_info=True)
        result['reason'] = f'Verification error: {str(e)}'
        result['status'] = 'INVALID'
        result['valid'] = False
        result['confidence'] = 0
        result['duration_ms'] = int((time.time() - start_time) * 1000)
        return result


# For backward compatibility
verify_email_improved = verify_email_enhanced
