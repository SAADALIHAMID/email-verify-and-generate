"""
Balanced Email Classification Module
Provides consistent status display across the application
"""

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
    valid_statuses = [
        'DELIVERABLE',
        'VALID',
        'ACCEPTED'
    ]
    
    # Check if valid
    if status in valid_statuses:
        return ('🟢', 'VALID', 'success')
    
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
        # Even if role-based or catch-all, if SMTP accepts it's valid
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
    else:
        return '#dc3545'  # Red


def format_status_for_display(status: str, smtp_accepted: bool = None) -> str:
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