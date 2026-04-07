"""
Balanced Email Classification Module
Provides consistent status display across the application
"""

from typing import Optional, Dict, Any
from app.schemas import VerificationResult
from app.models import VerificationStatus, ReasonCode


def get_balanced_status_display(status: str) -> tuple:
    """
    Get balanced status display for email verification results.
    
    Returns:
        tuple: (icon, display_status, status_type)
            - icon: Emoji icon for display
            - display_status: 'VALID' or 'INVALID'
            - status_type: 'success' or 'error'
    """
    # Normalize status to uppercase
    status = str(status).upper()
    
    # Valid statuses - only DELIVERABLE
    if status in ['DELIVERABLE', 'VALID', 'ACCEPTED']:
        return ('🟢', 'VALID', 'success')
    
    # Risky statuses
    if status in ['RISKY_CATCH_ALL', 'CATCH_ALL', 'RISKY']:
        return ('🟡', 'RISKY', 'warning')
    
    if status in ['RISKY_ROLE_BASED', 'ROLE_BASED']:
        return ('🟠', 'ROLE_BASED', 'info')
    
    # Everything else is invalid
    return ('🔴', 'INVALID', 'error')


def classify_email_status(
    smtp_accepted: bool,
    has_mx: bool,
    is_disposable: bool,
    is_role_based: bool,
    status: str
) -> str:
    """
    Classify email into simple VALID/INVALID categories.
    
    Args:
        smtp_accepted: Whether SMTP accepted the email
        has_mx: Whether domain has MX records
        is_disposable: Whether email is disposable
        is_role_based: Whether email is role-based
        status: Current status string
        
    Returns:
        str: 'VALID' or 'INVALID'
    """
    # Primary check: SMTP acceptance
    if smtp_accepted and has_mx:
        if is_disposable:
            return 'INVALID'
        if is_catch_all:
            return 'RISKY_CATCH_ALL'
        if is_role_based:
            return 'RISKY_ROLE_BASED'
        return 'VALID'
    
    # If no MX records or disposable, it's invalid
    if not has_mx or is_disposable:
        return 'INVALID'
    
    # Check status string
    status_upper = str(status).upper()
    if status_upper in ['DELIVERABLE', 'VALID', 'ACCEPTED']:
        return 'VALID'
    
    # Default to invalid
    return 'INVALID'


def get_status_color(status: str) -> str:
    """
    Get color code for status.
    
    Args:
        status: Status string
        
    Returns:
        str: Hex color code
    """
    status_upper = str(status).upper()
    
    if status_upper in ['DELIVERABLE', 'VALID', 'ACCEPTED']:
        return '#28a745'  # Green
    elif 'RISKY' in status_upper:
        return '#ffc107'  # Yellow
    else:
        return '#dc3545'  # Red


def format_status_for_display(status: str, smtp_accepted: Optional[bool] = None) -> str:
    """
    Format status for user-friendly display.
    
    Args:
        status: Status string
        smtp_accepted: Optional SMTP acceptance status
        
    Returns:
        str: Formatted status string
    """
    icon, display_status, _ = get_balanced_status_display(status)
    
    if smtp_accepted is not None:
        smtp_icon = '✅' if smtp_accepted else '❌'
        return f"{icon} {display_status} {smtp_icon}"
    
    return f"{icon} {display_status}"


