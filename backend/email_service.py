"""Email sending via Resend. Fails silently in local dev when RESEND_API_KEY is unset."""
import logging
import os

logger = logging.getLogger(__name__)

_API_KEY = os.environ.get("RESEND_API_KEY")
_FROM = os.environ.get("RESEND_FROM_EMAIL", "PrintShelf <noreply@printshelf.app>")
_APP_URL = os.environ.get("APP_URL", "https://printshelf.app")


def send_password_reset(to_email: str, token: str) -> bool:
    """Send a password-reset email. Returns True on success, False on failure."""
    if not _API_KEY:
        reset_url = f"{_APP_URL}/reset-password?token={token}"
        logger.warning("RESEND_API_KEY not set — password reset link: %s", reset_url)
        return False

    try:
        import resend
        resend.api_key = _API_KEY
        reset_url = f"{_APP_URL}/reset-password?token={token}"
        resend.Emails.send({
            "from": _FROM,
            "to": [to_email],
            "subject": "Reset your PrintShelf password",
            "html": f"""
<p>Someone requested a password reset for your PrintShelf account.</p>
<p><a href="{reset_url}" style="background:#6c63ff;color:#fff;padding:10px 20px;
border-radius:6px;text-decoration:none;display:inline-block;">Reset password</a></p>
<p>This link expires in 1 hour. If you didn't request this, ignore this email.</p>
<p style="color:#888;font-size:12px;">{reset_url}</p>
""",
        })
        return True
    except Exception:
        logger.exception("Failed to send password reset email to %s", to_email)
        return False


def send_verification_email(to_email: str, token: str) -> bool:
    """Send an email-verification link. Returns True on success, False on failure."""
    if not _API_KEY:
        verify_url = f"{_APP_URL}/verify-email?token={token}"
        logger.warning("RESEND_API_KEY not set — verification link: %s", verify_url)
        return False

    try:
        import resend
        resend.api_key = _API_KEY
        verify_url = f"{_APP_URL}/verify-email?token={token}"
        resend.Emails.send({
            "from": _FROM,
            "to": [to_email],
            "subject": "Verify your PrintShelf email",
            "html": f"""
<p>Thanks for joining PrintShelf! Tap the button below to verify your email address.</p>
<p><a href="{verify_url}" style="background:#ff6a3d;color:#fff;padding:10px 20px;
border-radius:6px;text-decoration:none;display:inline-block;">Verify email</a></p>
<p>This link expires in 24 hours. If you didn't create an account, ignore this email.</p>
<p style="color:#888;font-size:12px;">{verify_url}</p>
""",
        })
        return True
    except Exception:
        logger.exception("Failed to send verification email to %s", to_email)
        return False
