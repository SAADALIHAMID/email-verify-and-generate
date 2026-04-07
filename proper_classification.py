"""
Proper Email Classification - Strict VALID/INVALID validation
Only emails that are actually deliverable show as VALID
"""

from app.models import VerificationStatus, ReasonCode
from app.schemas import VerificationResult
from typing import Dict, Any
import re

def classify_verification_result_proper(signals: Dict[str, Any]) -> VerificationResult:
    """
    Proper 2-tier classification with strict validation
    Only truly deliverable emails show as VALID
    """
    
    email = signals.get('email', '')
    
    # Initialize result as INVALID by default
    result = VerificationResult(
        email=email,
        status=VerificationStatus.INVALID,
        reason_code=ReasonCode.NETWORK_ERROR,
        reasons=[],
        mx_records=signals.get('mx_records', []),
        has_mx=signals.get('has_mx', False),
        smtp_transcript=signals.get('smtp_transcript', []),
        smtp_accepted=signals.get('smtp_accepted', False),
        is_catch_all=signals.get('is_catch_all', False),
        is_role_based=signals.get('is_role_based', False),
        is_disposable=signals.get('is_disposable', False),
        verification_duration_ms=signals.get('verification_duration_ms', 0)
    )
    
    # 1. INVALID: Basic syntax validation
    if not _is_valid_email_syntax(email):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.SYNTAX_ERROR
        result.reasons = ["Invalid email syntax"]
        return result
    
    # 2. INVALID: Explicit syntax check from signals
    if not signals.get('valid_syntax', True):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.SYNTAX_ERROR
        result.reasons = ["Invalid email format"]
        return result
    
    # 3. INVALID: Disposable domains
    if signals.get('is_disposable', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.DISPOSABLE_DOMAIN
        result.reasons = ["Disposable email domain not allowed"]
        return result
    
    # 4. INVALID: No MX records (domain doesn't exist)
    if not signals.get('has_mx', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.NO_MX_RECORD
        result.reasons = ["Domain has no mail servers (MX records)"]
        return result
    
    # 5. INVALID: SMTP explicitly rejected the email
    if signals.get('smtp_checked', False) and not signals.get('smtp_accepted', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.SMTP_USER_UNKNOWN
        result.reasons = ["Email address rejected by mail server"]
        return result
    
    # 6. VALID: SMTP explicitly accepted the email
    if signals.get('smtp_accepted', False):
        result.status = VerificationStatus.DELIVERABLE
        result.reason_code = ReasonCode.SMTP_ACCEPTED
        
        reasons = ["Email verified as deliverable"]
        
        # Add informational notes but keep as VALID
        if signals.get('is_role_based', False):
            reasons.append("Role-based address (info, admin, contact, etc.)")
        
        if signals.get('is_catch_all', False):
            reasons.append("Domain accepts all emails (catch-all)")
        
        result.reasons = reasons
        return result
    
    # 7. INVALID: Has MX but no SMTP verification (can't confirm deliverability)
    if signals.get('has_mx', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.NETWORK_ERROR
        result.reasons = ["Cannot verify email deliverability - mail server unreachable"]
        return result
    
    # 8. Default: INVALID
    result.status = VerificationStatus.INVALID
    result.reason_code = ReasonCode.NETWORK_ERROR
    result.reasons = ["Email verification failed"]
    
    return result


def _is_valid_email_syntax(email: str) -> bool:
    """Strict email syntax validation"""
    if not email or not isinstance(email, str):
        return False
    
    # Must have exactly one @ symbol
    if email.count('@') != 1:
        return False
    
    # Split into local and domain parts
    try:
        local, domain = email.split('@')
    except ValueError:
        return False
    
    # Local part checks
    if not local or len(local) > 64:
        return False
    
    # Domain part checks
    if not domain or len(domain) > 255:
        return False
    
    # Domain must have at least one dot
    if '.' not in domain:
        return False
    
    # Basic regex validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False
    
    return True


def get_proper_status_display(status: str) -> tuple:
    """Convert status to proper VALID/INVALID display"""
    
    # Only DELIVERABLE is VALID
    if status == "DELIVERABLE":
        return ("✅", "VALID", "success")
    
    # Everything else is INVALID
    else:
        return ("❌", "INVALID", "error")