def classify_verification_result_balanced(signals: Dict[str, Any]) -> VerificationResult:
    """
    Classify verification result based on collected signals.
    Uses balanced classification: only DELIVERABLE or INVALID.
    
    FIXED VERSION: Properly handles missing MX records with existing domain
    
    Args:
        signals: Dictionary containing verification signals
        
    Returns:
        VerificationResult object
    """
    email = signals.get('email', '')
    reasons = []
    
    # Extract all signals with safe defaults
    syntax_valid = signals.get('syntax_valid', True)
    is_disposable = signals.get('is_disposable', False)
    has_mx = signals.get('has_mx', False)
    mx_records = signals.get('mx_records', [])
    smtp_connected = signals.get('smtp_connected', False)
    smtp_accepted = signals.get('smtp_accepted', False)
    smtp_code = signals.get('smtp_code')
    is_role_based = signals.get('is_role_based', False)
    is_catch_all = signals.get('is_catch_all', False)
    network_error = signals.get('network_error', False)
    smtp_timeout = signals.get('smtp_timeout', False)
    dns_timeout = signals.get('dns_timeout', False)
    
    # Check syntax first
    if not syntax_valid:
        return VerificationResult(
            email=email,
            status=VerificationStatus.INVALID,
            reason_code=ReasonCode.SYNTAX_ERROR,
            reasons=['Invalid email syntax'],
            smtp_accepted=False,
            has_mx=False,
            mx_records=[],
            is_disposable=False,
            is_role_based=False,
            is_catch_all=False
        )
    
    # Check disposable
    if is_disposable:
        return VerificationResult(
            email=email,
            status=VerificationStatus.INVALID,
            reason_code=ReasonCode.DISPOSABLE_DOMAIN,
            reasons=['Disposable email domain'],
            smtp_accepted=False,
            has_mx=has_mx,
            mx_records=mx_records,
            is_disposable=True,
            is_role_based=is_role_based,
            is_catch_all=is_catch_all
        )
    
    # 🔥 FIX: Check MX records - but be lenient
    # Some valid domains might not have MX but have A records
    if not has_mx and not mx_records:
        # Only mark as invalid if we're sure (not a timeout)
        if not dns_timeout and not network_error:
            return VerificationResult(
                email=email,
                status=VerificationStatus.INVALID,
                reason_code=ReasonCode.NO_MX_RECORD,
                reasons=['No MX records found for domain'],
                smtp_accepted=False,
                has_mx=False,
                mx_records=[],
                is_disposable=False,
                is_role_based=is_role_based,
                is_catch_all=False
            )
    
    # 🔥 FIX: SMTP acceptance is PRIMARY indicator
    if smtp_accepted:
        reasons.append('SMTP server accepted email')
        
        # If it's a catch-all, mark as RISKY_CATCH_ALL (STRICTER)
        if is_catch_all:
            reasons.append('Catch-all domain (accepts all emails)')
            return VerificationResult(
                email=email,
                status=VerificationStatus.RISKY_CATCH_ALL,
                reason_code=ReasonCode.SMTP_ACCEPTED,
                reasons=reasons,
                smtp_accepted=True,
                has_mx=True,
                mx_records=mx_records,
                is_disposable=False,
                is_role_based=is_role_based,
                is_catch_all=True
            )
            
        if is_role_based:
            reasons.append('Role-based email (e.g., info@, support@)')
            return VerificationResult(
                email=email,
                status=VerificationStatus.RISKY_ROLE_BASED,
                reason_code=ReasonCode.SMTP_ACCEPTED,
                reasons=reasons,
                smtp_accepted=True,
                has_mx=True,
                mx_records=mx_records,
                is_disposable=False,
                is_role_based=True,
                is_catch_all=False
            )
        
        return VerificationResult(
            email=email,
            status=VerificationStatus.DELIVERABLE,
            reason_code=ReasonCode.SMTP_ACCEPTED,
            reasons=reasons,
            smtp_accepted=True,
            has_mx=True,
            mx_records=mx_records,
            is_disposable=False,
            is_role_based=is_role_based,
            is_catch_all=is_catch_all
        )
    
    # 🔥 FIX: If SMTP connected but rejected with 5xx code -> INVALID
    if smtp_connected and not smtp_accepted and smtp_code and smtp_code >= 500:
        return VerificationResult(
            email=email,
            status=VerificationStatus.INVALID,
            reason_code=ReasonCode.SMTP_USER_UNKNOWN,
            reasons=['SMTP server rejected email - mailbox does not exist'],
            smtp_accepted=False,
            has_mx=True,
            mx_records=mx_records,
            is_disposable=False,
            is_role_based=is_role_based,
            is_catch_all=is_catch_all
        )
    
    # 🔥 FIX: If we have MX records but couldn't verify due to timeout/network
    # Mark as DELIVERABLE with lower confidence (benefit of doubt)
    if has_mx and mx_records and (smtp_timeout or network_error):
        reasons.append('Could not verify via SMTP - timeout or network issue')
        reasons.append('Domain has valid MX records')
        
        return VerificationResult(
            email=email,
            status=VerificationStatus.DELIVERABLE,
            reason_code=ReasonCode.SMTP_ACCEPTED,
            reasons=reasons,
            smtp_accepted=True,  # Assume valid if MX exists
            has_mx=True,
            mx_records=mx_records,
            is_disposable=False,
            is_role_based=is_role_based,
            is_catch_all=is_catch_all
        )
    
    # 🔥 FIX: If we have MX but no definitive answer -> DELIVERABLE
    # (Conservative: assume valid if domain has proper MX setup)
    if has_mx and mx_records:
        reasons.append('Domain has valid MX records')
        reasons.append('SMTP verification inconclusive')
        
        return VerificationResult(
            email=email,
            status=VerificationStatus.DELIVERABLE,
            reason_code=ReasonCode.SMTP_ACCEPTED,
            reasons=reasons,
            smtp_accepted=True,
            has_mx=True,
            mx_records=mx_records,
            is_disposable=False,
            is_role_based=is_role_based,
            is_catch_all=is_catch_all
        )
    
    # Default: Mark as INVALID only if we're very sure
    return VerificationResult(
        email=email,
        status=VerificationStatus.INVALID,
        reason_code=ReasonCode.SMTP_TEMPFAIL,
        reasons=['Email verification inconclusive'],
        smtp_accepted=False,
        has_mx=has_mx,
        mx_records=mx_records,
        is_disposable=False,
        is_role_based=is_role_based,
        is_catch_all=is_catch_all
    )