"""Final status decision engine that combines all verification signals."""

import logging
from typing import List, Dict, Any, Optional
from app.models import VerificationStatus, ReasonCode
from app.schemas import VerificationResult
from app.pipeline.soft_bounce_detector import SoftBounceDetector

logger = logging.getLogger(__name__)


class VerificationClassifier:
    """Classifies email verification results based on multiple signals."""
    
    def __init__(self):
        self.soft_bounce_detector = SoftBounceDetector()
        
        # Define classification rules and priorities
        # IMPORTANT: Check soft bounce BEFORE marking as valid!
        self.classification_rules = [
            self._classify_disposable,
            self._classify_syntax_invalid,
            self._classify_dns_invalid,
            self._classify_smtp_invalid,
            self._classify_soft_bounce,  # ⭐ NEW: Check for soft bounces
            self._classify_catch_all,
            self._classify_role_based,
            self._classify_tempfail,
            self._classify_deliverable,
            self._classify_network_fallback,
            self._classify_unknown
        ]
    
    def classify(self, signals: Dict[str, Any]) -> VerificationResult:
        """
        Classify email verification result based on collected signals.
        
        Args:
            signals: Dictionary containing all verification signals
            
        Returns:
            VerificationResult with final classification
        """
        email = signals.get('email', '')
        
        # Initialize result
        result = VerificationResult(
            email=email,
            status=VerificationStatus.UNKNOWN_TEMPFAIL,
            reason_code=ReasonCode.NETWORK_ERROR,
            reasons=[],
            mx_records=signals.get('mx_records', []),
            has_mx=signals.get('has_mx', False),
            smtp_transcript=signals.get('smtp_transcript', []),
            smtp_accepted=signals.get('smtp_accepted', False),
            is_catch_all=signals.get('is_catch_all', False),
            is_role_based=signals.get('is_role_based', False),
            is_disposable=signals.get('is_disposable', False),
            verification_duration_ms=signals.get('verification_duration_ms')
        )
        
        # Apply classification rules in order of priority
        for rule in self.classification_rules:
            if rule(signals, result):
                break  # First matching rule wins
        
        # Ensure we have at least one reason
        if not result.reasons:
            result.reasons.append("Classification completed")
        
        logger.debug(
            f"Classified {email} as {result.status.value} "
            f"with reason {result.reason_code.value}"
        )
        
        return result
    
    def _classify_disposable(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Check if email is from disposable domain."""
        if signals.get('is_disposable', False):
            result.status = VerificationStatus.DISPOSABLE
            result.reason_code = ReasonCode.DISPOSABLE_DOMAIN
            result.reasons.append("Email from known disposable domain")
            return True
        return False
    
    def _classify_syntax_invalid(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Check if email has syntax errors."""
        if not signals.get('syntax_valid', True):
            result.status = VerificationStatus.INVALID
            result.reason_code = ReasonCode.SYNTAX_ERROR
            result.reasons.append(signals.get('syntax_error', "Invalid email syntax"))
            return True
        return False
    
    def _classify_dns_invalid(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Check if domain has DNS issues."""
        if not signals.get('has_mx', False):
            result.status = VerificationStatus.INVALID
            result.reason_code = ReasonCode.NO_MX_RECORD
            dns_error = signals.get('dns_error', "No MX or A records found")
            result.reasons.append(f"DNS resolution failed: {dns_error}")
            return True
        return False
    
    def _classify_smtp_invalid(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """
        Check for SMTP permanent failures.
        
        CRITICAL IMPROVEMENT:
        - 5xx codes = Permanent failure (mark INVALID)
        - 4xx codes = Temporary failure (mark UNKNOWN, not INVALID)
        - 450/451 = Greylisting (temporary, not invalid)
        """
        smtp_code = signals.get('smtp_code')
        is_tempfail = signals.get('is_tempfail', False)
        is_greylisting = signals.get('is_greylisting', False)
        is_permanent = signals.get('smtp_permanent_fail', False)
        
        # ONLY mark as INVALID for 5xx codes (permanent failures)
        if is_permanent and smtp_code and 500 <= smtp_code < 600:
            result.status = VerificationStatus.INVALID
            
            # Determine specific reason based on SMTP code
            if smtp_code in [550, 551]:
                result.reason_code = ReasonCode.SMTP_USER_UNKNOWN
                result.reasons.append(f"✗ INVALID: SMTP rejected (code {smtp_code} - user unknown)")
            elif smtp_code in [553, 554]:
                result.reason_code = ReasonCode.SMTP_USER_UNKNOWN
                result.reasons.append(f"✗ INVALID: SMTP rejected (code {smtp_code})")
            else:
                result.reason_code = ReasonCode.SMTP_USER_UNKNOWN
                result.reasons.append(f"✗ INVALID: SMTP permanent failure (code {smtp_code})")
            
            return True
        
        # DO NOT MARK AS INVALID for 4xx (temporary) codes
        # These should be handled by _classify_tempfail instead
        return False
    
    def _classify_soft_bounce(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """
        Check for emails likely to soft bounce despite SMTP acceptance.
        
        ⭐ NEW FEATURE: Detect emails that SMTP accepts but later bounce
        
        Examples:
        - bchodroff@oncloudone.com (accepted but bounces)
        - catch-all domains with aggressive filtering
        - Temporary mail services
        - Test/demo addresses
        """
        email = signals.get('email', '')
        domain = signals.get('domain', '').lower()
        
        # Only check if SMTP accepted (otherwise it's already invalid)
        if not signals.get('smtp_accepted', False):
            return False
        
        # Check for soft bounce risk
        is_soft_bounce, bounce_reason = self.soft_bounce_detector.is_likely_soft_bounce(
            email, domain
        )
        
        if is_soft_bounce:
            result.status = VerificationStatus.RISKY_CATCH_ALL
            result.reason_code = ReasonCode.CATCH_ALL_DETECTED
            result.reasons.append(f"⚠️ RISKY: {bounce_reason}")
            result.reasons.append("Email accepted by SMTP but likely to bounce later")
            return True
        
        # Get soft bounce confidence score
        smtp_code = signals.get('smtp_code')
        confidence, confidence_reason = self.soft_bounce_detector.get_soft_bounce_confidence(
            email, domain,
            smtp_code=smtp_code if isinstance(smtp_code, int) else None,
            is_catch_all=signals.get('is_catch_all', False)
        )
        
        # If high confidence of soft bounce, mark as risky
        if confidence > 70:
            result.status = VerificationStatus.RISKY_CATCH_ALL
            result.reason_code = ReasonCode.CATCH_ALL_DETECTED
            result.reasons.append(f"⚠️ HIGH BOUNCE RISK ({confidence}%): {confidence_reason}")
            return True
        
        # If medium confidence, mark as uncertain
        elif confidence > 40:
            result.status = VerificationStatus.UNKNOWN_TEMPFAIL
            result.reason_code = ReasonCode.SMTP_TEMPFAIL
            result.reasons.append(f"⚠️ UNCERTAIN ({confidence}%): {confidence_reason}")
            return True
        
        return False
    
    def _classify_catch_all(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Check for catch-all domains."""
        if (signals.get('is_catch_all', False) and 
            signals.get('smtp_accepted', False)):
            
            result.status = VerificationStatus.RISKY_CATCH_ALL
            result.reason_code = ReasonCode.CATCH_ALL_DETECTED
            result.reasons.append("Domain accepts all email addresses (catch-all)")
            
            # Add additional context
            if signals.get('catch_all_confidence', 0) < 0.8:
                result.reasons.append("Catch-all detection has medium confidence")
            
            return True
        return False
    
    def _classify_role_based(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Check for role-based addresses."""
        if (signals.get('is_role_based', False) and 
            not signals.get('is_catch_all', False) and
            signals.get('smtp_accepted', False)):
            
            result.status = VerificationStatus.RISKY_ROLE_BASED
            result.reason_code = ReasonCode.ROLE_BASED_ADDRESS
            
            role_type = signals.get('role_type', 'generic')
            result.reasons.append(f"Role-based address ({role_type})")
            result.reasons.append("May have delivery restrictions or policies")
            
            return True
        return False
    
    def _classify_tempfail(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """
        Check for temporary failures (4xx codes and greylisting).
        
        CRITICAL IMPROVEMENTS:
        - 4xx codes = Temporary (mark UNKNOWN, try again later)
        - 450/451 = Greylisting (mark VALID with note)
        - Timeout + MX exists = Valid (benefit of doubt)
        """
        is_tempfail = signals.get('is_tempfail', False)
        is_greylisting = signals.get('is_greylisting', False)
        smtp_code = signals.get('smtp_code')
        timeout_occurred = signals.get('timeout_occurred', False)
        has_mx = signals.get('has_mx', False)
        
        # GREYLISTING (450/451): Assume VALID for later retry
        if is_greylisting or smtp_code in [450, 451]:
            result.status = VerificationStatus.DELIVERABLE
            result.reason_code = ReasonCode.SMTP_ACCEPTED
            result.smtp_accepted = True  # Mark as accepted - it's greylisting, not rejection
            result.reasons.append(f"⚠ Greylisting detected (code {smtp_code})")
            result.reasons.append("Server requested retry - email is likely valid")
            return True
        
        # TIMEOUT + MX EXISTS: Assume VALID (benefit of doubt)
        if timeout_occurred and has_mx and not signals.get('smtp_permanent_fail', False):
            result.status = VerificationStatus.DELIVERABLE
            result.reason_code = ReasonCode.SMTP_ACCEPTED
            result.smtp_accepted = True
            result.reasons.append(f"⏱ SMTP timeout (likely greylisting)")
            result.reasons.append("Domain has valid MX records - assuming valid")
            return True
        
        # OTHER 4xx CODES: Mark as temporary failure (not invalid!)
        if is_tempfail:
            result.status = VerificationStatus.UNKNOWN_TEMPFAIL
            result.reason_code = ReasonCode.SMTP_TEMPFAIL
            
            if smtp_code:
                result.reasons.append(f"⚠ Temporary SMTP failure (code {smtp_code})")
            else:
                result.reasons.append(f"⚠ Temporary network failure")
            
            # Add context about retries
            retry_count = signals.get('retry_count', 0)
            if retry_count > 0:
                result.reasons.append(f"Failed after {retry_count} retry attempts")
            else:
                result.reasons.append("Try again in a few minutes - server is experiencing temporary issues")
            
            return True
        
        return False
    
    def _classify_deliverable(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Check if email is deliverable."""
        if (signals.get('smtp_accepted', False) and 
            not signals.get('is_catch_all', False) and
            not signals.get('is_disposable', False)):
            
            result.status = VerificationStatus.DELIVERABLE
            result.reason_code = ReasonCode.SMTP_ACCEPTED
            result.reasons.append("SMTP server accepted recipient")
            
            # Add confidence indicators
            if signals.get('has_mx', False):
                result.reasons.append("Domain has valid MX records")
            
            if signals.get('smtp_starttls_used', False):
                result.reasons.append("SMTP connection used STARTTLS encryption")
            
            return True
        return False
    
    def _classify_network_fallback(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Handle network errors with improved fallback logic and webmail support."""
        domain = signals.get('domain', '').lower()
        is_webmail = signals.get('is_webmail', False)
        confidence_score = signals.get('confidence_score', 0)
        
        # Enhanced classification for known webmail providers
        known_good_domains = {
            'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 
            'live.com', 'aol.com', 'icloud.com', 'me.com', 'msn.com',
            'protonmail.com', 'yandex.com', 'mail.com', 'zoho.com',
            'yahoo.co.uk', 'yahoo.ca', 'ymail.com', 'rocketmail.com',
            'proton.me', 'comcast.net', 'verizon.net', 'att.net'
        }
        
        # If we have DNS but SMTP failed due to network issues
        if (signals.get('has_mx', False) and 
            (signals.get('network_error', False) or 
             signals.get('smtp_error') or 
             not signals.get('smtp_connected', False)) and
            not signals.get('is_disposable', False)):
            
            # Check for common business domains
            business_tlds = {'.com', '.org', '.net', '.info', '.biz', '.co'}
            likely_business = any(domain.endswith(tld) for tld in business_tlds)
            
            # Enhanced webmail provider detection
            if domain in known_good_domains or (is_webmail and confidence_score >= 70):
                # For major providers, assume deliverable even if SMTP fails
                result.status = VerificationStatus.DELIVERABLE
                result.reason_code = ReasonCode.SMTP_ACCEPTED
                result.smtp_accepted = True  # Mark as accepted for known providers
                if is_webmail:
                    result.reasons.append(f"Verified webmail provider - highly likely deliverable")
                    result.reasons.append(f"Confidence score: {confidence_score}%")
                else:
                    result.reasons.append("Major email provider - highly likely deliverable")
                result.reasons.append("SMTP verification blocked by provider policies")
            elif likely_business:
                # For business domains with MX records, be more optimistic
                if signals.get('is_role_based', False):
                    # Role-based business emails - mark as risky but potentially valid
                    result.status = VerificationStatus.RISKY_ROLE_BASED
                    result.reason_code = ReasonCode.ROLE_BASED_ADDRESS
                    result.reasons.append("Role-based business email with valid MX records")
                    result.reasons.append("Domain appears legitimate - likely deliverable")
                    result.reasons.append("SMTP verification blocked by network policies")
                else:
                    # Regular business emails - assume deliverable
                    result.status = VerificationStatus.DELIVERABLE
                    result.reason_code = ReasonCode.SMTP_ACCEPTED
                    result.smtp_accepted = True
                    result.reasons.append("Business domain with valid MX records")
                    result.reasons.append("Likely deliverable - verification limited by network policies")
            else:
                # For other domains with valid MX, mark as risky but potentially valid
                result.status = VerificationStatus.RISKY_CATCH_ALL
                result.reason_code = ReasonCode.NETWORK_ERROR
                result.reasons.append("Could not verify due to network restrictions")
                result.reasons.append("Domain has valid MX records - potentially deliverable")
            return True
        
        # If SMTP verification was successful with high confidence
        elif signals.get('smtp_connected', False) and confidence_score >= 80:
            result.status = VerificationStatus.DELIVERABLE
            result.reason_code = ReasonCode.SMTP_ACCEPTED
            result.reasons.append(f"Enhanced SMTP verification successful (confidence: {confidence_score}%)")
            if is_webmail:
                result.reasons.append(f"Verified webmail provider: {domain}")
            return True
        
        return False
    
    def _classify_unknown(self, signals: Dict[str, Any], result: VerificationResult) -> bool:
        """Default classification for unclear cases."""
        # Try network fallback first
        if self._classify_network_fallback(signals, result):
            return True
        
        # This should always match as the final fallback
        
        # Try to determine the most appropriate unknown reason
        if signals.get('dns_timeout', False):
            result.reason_code = ReasonCode.DNS_TIMEOUT
            result.reasons.append("DNS resolution timeout")
        elif signals.get('smtp_timeout', False):
            result.reason_code = ReasonCode.SMTP_TIMEOUT
            result.reasons.append("SMTP connection timeout")
        elif signals.get('network_error', False):
            result.reason_code = ReasonCode.NETWORK_ERROR
            result.reasons.append("Network connectivity error")
        else:
            result.reason_code = ReasonCode.NETWORK_ERROR
            result.reasons.append("Unable to determine deliverability")
        
        result.status = VerificationStatus.UNKNOWN_TEMPFAIL
        return True


def analyze_big_provider_behavior(domain: str, signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze behavior patterns for major email providers.
    
    Args:
        domain: Email domain
        signals: Verification signals
        
    Returns:
        Dictionary with provider-specific analysis
    """
    big_providers = {
        'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 
        'live.com', 'yahoo.com', 'aol.com', 'icloud.com', 'me.com'
    }
    
    analysis = {
        'is_big_provider': domain.lower() in big_providers,
        'provider_type': None,
        'reliability_notes': []
    }
    
    domain_lower = domain.lower()
    
    if domain_lower in ['gmail.com', 'googlemail.com']:
        analysis['provider_type'] = 'google'
        analysis['reliability_notes'].append(
            "Gmail may accept RCPT for non-existent users"
        )
        
    elif domain_lower in ['outlook.com', 'hotmail.com', 'live.com']:
        analysis['provider_type'] = 'microsoft'
        analysis['reliability_notes'].append(
            "Outlook.com implements tarpitting and may delay responses"
        )
        
    elif domain_lower == 'yahoo.com':
        analysis['provider_type'] = 'yahoo'
        analysis['reliability_notes'].append(
            "Yahoo may implement greylisting for unknown senders"
        )
    
    # If it's a big provider and SMTP accepted, add uncertainty note
    if (analysis['is_big_provider'] and 
        signals.get('smtp_accepted', False)):
        analysis['reliability_notes'].append(
            "Large providers may accept RCPT without guaranteeing delivery"
        )
    
    return analysis


def calculate_confidence_score(signals: Dict[str, Any]) -> float:
    """
    Calculate confidence score for verification result.
    
    Args:
        signals: Verification signals
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    confidence = 0.5  # Base confidence
    
    # Syntax validation adds confidence
    if signals.get('syntax_valid', False):
        confidence += 0.1
    
    # DNS resolution adds confidence
    if signals.get('has_mx', False):
        confidence += 0.1
    
    # SMTP connection adds confidence
    if signals.get('smtp_connected', False):
        confidence += 0.1
    
    # Clear SMTP response adds confidence
    smtp_code = signals.get('smtp_code')
    if smtp_code:
        if smtp_code in [250, 251]:  # Accepted
            confidence += 0.2
        elif smtp_code in [550, 551]:  # Rejected
            confidence += 0.2
        elif 400 <= smtp_code < 500:  # Tempfail
            confidence += 0.1
    
    # Disposable domain detection adds confidence
    if signals.get('is_disposable', False):
        confidence += 0.1
    
    # Catch-all detection affects confidence
    if signals.get('is_catch_all', False):
        catch_all_confidence = signals.get('catch_all_confidence', 0.5)
        confidence += catch_all_confidence * 0.1
    
    # Big provider reduces confidence for positive results
    domain = signals.get('domain', '')
    if domain:
        provider_analysis = analyze_big_provider_behavior(domain, signals)
        if (provider_analysis['is_big_provider'] and 
            signals.get('smtp_accepted', False)):
            confidence -= 0.1
    
    # Network errors reduce confidence
    if signals.get('network_error', False):
        confidence -= 0.2
    
    # Timeouts reduce confidence
    if signals.get('dns_timeout', False) or signals.get('smtp_timeout', False):
        confidence -= 0.1
    
    # Ensure confidence is within bounds
    return max(0.0, min(1.0, confidence))


# Global classifier instance
classifier = VerificationClassifier()


def classify_verification_result(signals: Dict[str, Any]) -> VerificationResult:
    """
    Classify verification result (convenience function).
    
    Args:
        signals: Dictionary containing all verification signals
        
    Returns:
        VerificationResult with final classification
    """
    return classifier.classify(signals)