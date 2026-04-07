"""Structured logging configuration with JSON formatter and email hash sanitization."""

import logging
import logging.config
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
from app.config import settings


class EmailSanitizingFormatter(logging.Formatter):
    """Custom formatter that sanitizes email addresses in log messages."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def format(self, record):
        # Sanitize email addresses in the message
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = self._sanitize_emails(record.msg)
        
        # Sanitize email addresses in args
        if hasattr(record, 'args') and record.args:
            sanitized_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    sanitized_args.append(self._sanitize_emails(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        
        return super().format(record)
    
    def _sanitize_emails(self, text: str) -> str:
        """Replace email addresses with hashed versions for privacy."""
        import re
        
        # Simple email regex
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        
        def hash_email(match):
            email = match.group(0)
            # Hash the localpart, keep domain for debugging
            if '@' in email:
                localpart, domain = email.split('@', 1)
                hashed_local = hashlib.sha256(localpart.encode()).hexdigest()[:8]
                return f"{hashed_local}@{domain}"
            return email
        
        return re.sub(email_pattern, hash_email, text)


class JSONFormatter(EmailSanitizingFormatter):
    """JSON formatter for structured logging."""
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add extra fields if present
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        
        if hasattr(record, 'job_id'):
            log_entry['job_id'] = record.job_id
        
        if hasattr(record, 'email_hash'):
            log_entry['email_hash'] = record.email_hash
        
        if hasattr(record, 'domain'):
            log_entry['domain'] = record.domain
        
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


def setup_logging():
    """Setup logging configuration."""
    
    # Determine log level
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Configure logging
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'json': {
                '()': JSONFormatter,
            },
            'standard': {
                '()': EmailSanitizingFormatter,
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': log_level,
                'formatter': 'json' if settings.app_env == 'prod' else 'standard',
                'stream': 'ext://sys.stdout'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': log_level,
                'formatter': 'json',
                'filename': 'data/app.log',
                'maxBytes': 10485760,  # 10MB
                'backupCount': 5
            }
        },
        'loggers': {
            'app': {
                'level': log_level,
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'uvicorn': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'rq': {
                'level': 'INFO',
                'handlers': ['console', 'file'],
                'propagate': False
            }
        },
        'root': {
            'level': log_level,
            'handlers': ['console']
        }
    }
    
    # Create data directory if it doesn't exist
    import os
    os.makedirs('data', exist_ok=True)
    
    logging.config.dictConfig(logging_config)


class LogContext:
    """Context manager for adding structured logging context."""
    
    def __init__(self, **kwargs):
        self.context = kwargs
        self.old_factory = None
    
    def __enter__(self):
        self.old_factory = logging.getLogRecordFactory()
        
        def record_factory(*args, **kwargs):
            if self.old_factory is None:
                raise RuntimeError("No previous log record factory")
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, key, value)
            return record
        
        logging.setLogRecordFactory(record_factory)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.old_factory is not None:
            logging.setLogRecordFactory(self.old_factory)


def get_logger(name: str) -> logging.Logger:
    """Get logger with app prefix."""
    return logging.getLogger(f"app.{name}")


def log_verification_start(email: str, request_id: Optional[str] = None):
    """Log verification start with context."""
    logger = get_logger("verification")
    
    # Hash email for privacy
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    domain = email.split('@')[1] if '@' in email else 'unknown'
    
    with LogContext(request_id=request_id, email_hash=email_hash, domain=domain):
        logger.info(f"Starting verification for domain {domain}")


def log_verification_complete(
    email: str, 
    status: str, 
    duration_ms: int,
    request_id: Optional[str] = None
):
    """Log verification completion with context."""
    logger = get_logger("verification")
    
    # Hash email for privacy
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    domain = email.split('@')[1] if '@' in email else 'unknown'
    
    with LogContext(
        request_id=request_id, 
        email_hash=email_hash, 
        domain=domain,
        duration_ms=duration_ms
    ):
        logger.info(f"Verification completed: {status} ({duration_ms}ms)")


def log_job_progress(job_id: str, processed: int, total: int, stats: Dict[str, int]):
    """Log job progress with context."""
    logger = get_logger("jobs")
    
    percentage = (processed / total * 100) if total > 0 else 0
    
    with LogContext(job_id=job_id):
        logger.info(
            f"Job progress: {processed}/{total} ({percentage:.1f}%) - "
            f"deliverable: {stats.get('deliverable_count', 0)}, "
            f"invalid: {stats.get('invalid_count', 0)}"
        )


def log_api_request(method: str, path: str, status_code: int, duration_ms: int, request_id: Optional[str] = None):
    """Log API request with context."""
    logger = get_logger("api")
    
    with LogContext(request_id=request_id, duration_ms=duration_ms):
        logger.info(f"{method} {path} - {status_code} ({duration_ms}ms)")


def log_error_with_context(logger_name: str, message: str, error: Exception, **context):
    """Log error with additional context."""
    logger = get_logger(logger_name)
    
    with LogContext(**context):
        logger.error(f"{message}: {str(error)}", exc_info=True)


# Audit logging for security events
def log_audit_event(event_type: str, details: Dict[str, Any], user_id: Optional[str] = None):
    """Log security/audit events."""
    logger = get_logger("audit")
    
    audit_entry = {
        'event_type': event_type,
        'timestamp': datetime.utcnow().isoformat(),
        'details': details
    }
    
    if user_id:
        audit_entry['user_id'] = user_id
    
    logger.info(f"Audit event: {event_type}", extra=audit_entry)