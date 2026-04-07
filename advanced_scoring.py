"""
Advanced Email Verification Scoring System
Implements 7-step verification process with comprehensive scoring
"""

from typing import Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class VerificationScore:
    """Detailed verification score breakdown"""
    step1_syntax: int  # 0-10 points
    step2_mx_records: int  # 0-20 points
    step3_role_based: int  # 0-20 points
    step4_disposable: int  # 0-20 points
    step5_smtp: int  # 0-20 points
    step6_catch_all: int  # 0-10 points (negative)
    step7_total: int  # 80-100 = DELIVERABLE, 60-79 = RISKY, <60 = INVALID
    
    @property
    def total_score(self) -> int:
        """Calculate total score"""
        return sum([
            self.step1_syntax,
            self.step2_mx_records,
            self.step3_role_based,
            self.step4_disposable,
            self.step5_smtp,
            self.step6_catch_all
        ])
    
    @property
    def classification(self) -> str:
        """Get classification based on score"""
        total = self.total_score
        
        if total >= 80:
            return "DELIVERABLE"
        elif total >= 60:
            return "RISKY"
        else:
            return "INVALID"
    
    @property
    def confidence(self) -> float:
        """Get confidence percentage"""
        total = self.total_score
        max_score = 100
        
        if total >= 80:
            # High confidence for DELIVERABLE
            return min(100.0, (total - 80) * 5 + 80)
        elif total >= 60:
            # Medium confidence for RISKY
            return min(100.0, (total - 60) * 2.5 + 60)
        else:
            # Lower confidence for INVALID
            return min(100.0, total)


