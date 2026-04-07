import smtplib
import socket
import time
import random
from typing import Optional


def verify_email_smtp(
    email: str,
    smtp_server: str,
    port: int = 25,
    from_address: Optional[str] = None,
    max_retries: int = 4,
    timeout: int = 10,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
    backoff_multiplier: float = 2.0,
    jitter: float = 0.5,
):
    """Attempt SMTP RCPT verification with polite retries and rate-limit handling.

    Returns a dict with keys: `status` (valid|invalid|temporary_failure|rate_limited|timeout|inconclusive),
    `smtp_code`, `smtp_message`, and `attempts`.
    """
    if from_address is None:
        try:
            from_address = f"verify@{socket.gethostname()}"
        except Exception:
            from_address = "verify@local"

    attempt = 0
    backoff = initial_backoff

    while attempt < max_retries:
        attempt += 1
        try:
            with smtplib.SMTP(smtp_server, port, timeout=timeout) as server:
                server.set_debuglevel(0)
                server.ehlo_or_helo_if_needed()
                # some servers require TLS or other negotiation; don't force it here
                try:
                    code_mail, resp_mail = server.mail(from_address)
                except Exception:
                    # some servers don't return a tuple for mail(); ignore and continue
                    code_mail, resp_mail = (None, None)

                rcpt = server.rcpt(email)
                # rcpt may return a tuple (code, message) or raise SMTPResponseException
                if isinstance(rcpt, tuple):
                    code, message = rcpt
                    # normalize message to string
                    message_text = message.decode() if isinstance(message, bytes) else str(message)
                else:
                    # defensive fallback
                    code = None
                    message_text = str(rcpt)

                result = {
                    "smtp_code": code,
                    "smtp_message": message_text,
                    "attempts": attempt,
                }

                # Interpret common SMTP codes
                if code == 250:
                    result["status"] = "valid"
                    return result
                if code in (550, 551, 553):
                    result["status"] = "invalid"
                    return result
                # Temporary failures that usually mean try later / greylisting
                if code in (421, 450, 451, 452):
                    # Distinguish likely rate limiting from transient greylisting by message text
                    lower_msg = (message_text or "").lower()
                    if "rate" in lower_msg or "too many" in lower_msg or "temporarily deferred" in lower_msg:
                        result["status"] = "rate_limited"
                        return result
                    # else treat as temporary failure and retry
                    result["status"] = "temporary_failure"
                    # fall through to retry logic below

                # If we reach here, treat as inconclusive and retry if attempts left
                if attempt >= max_retries:
                    result["status"] = "inconclusive"
                    return result

        except (socket.timeout,) as e:
            # connection-level timeout
            if attempt >= max_retries:
                return {
                    "status": "timeout",
                    "smtp_code": None,
                    "smtp_message": str(e),
                    "attempts": attempt,
                }
            # backoff and retry
            sleep_for = min(max_backoff, backoff) + random.uniform(0, jitter)
            print(f"SMTP timeout (attempt {attempt}/{max_retries}), sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)
            backoff *= backoff_multiplier
            continue
        except smtplib.SMTPResponseException as e:
            code = getattr(e, 'smtp_code', None)
            message_text = getattr(e, 'smtp_error', b'').decode() if getattr(e, 'smtp_error', None) else str(e)
            # handle rate-limit-like codes
            if code in (421, 450, 451, 452):
                lower_msg = (message_text or "").lower()
                if "rate" in lower_msg or "too many" in lower_msg:
                    return {"status": "rate_limited", "smtp_code": code, "smtp_message": message_text, "attempts": attempt}
                # otherwise treat as temporary failure and retry
                if attempt >= max_retries:
                    return {"status": "temporary_failure", "smtp_code": code, "smtp_message": message_text, "attempts": attempt}
                sleep_for = min(max_backoff, backoff) + random.uniform(0, jitter)
                print(f"SMTP temporary error {code} (attempt {attempt}/{max_retries}), sleeping {sleep_for:.1f}s")
                time.sleep(sleep_for)
                backoff *= backoff_multiplier
                continue
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as e:
            if attempt >= max_retries:
                return {"status": "inconclusive", "smtp_code": None, "smtp_message": str(e), "attempts": attempt}
            sleep_for = min(max_backoff, backoff) + random.uniform(0, jitter)
            print(f"SMTP connection error (attempt {attempt}/{max_retries}): {e}, sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)
            backoff *= backoff_multiplier
            continue
        except Exception as e:
            return {"status": "inconclusive", "smtp_code": None, "smtp_message": str(e), "attempts": attempt}

        # If we get here due to temporary_failure from an rcpt response tuple, backoff and retry
        sleep_for = min(max_backoff, backoff) + random.uniform(0, jitter)
        print(f"SMTP temporary response, retrying (attempt {attempt}/{max_retries}) after {sleep_for:.1f}s")
        time.sleep(sleep_for)
        backoff *= backoff_multiplier

    # final fallback
    return {"status": "inconclusive", "smtp_code": None, "smtp_message": "Max retries exceeded", "attempts": attempt}