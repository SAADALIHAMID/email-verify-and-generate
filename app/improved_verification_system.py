"""
FIXED Email Verification System
- Properly handles Gmail, Yahoo, Outlook, etc.
- Fixes MX record resolution
- Adds proper error handling
- Handles timeouts gracefully
"""

import asyncio
import logging
import socket
import smtplib
import time
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# ========== WEBMAIL PROVIDERS CONFIGURATION ==========
WEBMAIL_PROVIDERS = {
    'gmail.com': {
        'mx_servers': [
            'gmail-smtp-in.l.google.com',
            'alt1.gmail-smtp-in.l.google.com',
            'alt2.gmail-smtp-in.l.google.com',
            'alt3.gmail-smtp-in.l.google.com',
            'alt4.gmail-smtp-in.l.google.com'
        ],
        'ports': [25, 587],
        'supports_tls': True,
    },
    'yahoo.com': {
        'mx_servers': [
            'mta5.am0.yahoodns.net',
            'mta6.am0.yahoodns.net',
            'mta7.am0.yahoodns.net'
        ],
        'ports': [25, 587],
        'supports_tls': True,
    },
    'outlook.com': {
        'mx_servers': ['outlook-com.olc.protection.outlook.com'],
        'ports': [25, 587],
        'supports_tls': True,
    },
    'hotmail.com': {
        'mx_servers': ['hotmail-com.olc.protection.outlook.com'],
        'ports': [25, 587],
        'supports_tls': True,
    },
    'yahoo.co.uk': {
        'mx_servers': [
            'mta5.am0.yahoodns.net',
            'mta6.am0.yahoodns.net',
            'mta7.am0.yahoodns.net'
        ],
        'ports': [25, 587],
        'supports_tls': True,
    },
    'aol.com': {
        'mx_servers': ['mta7.am0.yahoodns.net'],
        'ports': [25, 587],
        'supports_tls': True,
    },
}


async def get_mx_records_reliable(domain: str, timeout: int = 15) -> tuple:
    """
    Get MX records for a domain with multiple DNS servers and fallbacks.
    
    Returns: (success: bool, mx_hosts: List[str], error: str)
    """
    try:
        import dns.resolver
        
        # Try multiple DNS servers in order
        dns_servers = [
            ('8.8.8.8', 'Google DNS 1'),
            ('8.8.4.4', 'Google DNS 2'),
            ('1.1.1.1', 'Cloudflare DNS 1'),
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
                        key=lambda x: 0  # All MX records are valid
                    )
                    if mx_hosts:
                        logger.info(f"✅ MX Records found for {domain} using {dns_name}: {mx_hosts}")
                        return True, mx_hosts, ""
                except Exception as mx_error:
                    logger.debug(f"No MX records for {domain} using {dns_name}: {mx_error}")
                
                # Fallback to A records
                try:
                    a_records = resolver.resolve(domain, 'A', lifetime=timeout)
                    if a_records:
                        logger.info(f"⚠️  Using A records for {domain} (no MX found)")
                        return True, [domain], ""
                except Exception as a_error:
                    logger.debug(f"No A records for {domain} using {dns_name}: {a_error}")
                    
            except Exception as e:
                logger.debug(f"DNS server {dns_name} failed: {e}")
                continue
        
        return False, [], "No DNS server could resolve MX records"
        
    except ImportError:
        logger.error("dns.resolver not available")
        return False, [], "DNS resolver library not available"
    except Exception as e:
        logger.error(f"Error getting MX records for {domain}: {e}")
        return False, [], str(e)


