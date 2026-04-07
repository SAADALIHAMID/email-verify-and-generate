"""
Advanced Email Verification Engine - Enterprise Grade
Implements 18-step verification pipeline with confidence scoring
"""

import asyncio
import re
import logging
from typing import Dict, Any, Tuple, List
from enum import Enum
import socket
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    """Verification status with confidence levels"""
    VALID = "DELIVERABLE"
    RISKY = "RISKY"
    INVALID = "INVALID"
    DISPOSABLE = "DISPOSABLE"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(str, Enum):
    """Confidence scoring levels"""
    VERY_HIGH = "95-98%"  # VALID
    HIGH = "80-94%"       # RISKY but likely valid
    MEDIUM = "60-79%"     # RISKY
    LOW = "40-59%"        # RISKY/UNKNOWN
    VERY_LOW = "<40%"     # INVALID


FAKE_PATTERNS = [
    r'^test@',
    r'^admin@',
    r'^demo@',
    r'^example@',
    r'^asdf@',
    r'^qwerty@',
    r'^dummy@',
]

WEBMAIL_PROVIDERS = {
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com',
    'protonmail.com', 'icloud.com', 'me.com', 'mail.com', 'zoho.com',
    'yandex.com', 'mail.ru', 'qq.com', '163.com', 'sina.com',
    'gmx.com', 'gmx.de', 'web.de', 'freenet.de'
}

FAKE_ACCEPTOR_DOMAINS = {
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
    'google.com', 'microsoft.com'
}

ROLE_BASED_PREFIXES = {
    'admin', 'info', 'support', 'sales', 'contact', 'help',
    'noreply', 'no-reply', 'abuse', 'security', 'postmaster',
    'webmaster', 'mailer-daemon', 'news', 'hello', 'mail',
    'marketing', 'hr', 'billing', 'accounting', 'finance',
    'legal', 'operations', 'management', 'team', 'group'
}

DISPOSABLE_DOMAINS = {
    'tempmail.com', '10minutemail.com', 'mailinator.com', 'yopmail.com',
    'guerrillamail.com', 'throwaway.email', 'maildrop.cc', 'temp-mail.org',
    'fakeinbox.com', 'sharklasers.com', 'spam4.me', 'trashmail.com'
}