class AdvancedScoringEngine:
    """
    7-Step Email Verification Scoring System
    
    STEP 1: SYNTAX CHECK (0-10 points)
        10 - Valid email syntax
        0  - Invalid syntax
    
    STEP 2: DOMAIN/MX RECORDS (0-20 points)
        20 - MX records found
        0  - No MX records
    
    STEP 3: ROLE-BASED CHECK (0-20 points)
        20 - Not role-based
        10 - Role-based (moderate risk)
        0  - Unknown/suspicious role
    
    STEP 4: DISPOSABLE/TEMP EMAIL (0-20 points)
        20 - Not disposable
        0  - Disposable domain
    
    STEP 5: SMTP VERIFICATION (0-20 points)
        20 - SMTP accepted
        15 - Webmail provider with valid syntax
        10 - SMTP timeout (likely valid)
        5  - SMTP temporary failure
        0  - SMTP rejected
    
    STEP 6: CATCH-ALL DETECTION (0 to -10 points)
        0  - Not catch-all
        -10 - Catch-all domain (uncertainty penalty)
    
    TOTAL SCORING:
        80-100 → DELIVERABLE (High confidence)
        60-79  → RISKY (Medium confidence)
        <60    → INVALID (Low confidence)
    """
    
    def __init__(self):
        """Initialize scoring engine"""
        self.role_based_keywords = {
            'admin', 'administrator', 'root', 'postmaster', 'webmaster',
            'support', 'info', 'hello', 'help', 'sales', 'contact',
            'billing', 'noreply', 'no-reply', 'reply', 'team',
            'office', 'jobs', 'careers', 'abuse', 'abuse-report',
            'security', 'privacy', 'legal', 'compliance',
            'hr', 'human-resources', 'recruitment',
            'feedback', 'suggestion', 'complaint', 'press', 'news',
            'public', 'general', 'marketing', 'newsletter',
            'test', 'demo', 'sample'
        }
    
    def score_email(self, signals: Dict[str, Any]) -> VerificationScore:
        """
        Calculate comprehensive verification score
        
        Args:
            signals: Verification signals dictionary
        
        Returns:
            VerificationScore object
        """
        
        # STEP 1: Syntax Validation (0-10 points)
        step1_syntax = self._score_step1_syntax(signals)
        
        # STEP 2: Domain/MX Records (0-20 points)
        step2_mx_records = self._score_step2_mx_records(signals)
        
        # STEP 3: Role-Based Detection (0-20 points)
        step3_role_based = self._score_step3_role_based(signals)
        
        # STEP 4: Disposable Domain (0-20 points)
        step4_disposable = self._score_step4_disposable(signals)
        
        # STEP 5: SMTP Verification (0-20 points)
        step5_smtp = self._score_step5_smtp(signals)
        
        # STEP 6: Catch-All Detection (-10 to 0 points)
        step6_catch_all = self._score_step6_catch_all(signals)
        
        return VerificationScore(
            step1_syntax=step1_syntax,
            step2_mx_records=step2_mx_records,
            step3_role_based=step3_role_based,
            step4_disposable=step4_disposable,
            step5_smtp=step5_smtp,
            step6_catch_all=step6_catch_all,
            step7_total=0  # Calculated automatically
        )
    
    def _score_step1_syntax(self, signals: Dict[str, Any]) -> int:
        """STEP 1: Syntax Validation (0-10 points)"""
        
        if signals.get('valid_syntax', False):
            return 10
        
        return 0
    
    def _score_step2_mx_records(self, signals: Dict[str, Any]) -> int:
        """STEP 2: Domain/MX Records (0-20 points)"""
        
        if signals.get('has_mx', False):
            # Bonus: multiple MX records (more robust)
            mx_count = len(signals.get('mx_records', []))
            if mx_count > 1:
                return 20  # Full points for multiple MX records
            return 20  # Full points for at least one MX record
        
        return 0  # No MX records
    
    def _score_step3_role_based(self, signals: Dict[str, Any]) -> int:
        """STEP 3: Role-Based Detection (0-20 points)"""
        
        if not signals.get('is_role_based', False):
            return 20  # Not role-based = good
        
        # Role-based reduces score but doesn't eliminate
        # Still deliverable if other signals are good
        email = signals.get('email', '').lower()
        local_part = email.split('@')[0] if '@' in email else ''
        
        # Check if it's a common business role (moderate risk)
        common_roles = {
            'info', 'contact', 'support', 'sales', 'hello',
            'help', 'billing', 'feedback', 'team', 'admin',
            'office', 'general'
        }
        
        if local_part in common_roles:
            return 10  # Moderate penalty for common roles
        
        # Unknown role gets lower score
        return 5
    
    def _score_step4_disposable(self, signals: Dict[str, Any]) -> int:
        """STEP 4: Disposable/Temp Email (0-20 points)"""
        
        if signals.get('is_disposable', False):
            return 0  # Disposable = automatic fail
        
        return 20  # Not disposable = good
    
    def _score_step5_smtp(self, signals: Dict[str, Any]) -> int:
        """STEP 5: SMTP Verification (0-20 points)"""
        
        if signals.get('smtp_accepted', False):
            return 20  # Explicit acceptance = full points
        
        # Check for webmail with valid syntax (usually deliverable)
        if signals.get('is_webmail', False) and signals.get('valid_syntax', True):
            if signals.get('has_mx', False):
                return 15  # Webmail + MX + syntax = high confidence
        
        # Check for timeout (might be valid despite timeout)
        if signals.get('smtp_timeout', False):
            if signals.get('has_mx', False) and signals.get('valid_syntax', True):
                return 10  # SMTP timeout but MX exists = moderate confidence
        
        # Temporary failure (might be due to rate limiting)
        if signals.get('smtp_tempfail', False):
            if signals.get('has_mx', False):
                return 5  # Temporary failure = low confidence but possible
        
        # SMTP rejected = no points
        return 0
    
    def _score_step6_catch_all(self, signals: Dict[str, Any]) -> int:
        """STEP 6: Catch-All Detection (0 to -10 points)"""
        
        if signals.get('is_catch_all', False):
            return -10  # Catch-all = penalty (uncertainty)
        
        return 0  # Not catch-all = no penalty
    
    def get_detailed_report(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate detailed verification report with scores
        
        Args:
            signals: Verification signals
        
        Returns:
            Dictionary with detailed report
        """
        
        score = self.score_email(signals)
        email = signals.get('email', '')
        
        return {
            'email': email,
            'scores': {
                'step1_syntax': {
                    'points': score.step1_syntax,
                    'max': 10,
                    'label': 'Email Syntax Validation',
                    'description': 'Valid email format check'
                },
                'step2_mx_records': {
                    'points': score.step2_mx_records,
                    'max': 20,
                    'label': 'Domain/MX Records',
                    'description': 'Domain can receive emails'
                },
                'step3_role_based': {
                    'points': score.step3_role_based,
                    'max': 20,
                    'label': 'Role-Based Detection',
                    'description': 'Not a generic mailbox'
                },
                'step4_disposable': {
                    'points': score.step4_disposable,
                    'max': 20,
                    'label': 'Disposable Domain Check',
                    'description': 'Not a temporary email service'
                },
                'step5_smtp': {
                    'points': score.step5_smtp,
                    'max': 20,
                    'label': 'SMTP Verification',
                    'description': 'Server accepts the email'
                },
                'step6_catch_all': {
                    'points': score.step6_catch_all,
                    'max': 0,
                    'min': -10,
                    'label': 'Catch-All Detection',
                    'description': 'Domain does not accept all emails'
                }
            },
            'summary': {
                'total_score': score.total_score,
                'max_score': 100,
                'classification': score.classification,
                'confidence': f"{score.confidence:.1f}%"
            },
            'recommendation': self._get_recommendation(score),
            'signals': {
                'syntax_valid': signals.get('valid_syntax', False),
                'has_mx': signals.get('has_mx', False),
                'smtp_accepted': signals.get('smtp_accepted', False),
                'is_role_based': signals.get('is_role_based', False),
                'is_disposable': signals.get('is_disposable', False),
                'is_catch_all': signals.get('is_catch_all', False),
                'is_webmail': signals.get('is_webmail', False),
                'smtp_timeout': signals.get('smtp_timeout', False),
                'smtp_tempfail': signals.get('smtp_tempfail', False)
            }
        }
    
    def _get_recommendation(self, score: VerificationScore) -> str:
        """Get recommendation based on score"""
        
        total = score.total_score
        
        if total >= 85:
            return "✅ SAFE TO USE - Email is valid and deliverable with high confidence"
        elif total >= 80:
            return "✅ LIKELY VALID - Email is very likely deliverable"
        elif total >= 75:
            return "⚠️ MODERATE RISK - Email may be deliverable but has minor red flags"
        elif total >= 60:
            return "⚠️ CAUTION ADVISED - Email validity uncertain, test before sending bulk"
        elif total >= 40:
            return "❌ HIGH RISK - Email is likely invalid or high bounce risk"
        else:
            return "❌ REJECT - Email is invalid or not deliverable"


# Singleton instance
_scoring_engine = None


def get_scoring_engine() -> AdvancedScoringEngine:
    """Get or create scoring engine instance"""
    global _scoring_engine
    if _scoring_engine is None:
        _scoring_engine = AdvancedScoringEngine()
    return _scoring_engine
