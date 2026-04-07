"""
Soft Bounce Detection - Advanced email validation.

مسئلہ: SMTP verification صرف یہ چیک کرتا ہے کہ SERVER نے accept کیا یا نہیں
      لیکن یہ نہیں چیک کرتا کہ email بعد میں bounce ہوگی یا نہیں

حل: Soft bounce patterns detect کریں:
- Catch-all domains جو filter کرتے ہیں
- Temporary mail servers
- Role-based emails جو delivery issues رکھتے ہیں
- Invalid format despite SMTP accept
"""

from typing import Dict, Any, Tuple, Optional
import re

# Known soft-bounce providers
SOFT_BOUNCE_DOMAINS = {
    # Domains that often accept emails but bounce them later
    'oncloudone.com',       # ⚠️ This domain bounces later!
    'tempmail.org',
    'guerrillamail.com',
    'yopmail.com',
}

# Domains with catch-all + filtering (bounce later)
CATCHALL_WITH_FILTERS = {
    'oncloudone.com',
    'yahoo.com',            # Some Yahoo accounts have aggressive filtering
    'mail.ru',
    'mailgun.org',
}

class SoftBounceDetector:
    """Detect emails likely to bounce despite SMTP acceptance."""
    
    def __init__(self):
        self.soft_bounce_patterns = [
            r'oncloudone\.com',           # Known soft bouncer
            r'catch\.?all',               # Generic catch-all
            r'temp.*mail',                # Temporary mail services
            r'throwaway',                 # Throwaway addresses
            r'(?:test|demo|sample|fake)', # Test addresses
        ]
    
    def is_likely_soft_bounce(self, email: str, domain: str) -> Tuple[bool, str]:
        """
        Detect if email is likely to bounce despite SMTP acceptance.
        
        Args:
            email: Full email address
            domain: Domain part
            
        Returns:
            (is_likely_soft_bounce, reason)
        """
        domain_lower = domain.lower()
        
        # Check if domain is known soft bouncer
        if domain_lower in SOFT_BOUNCE_DOMAINS:
            return True, f"Domain {domain} is known to soft bounce"
        
        # Check if domain matches soft bounce patterns
        for pattern in self.soft_bounce_patterns:
            if re.search(pattern, domain_lower, re.IGNORECASE):
                return True, f"Domain matches soft bounce pattern: {pattern}"
        
        # Check email format indicators
        local_part = email.split('@')[0].lower()
        
        # Numbers-only or very generic patterns might be soft bounce risks
        if re.match(r'^\d{5,}$', local_part):  # 5+ digit addresses
            return True, "Numeric-only address (possible test/disposable)"
        
        # Generic role addresses with certain domains have higher soft bounce
        generic_roles = {'test', 'demo', 'sample', 'fake', 'noreply', 'no-reply'}
        if any(role in local_part for role in generic_roles):
            if domain_lower in CATCHALL_WITH_FILTERS:
                return True, f"Generic role address on {domain} with aggressive filtering"
        
        return False, ""
    
    def get_soft_bounce_confidence(self, email: str, domain: str, 
                                  smtp_code: Optional[int] = None, 
                                  is_catch_all: bool = False) -> Tuple[int, str]:
        """
        Calculate confidence score for soft bounce likelihood.
        
        Args:
            email: Email address
            domain: Domain
            smtp_code: SMTP response code
            is_catch_all: Whether domain is catch-all
            
        Returns:
            (confidence_score_0_to_100, reason)
        """
        score = 0
        reasons = []
        
        # Check domain reputation
        domain_lower = domain.lower()
        if domain_lower in SOFT_BOUNCE_DOMAINS:
            score += 40
            reasons.append("Domain in soft bounce list")
        
        # Catch-all + filtering = higher risk
        if is_catch_all and domain_lower in CATCHALL_WITH_FILTERS:
            score += 30
            reasons.append("Catch-all domain with aggressive filtering")
        elif is_catch_all:
            score += 15
            reasons.append("Catch-all domain (may filter later)")
        
        # SMTP temporary fail before accept = risky
        if smtp_code and 400 <= smtp_code < 500:
            score += 10
            reasons.append(f"SMTP temporary failure before acceptance (code {smtp_code})")
        
        # Generic role addresses = higher bounce
        local_part = email.split('@')[0].lower()
        if any(role in local_part for role in ['test', 'demo', 'sample']):
            score += 20
            reasons.append("Test/demo address pattern")
        
        final_reason = " + ".join(reasons) if reasons else "Low risk"
        
        return min(score, 100), final_reason


# Test the detector
if __name__ == "__main__":
    detector = SoftBounceDetector()
    
    # Test case: bchodroff@oncloudone.com
    email = "bchodroff@oncloudone.com"
    domain = "oncloudone.com"
    
    print("\n" + "="*80)
    print(f"Email: {email}")
    print("="*80)
    
    # Check soft bounce
    is_soft_bounce, reason = detector.is_likely_soft_bounce(email, domain)
    print(f"\n1. Soft Bounce Check:")
    print(f"   Result: {'⚠️ YES - High Risk' if is_soft_bounce else '✅ NO - Low Risk'}")
    print(f"   Reason: {reason}")
    
    # Get confidence score
    confidence, full_reason = detector.get_soft_bounce_confidence(
        email, domain, 
        smtp_code=250,
        is_catch_all=False
    )
    print(f"\n2. Soft Bounce Confidence Score: {confidence}%")
    print(f"   Analysis: {full_reason}")
    
    # Recommendation
    if confidence > 70:
        print(f"\n3. Recommendation: 🟡 RISKY - Email likely to bounce")
        print(f"   Action: Mark as RISKY_SOFT_BOUNCE instead of VALID")
    elif confidence > 40:
        print(f"\n3. Recommendation: 🟠 UNCERTAIN - May bounce")
        print(f"   Action: Mark as UNKNOWN_TEMPFAIL")
    else:
        print(f"\n3. Recommendation: ✅ SAFE - Low bounce risk")
        print(f"   Action: Mark as VALID")
