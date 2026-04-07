"""
Simple 2-tier classification: VALID or INVALID only
This version converts RISKY statuses to either VALID or INVALID
"""

from app.models import VerificationStatus, ReasonCode
from app.schemas import VerificationResult
from typing import Dict, Any

def classify_verification_result_simple(signals: Dict[str, Any]) -> VerificationResult:
    """
    Simple 2-tier classification: VALID or INVALID only
    Converts risky statuses based on SMTP acceptance
    """
    
    email = signals.get('email', '')
    
    # Initialize result
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
    
    # 1. INVALID: Syntax errors
    if not signals.get('valid_syntax', True):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.SYNTAX_ERROR
        result.reasons = ["Invalid email syntax"]
        return result
    
    # 2. INVALID: Disposable domains
    if signals.get('is_disposable', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.DISPOSABLE_DOMAIN
        result.reasons = ["Disposable email domain"]
        return result
    
    # 3. INVALID: No MX records
    if not signals.get('has_mx', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.NO_MX_RECORD
        result.reasons = ["Domain has no MX records"]
        return result
    
    # 4. INVALID: SMTP rejected
    if signals.get('smtp_checked', False) and not signals.get('smtp_accepted', False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.SMTP_USER_UNKNOWN
        result.reasons = ["SMTP server rejected email address"]
        return result
    
    # 5. VALID: SMTP accepted (regardless of role-based or catch-all)
    if signals.get('smtp_accepted', False):
        result.status = VerificationStatus.DELIVERABLE
        result.reason_code = ReasonCode.SMTP_ACCEPTED
        
        reasons = ["Email address accepted by SMTP server"]
        
        # Add informational notes but keep as VALID
        if signals.get('is_role_based', False):
            reasons.append("Note: Role-based address (info, admin, etc.)")
        
        if signals.get('is_catch_all', False):
            reasons.append("Note: Domain accepts all emails (catch-all)")
        
        result.reasons = reasons
        return result
    
    # 6. VALID: Has MX and no obvious issues
    if signals.get('has_mx', False):
        result.status = VerificationStatus.DELIVERABLE
        result.reason_code = ReasonCode.SMTP_ACCEPTED
        result.reasons = ["Domain has valid MX records"]
        
        # Add notes if applicable
        if signals.get('is_role_based', False):
            result.reasons.append("Note: Role-based address")
        
        return result
    
    # 7. Default: INVALID
    result.status = VerificationStatus.INVALID
    result.reason_code = ReasonCode.NETWORK_ERROR
    result.reasons = ["Unable to verify email address"]
    
    return result


def get_simple_status_display(status: str) -> tuple:
    """Convert any status to simple VALID/INVALID display"""
    
    # Convert RISKY and DELIVERABLE to VALID
    if status in ["DELIVERABLE", "RISKY_ROLE_BASED", "RISKY_CATCH_ALL"]:
        return ("✅", "VALID", "success")
    
    # Everything else is INVALID
    else:
        return ("❌", "INVALID", "error")
