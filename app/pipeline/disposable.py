"""Disposable domain detection with maintainable list and online updates."""

import os
import logging
import asyncio
from typing import Set, Optional
import httpx
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)


class DisposableDomainChecker:
    """Disposable domain checker with caching and auto-updates."""
    
    def __init__(self):
        self._domains: Set[str] = set()
        self._loaded = False
        self._lock = asyncio.Lock()
        self._domains_file = Path(__file__).parent.parent / "disposable_domains.txt"
    
    async def load_domains(self) -> None:
        """Load disposable domains from file."""
        async with self._lock:
            if self._loaded:
                return
            
            try:
                if self._domains_file.exists():
                    with open(self._domains_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip().lower()
                            # Skip comments and empty lines
                            if line and not line.startswith('#'):
                                self._domains.add(line)
                    
                    logger.info(f"Loaded {len(self._domains)} disposable domains")
                else:
                    logger.warning(f"Disposable domains file not found: {self._domains_file}")
                
                self._loaded = True
                
            except Exception as e:
                logger.error(f"Error loading disposable domains: {e}")
                self._loaded = True  # Mark as loaded to avoid repeated attempts
    
    async def is_disposable(self, domain: str) -> bool:
        """
        Check if domain is disposable.
        
        Args:
            domain: Domain name to check
            
        Returns:
            True if domain is disposable
        """
        if not self._loaded:
            await self.load_domains()
        
        if not domain:
            return False
        
        domain = domain.lower().strip()
        
        # Direct match
        if domain in self._domains:
            return True
        
        # Check parent domains (for subdomains of disposable services)
        parts = domain.split('.')
        for i in range(1, len(parts)):
            parent_domain = '.'.join(parts[i:])
            if parent_domain in self._domains:
                return True
        
        return False
    
    async def update_from_url(self, url: Optional[str] = None) -> bool:
        """
        Update disposable domains list from remote URL.
        
        Args:
            url: URL to fetch domains from (uses config default if None)
            
        Returns:
            True if update was successful
        """
        if not url:
            url = settings.disposable_auto_update_url
        
        if not url:
            logger.warning("No disposable domains update URL configured")
            return False
        
        try:
            logger.info(f"Updating disposable domains from {url}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                content = response.text
                new_domains = set()
                
                for line in content.splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith('#'):
                        # Handle different formats
                        if line.startswith('*.'):
                            line = line[2:]  # Remove wildcard prefix
                        new_domains.add(line)
                
                if new_domains:
                    # Backup current file
                    backup_file = self._domains_file.with_suffix('.txt.backup')
                    if self._domains_file.exists():
                        self._domains_file.rename(backup_file)
                    
                    # Write new domains
                    with open(self._domains_file, 'w', encoding='utf-8') as f:
                        f.write("# Disposable email domains - one per line\n")
                        f.write("# Updated automatically from remote source\n")
                        f.write(f"# Source: {url}\n\n")
                        
                        for domain in sorted(new_domains):
                            f.write(f"{domain}\n")
                    
                    # Update in-memory cache
                    async with self._lock:
                        self._domains = new_domains
                        self._loaded = True
                    
                    logger.info(f"Updated {len(new_domains)} disposable domains")
                    return True
                else:
                    logger.warning("No domains found in remote source")
                    return False
                    
        except Exception as e:
            logger.error(f"Error updating disposable domains: {e}")
            return False
    
    def get_domain_count(self) -> int:
        """Get number of loaded disposable domains."""
        return len(self._domains)
    
    async def add_domain(self, domain: str) -> bool:
        """
        Add a domain to the disposable list.
        
        Args:
            domain: Domain to add
            
        Returns:
            True if domain was added
        """
        if not domain:
            return False
        
        domain = domain.lower().strip()
        
        async with self._lock:
            if domain not in self._domains:
                self._domains.add(domain)
                
                # Append to file
                try:
                    with open(self._domains_file, 'a', encoding='utf-8') as f:
                        f.write(f"{domain}\n")
                    logger.info(f"Added disposable domain: {domain}")
                    return True
                except Exception as e:
                    logger.error(f"Error adding domain to file: {e}")
                    return False
        
        return False
    
    async def remove_domain(self, domain: str) -> bool:
        """
        Remove a domain from the disposable list.
        
        Args:
            domain: Domain to remove
            
        Returns:
            True if domain was removed
        """
        if not domain:
            return False
        
        domain = domain.lower().strip()
        
        async with self._lock:
            if domain in self._domains:
                self._domains.remove(domain)
                
                # Rewrite file
                try:
                    with open(self._domains_file, 'w', encoding='utf-8') as f:
                        f.write("# Disposable email domains - one per line\n")
                        f.write("# This is a seed list that can be updated via CLI command\n\n")
                        
                        for d in sorted(self._domains):
                            f.write(f"{d}\n")
                    
                    logger.info(f"Removed disposable domain: {domain}")
                    return True
                except Exception as e:
                    logger.error(f"Error updating file after removal: {e}")
                    return False
        
        return False


# Global instance - load domains synchronously for ultra-fast checking
disposable_checker = DisposableDomainChecker()

# Pre-load domains set for instant checking
_LOADED_DOMAINS: Set[str] = set()
_DOMAINS_LOADED = False

def _load_domains_sync() -> Set[str]:
    """Load disposable domains synchronously for ultra-fast checking."""
    global _LOADED_DOMAINS, _DOMAINS_LOADED
    
    if _DOMAINS_LOADED:
        return _LOADED_DOMAINS
    
    try:
        domains_file = Path(__file__).parent.parent / "disposable_domains.txt"
        if domains_file.exists():
            with open(domains_file, 'r', encoding='utf-8') as f:
                domains = {line.strip().lower() for line in f if line.strip() and not line.strip().startswith('#')}
                _LOADED_DOMAINS.update(domains)
                logger.info(f"Loaded {len(domains)} disposable domains from file")
        
        # Add common disposable domains for immediate use
        common_disposable = {
            '10minutemail.com', 'tempmail.org', 'guerrillamail.com', 'mailinator.com',
            'temp-mail.org', 'yopmail.com', 'throwaway.email', 'maildrop.cc',
            'sharklasers.com', 'mailnesia.com', 'trashmail.com', 'dispostable.com'
        }
        _LOADED_DOMAINS.update(common_disposable)
        _DOMAINS_LOADED = True
        
        logger.info(f"Ultra-fast disposable checker loaded with {len(_LOADED_DOMAINS)} domains")
        return _LOADED_DOMAINS
        
    except Exception as e:
        logger.warning(f"Failed to load disposable domains: {e}")
        _DOMAINS_LOADED = True
        return _LOADED_DOMAINS

def is_disposable_domain_fast(domain: str) -> bool:
    """
    Ultra-fast synchronous disposable domain check.
    
    Args:
        domain: Domain name to check
        
    Returns:
        True if domain is disposable
    """
    if not _DOMAINS_LOADED:
        _load_domains_sync()
    
    domain_lower = domain.lower().strip()
    return domain_lower in _LOADED_DOMAINS


async def is_disposable_domain(domain: str) -> bool:
    """
    Check if domain is disposable (async wrapper for compatibility).
    
    Args:
        domain: Domain name to check
        
    Returns:
        True if domain is disposable
    """
    # Use the ultra-fast synchronous version
    return is_disposable_domain_fast(domain)


async def update_disposable_domains(url: Optional[str] = None) -> bool:
    """
    Update disposable domains list (convenience function).
    
    Args:
        url: URL to fetch domains from
        
    Returns:
        True if update was successful
    """
    return await disposable_checker.update_from_url(url)


def get_common_disposable_patterns() -> Set[str]:
    """
    Get common patterns that indicate disposable domains.
    
    Returns:
        Set of patterns to look for in domain names
    """
    return {
        'temp', 'temporary', 'disposable', 'throwaway', 'fake',
        'trash', 'spam', 'junk', '10min', '20min', 'minute',
        'guerrilla', 'mailinator', 'yopmail', 'tempmail'
    }


def looks_like_disposable(domain: str) -> bool:
    """
    Heuristic check if domain looks like it might be disposable.
    
    Args:
        domain: Domain name to check
        
    Returns:
        True if domain has patterns suggesting it's disposable
    """
    if not domain:
        return False
    
    domain_lower = domain.lower()
    patterns = get_common_disposable_patterns()
    
    # Check if any pattern appears in domain
    for pattern in patterns:
        if pattern in domain_lower:
            return True
    
    # Check for numeric patterns (like 10minutemail)
    if any(char.isdigit() for char in domain_lower):
        time_words = ['min', 'minute', 'hour', 'day', 'temp', 'mail']
        if any(word in domain_lower for word in time_words):
            return True
    
    return False