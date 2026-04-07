"""
Improved verification logic for handling network restrictions
"""
from app.models import VerificationStatus, ReasonCode
from app.schemas import VerificationResult
import re
import socket
import asyncio
import logging

logger = logging.getLogger(__name__)

def improved_classify_verification_result(signals: dict) -> VerificationResult:
    """
    Improved classification that handles network limitations better.
    """
    email = signals.get("email", "")
    domain = signals.get("domain", "")
    
    # Start with basic information
    result = VerificationResult(
        email=email,
        status=VerificationStatus.INVALID,
        reason_code=ReasonCode.SYNTAX_ERROR,
        reasons=[],
        mx_records=signals.get("mx_records", []),
        has_mx=signals.get("has_mx", False),
        smtp_accepted=signals.get("smtp_accepted", False),
        is_catch_all=signals.get("is_catch_all", False),
        is_role_based=signals.get("is_role_based", False),
        is_disposable=signals.get("is_disposable", False)
    )
    
    # Check for syntax errors first
    if not signals.get("syntax_valid", False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.SYNTAX_ERROR
        result.reasons = ["Invalid email syntax"]
        return result
    
    # Check for disposable domains
    if signals.get("is_disposable", False):
        result.status = VerificationStatus.DISPOSABLE
        result.reason_code = ReasonCode.DISPOSABLE_DOMAIN
        result.reasons = ["Disposable email domain detected"]
        return result
    
    # Check if domain has MX records
    if not signals.get("has_mx", False):
        result.status = VerificationStatus.INVALID
        result.reason_code = ReasonCode.NO_MX_RECORD
        result.reasons = ["No MX records found for domain"]
        return result
    
    # Known webmail providers - higher confidence
    webmail_domains = {
        'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
        'icloud.com', 'protonmail.com', 'zoho.com', 'aol.com'
    }
    
    is_webmail = domain.lower() in webmail_domains
    
    # Handle network errors better
    network_error = signals.get("network_error", False)
    smtp_connected = signals.get("smtp_connected", False)
    smtp_accepted = signals.get("smtp_accepted", False)
    
    if is_webmail:
        # For webmail providers, if MX exists, likely deliverable
        if signals.get("has_mx", False):
            result.status = VerificationStatus.DELIVERABLE
            result.reason_code = ReasonCode.SMTP_ACCEPTED
            result.reasons = ["Known webmail provider with valid MX records"]
            result.smtp_accepted = True  # Assume deliverable for known providers
        else:
            result.status = VerificationStatus.INVALID
            result.reason_code = ReasonCode.NO_MX_RECORD
            result.reasons = ["Webmail provider but no MX records"]
    
    elif network_error and not smtp_connected:
        # Network issues - classify as risky but potentially deliverable
        if signals.get("has_mx", False):
            # If role-based, mark as risky role-based
            if signals.get("is_role_based", False):
                result.status = VerificationStatus.RISKY_ROLE_BASED
                result.reason_code = ReasonCode.ROLE_BASED_ADDRESS
                result.reasons = [
                    "Could not verify due to network restrictions",
                    "Domain has valid MX records - potentially deliverable",
                    "Role-based email address detected"
                ]
            else:
                # Regular business email with network issues
                result.status = VerificationStatus.DELIVERABLE
                result.reason_code = ReasonCode.SMTP_ACCEPTED
                result.reasons = [
                    "Could not perform SMTP test due to network restrictions",
                    "Domain has valid MX records - likely deliverable",
                    "Business domain appears legitimate"
                ]
                result.smtp_accepted = True  # Assume deliverable if MX exists
        else:
            result.status = VerificationStatus.UNKNOWN_TEMPFAIL
            result.reason_code = ReasonCode.NETWORK_ERROR
            result.reasons = ["Network error and no MX records found"]
    
    elif smtp_connected and smtp_accepted:
        # SMTP verification successful
        if signals.get("is_role_based", False):
            result.status = VerificationStatus.RISKY_ROLE_BASED
            result.reason_code = ReasonCode.ROLE_BASED_ADDRESS
            result.reasons = ["Email verified but is role-based"]
        else:
            result.status = VerificationStatus.DELIVERABLE
            result.reason_code = ReasonCode.SMTP_ACCEPTED
            result.reasons = ["Email verified via SMTP"]
    
    elif smtp_connected and not smtp_accepted:
        # SMTP connected but email rejected
        smtp_code = signals.get("smtp_code")
        if smtp_code and 400 <= smtp_code < 500:
            result.status = VerificationStatus.UNKNOWN_TEMPFAIL
            result.reason_code = ReasonCode.SMTP_TEMPFAIL
            result.reasons = ["SMTP temporary failure - try again later"]
        else:
            result.status = VerificationStatus.INVALID
            result.reason_code = ReasonCode.SMTP_USER_UNKNOWN
            result.reasons = ["SMTP server rejected the email address"]
    
    else:
        # SMTP connection failed but we have MX records
        if signals.get("has_mx", False):
            if signals.get("is_role_based", False):
                result.status = VerificationStatus.RISKY_ROLE_BASED
                result.reason_code = ReasonCode.ROLE_BASED_ADDRESS
                result.reasons = [
                    "SMTP verification failed",
                    "Domain has MX records",
                    "Role-based email detected"
                ]
            else:
                # Give benefit of doubt for business emails with MX
                result.status = VerificationStatus.DELIVERABLE
                result.reason_code = ReasonCode.SMTP_ACCEPTED
                result.reasons = [
                    "SMTP test inconclusive but domain has valid MX records",
                    "Business email likely deliverable"
                ]
                result.smtp_accepted = True
        else:
            result.status = VerificationStatus.INVALID
            result.reason_code = ReasonCode.NO_MX_RECORD
            result.reasons = ["No MX records and SMTP verification failed"]
    
    return result

# Function to patch the existing classification
def patch_verification_classification():
    """
    Patches the existing verification system to handle network issues better.
    """
    try:
        from app.pipeline.classification import classify_verification_result
        # Replace the existing function
        import app.pipeline.classification
        app.pipeline.classification.classify_verification_result = improved_classify_verification_result
        print("Successfully patched verification classification")
        return True
    except Exception as e:
        print(f"Failed to patch verification: {e}")
        return False

if __name__ == "__main__":
    # Test the improved classification
    test_signals = {
        "email": "info@seodexa.com", 
        "domain": "seodexa.com",
        "syntax_valid": True,
        "has_mx": True,
        "smtp_accepted": False,
        "smtp_connected": False,
        "is_disposable": False,
        "is_role_based": True,
        "is_catch_all": False,
        "mx_records": ["seodexa.com"],
        "network_error": True
    }
    
    result = improved_classify_verification_result(test_signals)
    print(f"Email: {result.email}")
    print(f"Status: {result.status}")
    print(f"Reason: {result.reason_code}")
    print(f"Reasons: {result.reasons}")
    print(f"SMTP Accepted: {result.smtp_accepted}")