class AdvancedVerificationEngine:
    """
    18-Step Enterprise Email Verification Engine
    Provides confidence-based scoring with strict validation
    """

    def __init__(self):
        self.disposable_domains = DISPOSABLE_DOMAINS
        self.role_prefixes = ROLE_BASED_PREFIXES
        self.webmail_providers = WEBMAIL_PROVIDERS
        self.fake_acceptors = FAKE_ACCEPTOR_DOMAINS
        self.verification_steps = []

    async def verify(self, email: str) -> Dict[str, Any]:
        """
        Execute full 18-step verification pipeline
        """
        self.verification_steps = []
        result = {
            'email': email,
            'status': VerificationStatus.UNKNOWN,
            'confidence': 0,
            'confidence_level': ConfidenceLevel.VERY_LOW,
            'steps': [],
            'reasons': [],
            'is_valid': False,
            'is_risky': False,
            'is_disposable': False,
            'is_role_based': False,
            'is_catch_all': False,
            'smtp_accepted': False,
            'details': {}
        }

        try:
            # LINE 1: Normalize Input
            email = await self._normalize_input(email)
            result['email'] = email
            if not email:
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append('Failed normalization')
                return result

            # LINE 2: RFC Syntax Check
            if not await self._rfc_syntax_check(email):
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append('RFC syntax violation')
                return result

            # LINE 3: Length Validation
            if not await self._length_validation(email):
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append('Email length exceeds limits')
                return result

            # LINE 4: Block Obvious Fake Patterns
            if not await self._block_fake_patterns(email):
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append('Matches obvious test pattern')
                return result

            # Extract domain
            local_part, domain = email.split('@')

            # LINE 5: Domain DNS Existence
            has_dns, dns_error = await self._domain_dns_existence(domain)
            if not has_dns:
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append(f'No DNS records: {dns_error}')
                return result

            # LINE 6: MX Record Check
            mx_records, mx_error = await self._mx_record_check(domain)
            if not mx_records:
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append(f'No MX records: {mx_error}')
                return result

            result['details']['mx_count'] = len(mx_records)

            # LINE 7: MX Host Resolution
            mx_valid, mx_resolve_error = await self._mx_host_resolution(mx_records)
            if not mx_valid:
                result['status'] = VerificationStatus.INVALID
                result['reasons'].append(f'MX resolution failed: {mx_resolve_error}')
                return result

            # LINE 8: Disposable Domain Check
            if await self._disposable_domain_check(domain):
                result['status'] = VerificationStatus.DISPOSABLE
                result['is_disposable'] = True
                result['reasons'].append('Disposable email domain')
                return result

            # LINE 9: Role-Based Detection
            is_role_based = await self._role_based_detection(local_part)
            if is_role_based:
                result['is_role_based'] = True
                result['reasons'].append('Role-based address detected')

            # LINE 10-16: SMTP Verification
            smtp_result = await self._smtp_verification(email, mx_records)
            result['details']['smtp'] = smtp_result

            # LINE 17: Confidence Scoring
            confidence_score = await self._calculate_confidence(
                email, domain, local_part, mx_records, smtp_result, is_role_based
            )
            result['confidence'] = confidence_score
            result['details']['score'] = confidence_score

            # LINE 18: Final Status Guard (MOST IMPORTANT)
            final_status = await self._final_status_guard(
                email, domain, smtp_result, is_role_based, confidence_score
            )
            result['status'] = final_status['status']
            result['is_valid'] = final_status['is_valid']
            result['is_risky'] = final_status['is_risky']
            result['confidence_level'] = final_status['confidence_level']
            result['smtp_accepted'] = smtp_result.get('accepted', False)

            if smtp_result.get('catch_all'):
                result['is_catch_all'] = True
                result['reasons'].append('Domain uses catch-all')

            # If SMTP had an inconclusive result (timeout/greylist/rate-limit), add a clarifying reason
            if smtp_result.get('temp_fail') or smtp_result.get('rate_limited'):
                if not smtp_result.get('accepted'):
                    result['reasons'].append(
                        'SMTP verification inconclusive - possible server timeout or rate limiting. Email is likely valid but could not be confirmed via SMTP'
                    )

            # If SMTP was inconclusive due to timeouts/rate-limiting/network errors,
            # prefer to mark as RISKY (likely valid) rather than INVALID. Add a clear reason.
            if result['status'] == VerificationStatus.INVALID and (
                smtp_result.get('temp_fail') or smtp_result.get('rate_limited') or (
                    smtp_result.get('error') and any(k in str(smtp_result.get('error')).lower() for k in ['timeout','connection','refused','reset','unreachable'])
                )
            ):
                result['status'] = VerificationStatus.RISKY
                result['is_risky'] = True
                result['reasons'].append('SMTP verification inconclusive - possible server timeout or rate limiting. Email is likely valid but could not be confirmed via SMTP')

        except Exception as e:
            logger.error(f"Verification error for {email}: {e}")
            result['status'] = VerificationStatus.UNKNOWN
            result['reasons'].append(f'Verification error: {str(e)}')

        return result

    # ==================== 18 VERIFICATION STEPS ====================

    async def _normalize_input(self, email: str) -> str:
        """LINE 1: Normalize Input"""
        try:
            # Trim spaces
            email = email.strip()
            
            # Convert to lowercase
            email = email.lower()
            
            # Normalize Unicode → ASCII (punycode)
            try:
                # Handle internationalized domain names
                if '@' in email:
                    local, domain = email.split('@', 1)
                    domain = domain.encode('idna').decode('ascii')
                    email = f"{local}@{domain}"
            except:
                pass
            
            self.verification_steps.append(('Normalize Input', True))
            return email
        except Exception as e:
            logger.error(f"Normalization error: {e}")
            self.verification_steps.append(('Normalize Input', False, str(e)))
            return email

    async def _rfc_syntax_check(self, email: str) -> bool:
        """LINE 2: RFC Syntax Check"""
        try:
            # One @
            if email.count('@') != 1:
                self.verification_steps.append(('RFC Syntax Check', False, 'Multiple @ symbols'))
                return False

            local_part, domain = email.split('@')

            # Valid characters
            if not re.match(r'^[a-zA-Z0-9._%-]+$', local_part):
                self.verification_steps.append(('RFC Syntax Check', False, 'Invalid local part'))
                return False

            if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', domain):
                self.verification_steps.append(('RFC Syntax Check', False, 'Invalid domain'))
                return False

            # No spaces / control chars
            if ' ' in email or any(ord(c) < 32 for c in email):
                self.verification_steps.append(('RFC Syntax Check', False, 'Control characters'))
                return False

            self.verification_steps.append(('RFC Syntax Check', True))
            return True
        except Exception as e:
            self.verification_steps.append(('RFC Syntax Check', False, str(e)))
            return False

    async def _length_validation(self, email: str) -> bool:
        """LINE 3: Length Validation"""
        try:
            local_part, domain = email.split('@')

            # Local part ≤ 64 chars
            if len(local_part) > 64:
                self.verification_steps.append(('Length Validation', False, 'Local part too long'))
                return False

            # Full email ≤ 254 chars
            if len(email) > 254:
                self.verification_steps.append(('Length Validation', False, 'Email too long'))
                return False

            self.verification_steps.append(('Length Validation', True))
            return True
        except Exception as e:
            self.verification_steps.append(('Length Validation', False, str(e)))
            return False

    async def _block_fake_patterns(self, email: str) -> bool:
        """LINE 4: Block Obvious Fake Patterns"""
        try:
            for pattern in FAKE_PATTERNS:
                if re.match(pattern, email):
                    self.verification_steps.append(('Block Fake Patterns', False, f'Matches pattern: {pattern}'))
                    return False

            self.verification_steps.append(('Block Fake Patterns', True))
            return True
        except Exception as e:
            self.verification_steps.append(('Block Fake Patterns', False, str(e)))
            return False

    async def _domain_dns_existence(self, domain: str) -> Tuple[bool, str]:
        """LINE 5: Domain DNS Existence - Optimized with proper timeouts"""
        try:
            # Use dnspython for explicit record checks (A, AAAA, MX, NS, SOA)
            import dns.resolver

            resolver = dns.resolver.Resolver()
            resolver.timeout = 5  # 5s per query
            resolver.lifetime = 10  # 10s total - allows slow nameservers

            record_types = ('MX', 'A', 'AAAA', 'NS', 'SOA')
            last_error = None

            for rtype in record_types:
                try:
                    # Wrap with timeout to prevent hanging
                    answers = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, lambda: resolver.resolve(domain, rtype)
                        ),
                        timeout=9  # Hard timeout of 9s per query
                    )
                    # if we have answers, domain exists
                    if answers:
                        self.verification_steps.append(('Domain DNS Existence', True, f'{rtype} record found'))
                        return True, ""
                except dns.resolver.NoAnswer:
                    # No records of this type, try next
                    continue
                except dns.resolver.NXDOMAIN:
                    last_error = 'Domain not found (NXDOMAIN)'
                    break
                except (dns.resolver.Timeout, asyncio.TimeoutError):
                    last_error = 'DNS query timed out'
                    # Try next record type quickly
                    continue
                except Exception as e:
                    last_error = str(e)
                    continue

            # If we reach here, no useful records were found
            msg = last_error or 'No DNS records found'
            self.verification_steps.append(('Domain DNS Existence', False, msg))
            return False, msg

        except Exception as e:
            self.verification_steps.append(('Domain DNS Existence', False, str(e)))
            return False, str(e)

    async def _mx_record_check(self, domain: str) -> Tuple[List[str], str]:
        """LINE 6: MX Record Check - Optimized with proper timeouts"""
        try:
            import dns.resolver
            
            resolver = dns.resolver.Resolver()
            resolver.timeout = 5  # 5s per query
            resolver.lifetime = 10  # 10s lifetime

            try:
                # Wrap with hard timeout
                mx_records = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: resolver.resolve(domain, 'MX')
                    ),
                    timeout=9  # Hard timeout of 9s
                )
                mx_hosts = [str(mx.exchange).rstrip('.') for mx in mx_records]
                self.verification_steps.append(('MX Record Check', True, f'Found {len(mx_hosts)} MX'))
                return mx_hosts, ""
            except dns.resolver.NoAnswer:
                self.verification_steps.append(('MX Record Check', False, 'No MX records'))
                return [], "No MX records"
            except dns.resolver.NXDOMAIN:
                self.verification_steps.append(('MX Record Check', False, 'Domain not found'))
                return [], "Domain not found"
            except (dns.resolver.Timeout, asyncio.TimeoutError):
                self.verification_steps.append(('MX Record Check', False, 'MX lookup timeout'))
                return [], "MX lookup timed out"
        except Exception as e:
            self.verification_steps.append(('MX Record Check', False, str(e)))
            return [], str(e)

    async def _mx_host_resolution(self, mx_hosts: List[str]) -> Tuple[bool, str]:
        """LINE 7: MX Host Resolution - Optimized with parallel lookups and proper timeouts"""
        try:
            def resolve_single_mx(mx_host):
                """Try to resolve a single MX host"""
                try:
                    socket.gethostbyname(mx_host)
                    return True
                except:
                    return False

            loop = asyncio.get_event_loop()
            
            # Try first 5 MX hosts in parallel with reasonable timeout
            tasks = [
                asyncio.wait_for(
                    loop.run_in_executor(None, resolve_single_mx, mx_host),
                    timeout=8  # 8s per host
                )
                for mx_host in mx_hosts[:5]  # Try up to 5 hosts
            ]
            
            # Return success if any host resolves
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                if any(r is True for r in results):
                    self.verification_steps.append(('MX Host Resolution', True))
                    return True, ""
            except:
                pass
            
            # Fallback: try first host
            if mx_hosts:
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, resolve_single_mx, mx_hosts[0]),
                        timeout=8  # 8s timeout
                    )
                    if result:
                        self.verification_steps.append(('MX Host Resolution', True))
                        return True, ""
                except:
                    pass

            self.verification_steps.append(('MX Host Resolution', False, "No MX host resolved to IP"))
            return False, "No MX host resolved to IP"
        except Exception as e:
            self.verification_steps.append(('MX Host Resolution', False, str(e)))
            return False, str(e)

    async def _disposable_domain_check(self, domain: str) -> bool:
        """LINE 8: Disposable Domain Check"""
        try:
            is_disposable = domain in self.disposable_domains
            
            if is_disposable:
                self.verification_steps.append(('Disposable Domain Check', True, 'Disposable detected'))
            else:
                self.verification_steps.append(('Disposable Domain Check', True))

            return is_disposable
        except Exception as e:
            self.verification_steps.append(('Disposable Domain Check', False, str(e)))
            return False

    async def _role_based_detection(self, local_part: str) -> bool:
        """LINE 9: Role-Based Detection"""
        try:
            is_role_based = local_part.split('.')[0] in self.role_prefixes
            
            if is_role_based:
                self.verification_steps.append(('Role-Based Detection', True, f'Role detected: {local_part}'))
            else:
                self.verification_steps.append(('Role-Based Detection', True))

            return is_role_based
        except Exception as e:
            self.verification_steps.append(('Role-Based Detection', False, str(e)))
            return False

    async def _smtp_verification(self, email: str, mx_hosts: List[str]) -> Dict[str, Any]:
        """LINES 10-16: SMTP Verification with multi-step checks (fixed try/except structure)"""
        result = {
            'accepted': False,
            'rejected': False,
            'temp_fail': False,
            'catch_all': False,
            'response_code': None,
            'error': None,
            'rate_limited': False
        }

        SMTP_CONNECT_TIMEOUT = 30  # Increased to 30s for slow servers
        SMTP_RESPONSE_TIMEOUT = 30  # Increased to 30s to prevent timeouts
        MAX_RETRIES = 5  # Increased retry attempts
        INITIAL_BACKOFF = 1.0
        BACKOFF_MULTIPLIER = 2.0

        for mx_host in mx_hosts[:3]:
            backoff = INITIAL_BACKOFF
            for attempt in range(MAX_RETRIES):
                reader = writer = None
                # Attempt to open TCP connection
                try:
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(mx_host, 25),
                            timeout=SMTP_CONNECT_TIMEOUT
                        )
                        self.verification_steps.append(('SMTP TCP Connection', True, f'{mx_host} (attempt {attempt+1})'))
                    except asyncio.TimeoutError:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(backoff)
                            backoff *= BACKOFF_MULTIPLIER
                            continue
                        self.verification_steps.append(('SMTP TCP Connection', False, f'Timeout {mx_host}'))
                        result['error'] = 'SMTP connection timeout'
                        result['temp_fail'] = True
                        break
                    except ConnectionRefusedError:
                        self.verification_steps.append(('SMTP Connection', False, f'Refused {mx_host}'))
                        result['error'] = 'Connection refused'
                        # Treat connection refused as a temporary/network failure so it can be
                        # handled as 'risky' instead of outright invalid when MX exists
                        result['temp_fail'] = True
                        break
                    except Exception as e:
                        self.verification_steps.append(('SMTP Connection', False, str(e)))
                        result['error'] = str(e)
                        continue

                    # Perform SMTP handshake and RCPT check
                    try:
                        greeting = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=SMTP_RESPONSE_TIMEOUT)
                        writer.write(b'HELO verify.example.com\r\n')
                        await writer.drain()

                        helo_resp = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=SMTP_RESPONSE_TIMEOUT)

                        writer.write(b'MAIL FROM:<test@verify.example.com>\r\n')
                        await writer.drain()

                        mail_resp = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=SMTP_RESPONSE_TIMEOUT)

                        self.verification_steps.append(('SMTP Handshake', True))

                        # RCPT TO
                        writer.write(f'RCPT TO:<{email}>\r\n'.encode())
                        await writer.drain()
                        rcpt_resp = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=SMTP_RESPONSE_TIMEOUT)
                        rcpt_text = rcpt_resp.decode('utf-8', errors='ignore').strip()
                        self.verification_steps.append(('RCPT TO Check', True))

                        try:
                            response_code = int(rcpt_text.split()[0])
                            result['response_code'] = response_code
                        except:
                            response_code = 550

                        response_lower = rcpt_text.lower()
                        # Detect rate-limiting / greylist style responses
                        if any(keyword in response_lower for keyword in ['rate', 'too many', 'temporarily deferred', 'deferred', 'try again later']):
                            result['temp_fail'] = True
                            result['rate_limited'] = True
                            self.verification_steps.append(('SMTP Message Parsing', True, f'Rate-limited/greylist: {rcpt_text}'))
                        elif any(pattern in response_lower for pattern in [
                            'does not exist', 'user unknown', 'no such user',
                            'invalid recipient', 'recipient unknown'
                        ]):
                            result['rejected'] = True
                            self.verification_steps.append(('SMTP Message Parsing', True, 'User rejected'))
                        elif 200 <= response_code < 300:
                            result['accepted'] = True
                            self.verification_steps.append(('SMTP Code Classification', True, f'Code {response_code}'))
                        elif 400 <= response_code < 500:
                            result['temp_fail'] = True
                            self.verification_steps.append(('SMTP Code Classification', True, f'Temporary fail {response_code}'))
                        elif 500 <= response_code < 600:
                            result['rejected'] = True
                            self.verification_steps.append(('SMTP Code Classification', True, f'Rejected {response_code}'))

                        # Catch-all detection
                        if result['accepted']:
                            random_email = f"test_random_{datetime.now().timestamp()}@{email.split('@')[1]}"
                            writer.write(f'RCPT TO:<{random_email}>\r\n'.encode())
                            await writer.drain()
                            try:
                                random_resp = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=5)
                                random_code = int(random_resp.decode('utf-8', errors='ignore').split()[0])
                                if 200 <= random_code < 300:
                                    result['catch_all'] = True
                                    self.verification_steps.append(('Catch-All Detection', True, 'Catch-all detected'))
                            except Exception:
                                # if random check fails or times out, ignore
                                pass

                        # QUIT politely
                        try:
                            writer.write(b'QUIT\r\n')
                            await writer.drain()
                        except:
                            pass

                    except asyncio.TimeoutError:
                        # Retry on response timeout with backoff when possible
                        self.verification_steps.append(('SMTP Verification', False, f'Timeout {mx_host} (attempt {attempt+1})'))
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(backoff)
                            backoff *= BACKOFF_MULTIPLIER
                            # continue to next attempt
                            continue
                        # final attempt failed
                        result['error'] = 'SMTP timeout - server not responding'
                        result['temp_fail'] = True
                    except Exception as e:
                        logger.error(f"SMTP error with {mx_host}: {e}")
                        self.verification_steps.append(('SMTP Verification', False, f'Error: {str(e)[:50]}'))
                        result['error'] = str(e)
                    finally:
                        try:
                            if writer:
                                writer.close()
                                await writer.wait_closed()
                        except:
                            pass

                finally:
                    # do not break inside a finally block; set a flag instead
                    # so we can break after the finally completes
                    stop_attempts = False
                    if result['accepted'] or result['rejected'] or result.get('error'):
                        stop_attempts = True

                # break inner attempt loop if a definitive result was recorded
                try:
                    if stop_attempts:
                        break
                except UnboundLocalError:
                    # If stop_attempts wasn't set (unexpected), continue normally
                    pass

            # break outer MX loop if definitive
            if result['accepted'] or result['rejected'] or result.get('error'):
                break

        # Mail Server Behavior Check (Fake Acceptor Detection)
        domain = email.split('@')[1]
        if domain in self.fake_acceptors and result['accepted']:
            self.verification_steps.append(('Mail Server Behavior', True, 'Fake acceptor detected'))
            result['fake_acceptor'] = True

        return result

    async def _calculate_confidence(
        self,
        email: str,
        domain: str,
        local_part: str,
        mx_records: List[str],
        smtp_result: Dict[str, Any],
        is_role_based: bool
    ) -> int:
        """LINE 17: Confidence Scoring"""
        score = 0

        # Syntax valid: +10
        score += 10
        
        # DNS valid: +10
        score += 10
        
        # MX valid: +20
        score += 20
        
        # SMTP accepted: +25
        if smtp_result.get('accepted'):
            score += 25
        elif smtp_result.get('rate_limited'):
            # Rate-limited servers likely valid but unconfirmed
            score += 10
            # add a reason for clarity
        elif smtp_result.get('temp_fail'):
            score += 5
        elif smtp_result.get('rejected'):
            score = 20  # Reduced score for rejected
        else:
            score -= 10
        
        # Not catch-all: +15
        if not smtp_result.get('catch_all'):
            score += 15
        else:
            score -= 10
        
        # Not role-based: +10
        if not is_role_based:
            score += 10
        else:
            score -= 5
        
        # No greylist: +10 (penalize if temp_fail or rate_limited)
        if not smtp_result.get('temp_fail') and not smtp_result.get('rate_limited'):
            score += 10
        
        # Not fake acceptor: bonus
        if not smtp_result.get('fake_acceptor'):
            score += 5

        # Clamp between 0-100
        score = max(0, min(100, score))

        self.verification_steps.append(('Confidence Scoring', True, f'Score: {score}'))
        return score

    async def _final_status_guard(
        self,
        email: str,
        domain: str,
        smtp_result: Dict[str, Any],
        is_role_based: bool,
        confidence_score: int
    ) -> Dict[str, Any]:
        """LINE 18: Final Status Guard (MOST IMPORTANT)"""
        
        result = {
            'status': VerificationStatus.UNKNOWN,
            'is_valid': False,
            'is_risky': False,
            'confidence_level': ConfidenceLevel.VERY_LOW
        }

        # STRICT RULE FOR GREEN (VALID)
        # Only show GREEN if ALL below are true
        is_valid_candidate = (
            smtp_result.get('accepted') and
            not smtp_result.get('catch_all') and
            not is_role_based and
            not smtp_result.get('temp_fail') and
            not smtp_result.get('fake_acceptor') and
            confidence_score >= 85
        )

        if is_valid_candidate:
            result['status'] = VerificationStatus.VALID
            result['is_valid'] = True
            result['confidence_level'] = ConfidenceLevel.VERY_HIGH
            self.verification_steps.append(('Final Status Guard', True, 'VALID (Strict criteria met)'))
        elif confidence_score >= 60 and (smtp_result.get('accepted') or smtp_result.get('temp_fail')):
            result['status'] = VerificationStatus.RISKY
            result['is_risky'] = True
            
            if confidence_score >= 80:
                result['confidence_level'] = ConfidenceLevel.HIGH
            elif confidence_score >= 70:
                result['confidence_level'] = ConfidenceLevel.MEDIUM
            else:
                result['confidence_level'] = ConfidenceLevel.LOW
            
            self.verification_steps.append(('Final Status Guard', True, f'RISKY (Score {confidence_score})'))
        else:
            result['status'] = VerificationStatus.INVALID
            result['confidence_level'] = ConfidenceLevel.VERY_LOW
            self.verification_steps.append(('Final Status Guard', True, 'INVALID'))

        return result