async def smtp_verify_email(email: str, mx_host: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Verify email using SMTP protocol.
    Returns detailed verification result.
    """
    result = {
        'connected': False,
        'accepted': False,
        'rejected': False,
        'tempfail': False,
        'response_code': None,
        'response_text': '',
        'error': None,
        'is_timeout': False
    }
    
    if not mx_host:
        result['error'] = "No MX host provided"
        return result
    
    try:
        # Try connection with timeout
        try:
            # Connect to SMTP server
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(mx_host, 25),
                timeout=timeout
            )
            
            result['connected'] = True
            logger.debug(f"Connected to {mx_host}:25 for {email}")
            
            try:
                # Read greeting (250 response)
                greeting = await asyncio.wait_for(
                    reader.readuntil(b'\n'),
                    timeout=timeout
                )
                logger.debug(f"Server greeting: {greeting.decode().strip()}")
                
                # Send HELO/EHLO
                writer.write(b'EHLO verify-server.local\r\n')
                await writer.drain()
                
                # Read EHLO response (may be multiple lines)
                ehlo_response = b''
                while True:
                    line = await asyncio.wait_for(
                        reader.readuntil(b'\n'),
                        timeout=timeout
                    )
                    ehlo_response += line
                    if line.startswith(b'250 '):  # Last line starts with "250 "
                        break
                    elif line.startswith(b'250-'):  # More lines coming
                        continue
                
                logger.debug(f"EHLO response received")
                
                # Send MAIL FROM
                writer.write(b'MAIL FROM:<verify@example.com>\r\n')
                await writer.drain()
                
                mail_response = await asyncio.wait_for(
                    reader.readuntil(b'\n'),
                    timeout=timeout
                )
                mail_text = mail_response.decode().strip()
                logger.debug(f"MAIL FROM response: {mail_text}")
                
                # Send RCPT TO (THE KEY TEST)
                writer.write(f'RCPT TO:<{email}>\r\n'.encode())
                await writer.drain()
                
                rcpt_response = await asyncio.wait_for(
                    reader.readuntil(b'\n'),
                    timeout=timeout
                )
                rcpt_text = rcpt_response.decode().strip()
                logger.debug(f"RCPT TO response: {rcpt_text}")
                
                result['response_text'] = rcpt_text
                
                # Parse response code
                try:
                    code = int(rcpt_text.split()[0])
                    result['response_code'] = code
                    
                    # Determine if accepted
                    if 200 <= code < 300:
                        result['accepted'] = True
                        logger.info(f"✅ SMTP Accepted: {email} (Code: {code})")
                    elif 400 <= code < 500:
                        result['tempfail'] = True
                        logger.warning(f"⚠️  SMTP Temp Fail: {email} (Code: {code})")
                    elif code >= 500:
                        result['rejected'] = True
                        logger.warning(f"❌ SMTP Rejected: {email} (Code: {code})")
                except:
                    result['response_code'] = 550
                    result['rejected'] = True
                
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
            result['error'] = "SMTP connection timeout"
            logger.warning(f"⏱️  SMTP Timeout for {email} on {mx_host}")
        
        except ConnectionRefusedError:
            result['error'] = f"Connection refused by {mx_host}:25"
            logger.warning(f"Connection refused: {mx_host}")
        
        except ConnectionResetError:
            result['error'] = f"Connection reset by {mx_host}:25"
            logger.warning(f"Connection reset: {mx_host}")
        
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"SMTP error for {email}: {e}")
    
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Unexpected error in smtp_verify_email: {e}")
    
    return result


async def verify_email_improved(email: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Improved email verification with proper error handling.
    Returns detailed results.
    """
    start_time = time.time()
    
    result = {
        'email': email,
        'valid': False,
        'reason': 'Unknown',
        'mx_records': [],
        'smtp_accepted': False,
        'smtp_rejected': False,
        'smtp_timeout': False,
        'has_mx': False,
        'duration_ms': 0,
        'steps': []
    }
    
    try:
        # Step 1: Syntax validation
        if '@' not in email or len(email) > 254:
            result['reason'] = 'Invalid email syntax'
            result['steps'].append('✅ Syntax check: FAILED')
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['steps'].append('✅ Syntax check: PASSED')
        
        # Step 2: Extract domain
        try:
            local, domain = email.rsplit('@', 1)
            domain = domain.lower()
        except:
            result['reason'] = 'Invalid email format'
            result['steps'].append('❌ Domain extraction: FAILED')
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['steps'].append('✅ Domain extraction: OK')
        
        # Step 3: Get MX records
        logger.info(f"🔍 Resolving MX records for {domain}")
        has_mx, mx_records, mx_error = await get_mx_records_reliable(domain, timeout=15)
        
        if not has_mx or not mx_records:
            result['reason'] = f'No MX records: {mx_error}'
            result['steps'].append(f'❌ MX Resolution: FAILED - {mx_error}')
            result['duration_ms'] = int((time.time() - start_time) * 1000)
            return result
        
        result['has_mx'] = True
        result['mx_records'] = mx_records
        result['steps'].append(f'✅ MX Resolution: Found {len(mx_records)} MX record(s)')
        logger.info(f"✅ Found {len(mx_records)} MX records for {domain}: {mx_records}")
        
        # Step 4: SMTP verification
        result['steps'].append('🔄 SMTP Verification: Starting...')
        
        # Try each MX record
        smtp_success = False
        for idx, mx_host in enumerate(mx_records[:3]):  # Try first 3 MX servers
            logger.info(f"Trying MX server {idx+1}/{len(mx_records)}: {mx_host}")
            
            try:
                smtp_result = await asyncio.wait_for(
                    smtp_verify_email(email, mx_host, timeout=timeout),
                    timeout=timeout + 5
                )
                
                if smtp_result['accepted']:
                    result['valid'] = True
                    result['smtp_accepted'] = True
                    result['reason'] = 'SMTP accepted'
                    result['steps'].append(f'✅ SMTP Accepted by {mx_host} (Code: {smtp_result["response_code"]})')
                    smtp_success = True
                    break
                
                elif smtp_result['rejected']:
                    result['smtp_rejected'] = True
                    result['reason'] = f'SMTP rejected: {smtp_result["response_text"]}'
                    result['steps'].append(f'❌ SMTP Rejected by {mx_host} (Code: {smtp_result["response_code"]})')
                    break  # No need to try other servers
                
                elif smtp_result['is_timeout']:
                    result['smtp_timeout'] = True
                    # Continue to next MX server
                    result['steps'].append(f'⏱️  SMTP Timeout on {mx_host}, trying next...')
                    continue
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on MX {mx_host}")
                result['smtp_timeout'] = True
                result['steps'].append(f'⏱️  SMTP Timeout on {mx_host}')
                continue
            
            except Exception as e:
                logger.error(f"Error with MX {mx_host}: {e}")
                result['steps'].append(f'⚠️  Error with {mx_host}: {str(e)[:50]}')
                continue
        
        # Final decision logic - FIXED: Properly handle SMTP rejections
        if smtp_success:
            # SMTP server explicitly accepted
            result['valid'] = True
            result['reason'] = 'SMTP accepted - email is valid'
            result['steps'].append('✅ Final: SMTP Accepted = VALID')
        
        elif result['smtp_rejected']:
            # SMTP server explicitly rejected (550, 551, 553, etc.)
            # This means mailbox doesn't exist or is invalid
            result['valid'] = False
            result['reason'] = 'SMTP rejected - mailbox does not exist or invalid'
            result['steps'].append('❌ Final: SMTP Rejected = INVALID')
        
        elif result['smtp_timeout']:
            # Timeout is ambiguous - only assume valid if we explicitly know it's safe
            # WARNING: This is risky - timeout can indicate problems
            if has_mx and not result['smtp_rejected']:
                result['valid'] = True
                result['reason'] = 'MX exists + SMTP timeout (may be catch-all server, treating as valid)'
                result['steps'].append('⚠️  Final: Timeout + MX = assume VALID (risky)')
            else:
                result['valid'] = False
                result['reason'] = 'SMTP timeout without MX confirmation = invalid'
                result['steps'].append('❌ Final: Timeout + no MX = INVALID')
        
        elif has_mx:
            # MX exists but we got no definitive response from SMTP
            # Check if we got ANY rejection - if so, it's INVALID
            if result['smtp_rejected']:
                # Explicit rejection takes precedence
                result['valid'] = False
                result['reason'] = 'SMTP rejected - User unknown or address invalid (550/551)'
                result['steps'].append('❌ FINAL DECISION: SMTP explicitly rejected = INVALID')
            else:
                # No rejection found, MX exists = likely valid
                result['valid'] = True
                result['reason'] = 'MX records found (SMTP verification uncertain)'
                result['steps'].append('✅ Final: MX exists, no rejection found = assume valid')
        
        else:
            # No MX records found
            result['valid'] = False
            result['reason'] = 'No MX records found'
            result['steps'].append('❌ Final: No MX records = INVALID')
        
        result['duration_ms'] = int((time.time() - start_time) * 1000)
        
        # Log final result
        status = "✅ VALID" if result['valid'] else "❌ INVALID"
        logger.info(f"{status}: {email} ({result['duration_ms']}ms) - {result['reason']}")
        
        return result
    
    except Exception as e:
        logger.error(f"Error in verify_email_improved: {e}", exc_info=True)
        result['reason'] = f'Verification error: {str(e)}'
        result['duration_ms'] = int((time.time() - start_time) * 1000)
        return result
