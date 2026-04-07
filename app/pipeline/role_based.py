"""Role-based email address detection."""

import logging
from typing import Set, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class RoleBasedChecker:
    """Role-based email address checker."""
    
    def __init__(self):
        self._prefixes: Set[str] = set()
        self._loaded = False
        self._prefixes_file = Path(__file__).parent.parent / "role_based_prefixes.txt"
    
    def load_prefixes(self) -> None:
        """Load role-based prefixes from file."""
        if self._loaded:
            return
        
        try:
            if self._prefixes_file.exists():
                with open(self._prefixes_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip().lower()
                        # Skip comments and empty lines
                        if line and not line.startswith('#'):
                            self._prefixes.add(line)
                
                logger.info(f"Loaded {len(self._prefixes)} role-based prefixes")
            else:
                logger.warning(f"Role-based prefixes file not found: {self._prefixes_file}")
            
            self._loaded = True
            
        except Exception as e:
            logger.error(f"Error loading role-based prefixes: {e}")
            self._loaded = True  # Mark as loaded to avoid repeated attempts
    
    def is_role_based(self, email: str) -> bool:
        """
        Check if email address is role-based.
        
        Args:
            email: Email address to check
            
        Returns:
            True if email appears to be role-based
        """
        if not self._loaded:
            self.load_prefixes()
        
        if not email or '@' not in email:
            return False
        
        localpart = email.split('@')[0].lower().strip()
        
        # Direct match
        if localpart in self._prefixes:
            return True
        
        # Check for common variations with separators
        normalized_localpart = localpart.replace('-', '').replace('_', '').replace('.', '')
        if normalized_localpart in self._prefixes:
            return True
        
        # Check if localpart starts with known role prefix
        for prefix in self._prefixes:
            if localpart.startswith(prefix):
                # Check if it's followed by separator or number
                remaining = localpart[len(prefix):]
                if not remaining or remaining[0] in '-_.0123456789':
                    return True
        
        return False
    
    def get_role_type(self, email: str) -> Optional[str]:
        """
        Get the type of role-based email.
        
        Args:
            email: Email address to analyze
            
        Returns:
            Role type category or None if not role-based
        """
        if not self.is_role_based(email):
            return None
        
        if not email or '@' not in email:
            return None
        
        localpart = email.split('@')[0].lower().strip()
        
        # Define role categories
        role_categories = {
            'administrative': {
                'admin', 'administrator', 'root', 'postmaster', 'webmaster',
                'hostmaster', 'system', 'systems'
            },
            'support': {
                'support', 'help', 'helpdesk', 'service', 'services',
                'tech', 'technical', 'it', 'itsupport'
            },
            'sales_marketing': {
                'sales', 'marketing', 'info', 'information', 'contact',
                'enquiry', 'enquiries', 'inquiry', 'inquiries'
            },
            'hr_legal': {
                'hr', 'human-resources', 'humanresources', 'legal',
                'careers', 'jobs', 'recruitment'
            },
            'finance': {
                'billing', 'accounts', 'accounting', 'finance', 'invoice',
                'invoices', 'orders', 'order', 'procurement', 'purchasing'
            },
            'communication': {
                'noreply', 'no-reply', 'newsletter', 'news', 'updates',
                'alerts', 'notifications', 'press', 'media', 'pr'
            },
            'security': {
                'security', 'abuse', 'privacy', 'compliance', 'audit',
                'risk', 'security-team'
            }
        }
        
        # Normalize localpart for matching
        normalized = localpart.replace('-', '').replace('_', '').replace('.', '')
        
        for category, prefixes in role_categories.items():
            for prefix in prefixes:
                normalized_prefix = prefix.replace('-', '').replace('_', '')
                if normalized.startswith(normalized_prefix):
                    return category
                if localpart.startswith(prefix):
                    return category
        
        return 'generic'
    
    def get_prefix_count(self) -> int:
        """Get number of loaded role-based prefixes."""
        if not self._loaded:
            self.load_prefixes()
        return len(self._prefixes)
    
    def add_prefix(self, prefix: str) -> bool:
        """
        Add a prefix to the role-based list.
        
        Args:
            prefix: Prefix to add
            
        Returns:
            True if prefix was added
        """
        if not prefix:
            return False
        
        prefix = prefix.lower().strip()
        
        if prefix not in self._prefixes:
            self._prefixes.add(prefix)
            
            # Append to file
            try:
                with open(self._prefixes_file, 'a', encoding='utf-8') as f:
                    f.write(f"{prefix}\n")
                logger.info(f"Added role-based prefix: {prefix}")
                return True
            except Exception as e:
                logger.error(f"Error adding prefix to file: {e}")
                return False
        
        return False


# Global instance
role_checker = RoleBasedChecker()


def is_role_based_email(email: str) -> bool:
    """
    Check if email address is role-based (convenience function).
    
    Args:
        email: Email address to check
        
    Returns:
        True if email appears to be role-based
    """
    return role_checker.is_role_based(email)


def get_role_type(email: str) -> Optional[str]:
    """
    Get the type of role-based email (convenience function).
    
    Args:
        email: Email address to analyze
        
    Returns:
        Role type category or None if not role-based
    """
    return role_checker.get_role_type(email)


def get_common_role_patterns() -> Set[str]:
    """
    Get common role-based email patterns.
    
    Returns:
        Set of common role-based patterns
    """
    return {
        # Administrative
        'admin', 'administrator', 'root', 'postmaster', 'webmaster',
        
        # Support
        'support', 'help', 'helpdesk', 'service',
        
        # Sales & Marketing
        'sales', 'marketing', 'info', 'contact',
        
        # HR & Legal
        'hr', 'legal', 'careers', 'jobs',
        
        # Finance
        'billing', 'accounts', 'finance', 'orders',
        
        # Communication
        'noreply', 'newsletter', 'news', 'press',
        
        # Security
        'security', 'abuse', 'privacy'
    }


def analyze_email_localpart(localpart: str) -> dict:
    """
    Analyze email localpart for various characteristics.
    
    Args:
        localpart: Local part of email address (before @)
        
    Returns:
        Dictionary with analysis results
    """
    if not localpart:
        return {}
    
    localpart = localpart.lower()
    
    analysis = {
        'is_role_based': False,
        'role_category': None,
        'has_numbers': any(c.isdigit() for c in localpart),
        'has_separators': any(c in localpart for c in '-_.'),
        'length': len(localpart),
        'patterns': []
    }
    
    # Check role-based
    if role_checker.is_role_based(f"{localpart}@example.com"):
        analysis['is_role_based'] = True
        analysis['role_category'] = role_checker.get_role_type(f"{localpart}@example.com")
    
    # Check for common patterns
    if localpart.startswith('no') and ('reply' in localpart or 'response' in localpart):
        analysis['patterns'].append('noreply')
    
    if any(word in localpart for word in ['test', 'demo', 'sample']):
        analysis['patterns'].append('test_account')
    
    if localpart.count('.') >= 2:
        analysis['patterns'].append('multiple_dots')
    
    if len(localpart) <= 2:
        analysis['patterns'].append('very_short')
    
    if len(localpart) >= 20:
        analysis['patterns'].append('very_long')
    
    return analysis