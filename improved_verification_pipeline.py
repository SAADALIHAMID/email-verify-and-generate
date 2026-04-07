"""
Improved Email Verification Pipeline
7-Step verification process with proper handling of all email types
Does NOT block role-based addresses - just marks them as RISKY if unverified
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum


class VerificationLevel(Enum):
    """Verification confidence levels"""
    CONFIRMED = "confirmed"      # SMTP accepted
    LIKELY_VALID = "likely_valid"  # Multiple signals agree
    POSSIBLE = "possible"          # Some signals good, some unknown
    UNCERTAIN = "uncertain"        # Few signals, mostly unknown
    LIKELY_INVALID = "likely_invalid"  # Multiple signals negative
    INVALID = "invalid"            # Confirmed invalid


@dataclass
class VerificationStep:
    """Result from a verification step"""
    number: int
    name: str
    passed: bool
    score: int
    details: str
    confidence: float  # 0.0 to 1.0


class ImprovedVerificationPipeline:
    """
    7-Step Email Verification Pipeline
    
    NEVER BLOCKS emails unnecessarily
    All steps are INFORMATIONAL - higher steps provide confidence
    """
    
    def __init__(self):
        self.steps: List[VerificationStep] = []
    
    def verify_email_comprehensive(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run comprehensive 7-step verification
        
        Args:
            signals: Verification signals from backend
        
        Returns:
            Comprehensive verification result
        """
        
        email = signals.get('email', '')
        self.steps = []
        
        # STEP 1: Syntax Validation
        step1 = self._step1_syntax_check(email, signals)
        self.steps.append(step1)
        
        # STEP 2: Domain Validation
        step2 = self._step2_domain_mx_check(email, signals)
        self.steps.append(step2)
        
        # STEP 3: Role-Based Detection
        step3 = self._step3_role_based_check(email, signals)
        self.steps.append(step3)
        
        # STEP 4: Disposable Domain Check
        step4 = self._step4_disposable_check(email, signals)
        self.steps.append(step4)
        
        # STEP 5: SMTP Verification
        step5 = self._step5_smtp_check(email, signals)
        self.steps.append(step5)
        
        # STEP 6: Catch-All Detection
        step6 = self._step6_catch_all_check(email, signals)
        self.steps.append(step6)
        
        # STEP 7: Final Assessment
        step7 = self._step7_final_assessment(email, signals)
        self.steps.append(step7)
        
        return self._compile_results(email, signals)
    
    def _step1_syntax_check(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 1: SYNTAX CHECK (Basic – Must Have)
        Check email format using regex.
        """
        
        valid_syntax = signals.get('valid_syntax', False)
        
        if valid_syntax:
            return VerificationStep(
                number=1,
                name="Email Syntax Validation",
                passed=True,
                score=10,
                details=f"✅ {email} has valid email format",
                confidence=1.0
            )
        else:
            return VerificationStep(
                number=1,
                name="Email Syntax Validation",
                passed=False,
                score=0,
                details=f"❌ {email} has invalid email format",
                confidence=1.0
            )
    
    def _step2_domain_mx_check(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 2: DOMAIN CHECK (DNS + MX RECORD)
        Check whether the domain can receive email.
        """
        
        has_mx = signals.get('has_mx', False)
        mx_records = signals.get('mx_records', [])
        
        if has_mx:
            mx_text = ", ".join(mx_records) if mx_records else "MX records found"
            return VerificationStep(
                number=2,
                name="Domain/MX Records Validation",
                passed=True,
                score=20,
                details=f"✅ Domain has valid MX records: {mx_text}",
                confidence=1.0
            )
        else:
            return VerificationStep(
                number=2,
                name="Domain/MX Records Validation",
                passed=False,
                score=0,
                details=f"❌ Domain has no MX records (cannot receive email)",
                confidence=1.0
            )
    
    def _step3_role_based_check(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 3: ROLE-BASED EMAIL CHECK (VERY IMPORTANT)
        Use a role keyword list and check the local part.
        
        NOTE: Role-based emails are NOT blocked, just marked for caution
        """
        
        is_role_based = signals.get('is_role_based', False)
        
        if not is_role_based:
            return VerificationStep(
                number=3,
                name="Role-Based Detection",
                passed=True,
                score=20,
                details=f"✅ {email} appears to be a personal mailbox (not generic role)",
                confidence=0.9
            )
        else:
            # IMPORTANT: Role-based is NOT a hard fail!
            # Just means we should be more cautious
            local_part = email.split('@')[0].lower() if '@' in email else ''
            
            return VerificationStep(
                number=3,
                name="Role-Based Detection",
                passed=False,
                score=10,  # Still get some points
                details=f"⚠️ {email} is role-based address ({local_part}@...) - common mailbox like info@, admin@, support@, etc.",
                confidence=0.5
            )
    
    def _step4_disposable_check(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 4: DISPOSABLE / TEMP EMAIL CHECK
        Block temp email providers.
        """
        
        is_disposable = signals.get('is_disposable', False)
        
        if not is_disposable:
            return VerificationStep(
                number=4,
                name="Disposable Domain Check",
                passed=True,
                score=20,
                details=f"✅ {email} is from a legitimate domain (not temporary/disposable)",
                confidence=1.0
            )
        else:
            return VerificationStep(
                number=4,
                name="Disposable Domain Check",
                passed=False,
                score=0,
                details=f"❌ {email} is from a disposable/temporary email service",
                confidence=1.0
            )
    
    def _step5_smtp_check(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 5: SMTP HANDSHAKE CHECK (ADVANCED)
        Most important for deliverability.
        """
        
        smtp_accepted = signals.get('smtp_accepted', False)
        is_webmail = signals.get('is_webmail', False)
        has_mx = signals.get('has_mx', False)
        valid_syntax = signals.get('valid_syntax', False)
        smtp_timeout = signals.get('smtp_timeout', False)
        smtp_tempfail = signals.get('smtp_tempfail', False)
        
        if smtp_accepted:
            return VerificationStep(
                number=5,
                name="SMTP Verification",
                passed=True,
                score=20,
                details=f"✅ SMTP server accepted {email} - Email is deliverable",
                confidence=1.0
            )
        
        elif is_webmail and valid_syntax and has_mx:
            # Webmail providers often return uncertain results
            return VerificationStep(
                number=5,
                name="SMTP Verification",
                passed=True,
                score=15,
                details=f"✅ Webmail provider ({email}) with valid syntax and MX records - Likely deliverable despite SMTP uncertainty",
                confidence=0.8
            )
        
        elif smtp_timeout and has_mx and valid_syntax:
            # Timeout might mean server is rate limiting or overloaded
            return VerificationStep(
                number=5,
                name="SMTP Verification",
                passed=True,
                score=10,
                details=f"⚠️ SMTP verification timed out for {email} - Server may be rate limiting. MX records exist, syntax valid - Likely deliverable",
                confidence=0.6
            )
        
        elif smtp_tempfail and has_mx:
            # Temporary failure might resolve later
            return VerificationStep(
                number=5,
                name="SMTP Verification",
                passed=False,
                score=5,
                details=f"⚠️ SMTP temporary failure for {email} - Try again later, may be greylist or rate limit",
                confidence=0.4
            )
        
        else:
            # SMTP rejected or no response
            return VerificationStep(
                number=5,
                name="SMTP Verification",
                passed=False,
                score=0,
                details=f"❌ SMTP server rejected {email} or could not verify",
                confidence=0.2
            )
    
    def _step6_catch_all_check(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 6: CATCH-ALL DOMAIN DETECTION
        Some domains accept any email.
        """
        
        is_catch_all = signals.get('is_catch_all', False)
        
        if not is_catch_all:
            return VerificationStep(
                number=6,
                name="Catch-All Domain Detection",
                passed=True,
                score=0,  # Neutral score
                details=f"✅ Domain does NOT accept all emails (not catch-all)",
                confidence=0.8
            )
        else:
            return VerificationStep(
                number=6,
                name="Catch-All Domain Detection",
                passed=False,
                score=-10,  # Penalty
                details=f"⚠️ Domain accepts all emails (catch-all) - Email may not actually exist",
                confidence=0.5
            )
    
    def _step7_final_assessment(self, email: str, signals: Dict[str, Any]) -> VerificationStep:
        """
        STEP 7: FINAL ASSESSMENT
        Compile all signals into final recommendation.
        """
        
        # Calculate total score from all steps
        total_score = sum(step.score for step in self.steps)
        
        if total_score >= 80:
            return VerificationStep(
                number=7,
                name="Final Assessment",
                passed=True,
                score=total_score,
                details=f"✅ HIGH CONFIDENCE - Email is valid and deliverable. Score: {total_score}/100",
                confidence=0.95
            )
        elif total_score >= 60:
            return VerificationStep(
                number=7,
                name="Final Assessment",
                passed=True,
                score=total_score,
                details=f"⚠️ MODERATE CONFIDENCE - Email is likely valid but has some risk factors. Score: {total_score}/100",
                confidence=0.70
            )
        else:
            return VerificationStep(
                number=7,
                name="Final Assessment",
                passed=False,
                score=total_score,
                details=f"❌ LOW CONFIDENCE - Email validity uncertain or invalid. Score: {total_score}/100",
                confidence=0.40
            )
    
    def _compile_results(self, email: str, signals: Dict[str, Any]) -> Dict[str, Any]:
        """Compile all verification steps into final result"""
        
        total_score = sum(step.score for step in self.steps)
        
        return {
            'email': email,
            'verification_steps': [
                {
                    'step': step.number,
                    'name': step.name,
                    'passed': step.passed,
                    'score': step.score,
                    'details': step.details,
                    'confidence': step.confidence
                }
                for step in self.steps
            ],
            'summary': {
                'total_score': total_score,
                'max_score': 100,
                'confidence': self._calculate_overall_confidence(),
                'classification': self._classify_result(total_score),
                'recommendation': self._get_recommendation(total_score)
            },
            'signals_summary': {
                'syntax_valid': signals.get('valid_syntax', False),
                'has_mx': signals.get('has_mx', False),
                'smtp_accepted': signals.get('smtp_accepted', False),
                'role_based': signals.get('is_role_based', False),
                'disposable': signals.get('is_disposable', False),
                'catch_all': signals.get('is_catch_all', False),
                'webmail': signals.get('is_webmail', False)
            }
        }
    
    def _calculate_overall_confidence(self) -> str:
        """Calculate overall confidence level"""
        
        if not self.steps:
            return "0%"
        
        avg_confidence = sum(step.confidence for step in self.steps) / len(self.steps)
        return f"{avg_confidence * 100:.1f}%"
    
    def _classify_result(self, score: int) -> str:
        """Classify result based on score"""
        
        if score >= 80:
            return "DELIVERABLE"
        elif score >= 60:
            return "RISKY"
        else:
            return "INVALID"
    
    def _get_recommendation(self, score: int) -> str:
        """Get recommendation based on score"""
        
        if score >= 85:
            return "✅ SAFE - Email is valid and deliverable. Safe to send."
        elif score >= 80:
            return "✅ VALID - Email is likely valid and deliverable."
        elif score >= 75:
            return "⚠️ CAUTION - Email may be valid but has risk factors. Test before bulk send."
        elif score >= 60:
            return "⚠️ RISKY - Email validity uncertain. High bounce risk for cold emails."
        elif score >= 40:
            return "❌ INVALID - Email is likely invalid or not deliverable."
        else:
            return "❌ REJECT - Email is invalid and should not be used."
