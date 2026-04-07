"""Email syntax validation using email-validator and strict fallback regex."""

import re
import logging
from typing import Tuple, Optional
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)

# Strict RFC-compliant email regex as fallback
RFC_EMAIL_REGEX = re.compile(
    r'^[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+)*'
    r'@(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$'
)


def validate_email_syntax(email: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate email syntax using email-validator with regex fallback.
    
    Args:
        email: Email address to validate
        
    Returns:
        Tuple of (is_valid, normalized_email, error_message)
    """
    if not email or not isinstance(email, str):
        return False, None, "Email is empty or not a string"
    
    # Basic length check
    if len(email) > 320:  # RFC 5321 limit
        return False, None, "Email address too long (max 320 characters)"
    
    # Check for basic structure
    if '@' not in email:
        return False, None, "Missing @ symbol"
    
    parts = email.split('@')
    if len(parts) != 2:
        return False, None, "Multiple @ symbols found"
    
    localpart, domain = parts
    
    # Check localpart length (RFC 5321)
    if len(localpart) > 64:
        return False, None, "Local part too long (max 64 characters)"
    
    # Check domain length
    if len(domain) > 253:
        return False, None, "Domain too long (max 253 characters)"
    
    if not localpart or not domain:
        return False, None, "Empty local part or domain"
    
    try:
        # Use email-validator for comprehensive validation
        validated = validate_email(
            email,
            check_deliverability=False,  # We'll do our own deliverability check
            test_environment=False
        )
        
        # Return normalized email (lowercased domain, etc.)
        normalized = validated.email
        logger.debug(f"Email syntax valid: {email} -> {normalized}")
        return True, normalized, None
        
    except EmailNotValidError as e:
        # Fallback to regex validation for edge cases
        logger.debug(f"email-validator failed for {email}: {e}")
        
        # Try strict regex as fallback
        if RFC_EMAIL_REGEX.match(email):
            # Manual normalization: lowercase domain
            localpart, domain = email.split('@', 1)
            normalized = f"{localpart}@{domain.lower()}"
            logger.debug(f"Regex fallback valid: {email} -> {normalized}")
            return True, normalized, None
        
        return False, None, str(e)
    
    except Exception as e:
        logger.error(f"Unexpected error validating {email}: {e}")
        return False, None, f"Validation error: {str(e)}"


def extract_domain(email: str) -> Optional[str]:
    """
    Extract domain from email address.
    
    Args:
        email: Email address
        
    Returns:
        Domain part or None if invalid
    """
    if not email or '@' not in email:
        return None
    
    parts = email.split('@')
    if len(parts) != 2:
        return None
    
    domain = parts[1].lower().strip()
    return domain if domain else None


def normalize_email(email: str) -> str:
    """
    Normalize email address (lowercase domain, strip whitespace).
    
    Args:
        email: Email address to normalize
        
    Returns:
        Normalized email address
    """
    if not email:
        return email
    
    email = email.strip()
    
    if '@' not in email:
        return email
    
    parts = email.split('@', 1)
    if len(parts) != 2:
        return email
    
    localpart, domain = parts
    return f"{localpart}@{domain.lower()}"


def is_internationalized_domain(domain: str) -> bool:
    """
    Check if domain contains internationalized characters.
    
    Args:
        domain: Domain name to check
        
    Returns:
        True if domain has non-ASCII characters
    """
    try:
        domain.encode('ascii')
        return False
    except UnicodeEncodeError:
        return True


def validate_localpart(localpart: str) -> Tuple[bool, Optional[str]]:
    """
    Validate email local part (before @).
    
    Args:
        localpart: Local part of email address
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not localpart:
        return False, "Empty local part"
    
    if len(localpart) > 64:
        return False, "Local part too long"
    
    # Check for consecutive dots
    if '..' in localpart:
        return False, "Consecutive dots not allowed"
    
    # Check for leading/trailing dots
    if localpart.startswith('.') or localpart.endswith('.'):
        return False, "Local part cannot start or end with dot"
    
    # Check for valid characters (simplified)
    valid_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&\'*+-/=?^_`{|}~.')
    if not all(c in valid_chars for c in localpart):
        return False, "Invalid characters in local part"
    
    return True, None


def validate_domain_syntax(domain: str) -> Tuple[bool, Optional[str]]:
    """
    Validate domain syntax.
    
    Args:
        domain: Domain name to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not domain:
        return False, "Empty domain"
    
    if len(domain) > 253:
        return False, "Domain too long"
    
    # Check for valid domain format
    if domain.startswith('.') or domain.endswith('.'):
        return False, "Domain cannot start or end with dot"
    
    if '..' in domain:
        return False, "Consecutive dots not allowed in domain"
    
    # Split into labels
    labels = domain.split('.')
    if len(labels) < 2:
        return False, "Domain must have at least two labels"
    
    for label in labels:
        if not label:
            return False, "Empty label in domain"
        
        if len(label) > 63:
            return False, "Domain label too long"
        
        # Labels must start and end with alphanumeric
        if not (label[0].isalnum() and label[-1].isalnum()):
            return False, "Domain label must start and end with alphanumeric character"
        
        # Check for valid characters
        if not all(c.isalnum() or c == '-' for c in label):
            return False, "Invalid characters in domain label"
    
    return True, None