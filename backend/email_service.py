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


def send_follow_notification(to_email: str, follower_username: str, follower_display: str, unsubscribe_token: str) -> bool:
    """Notify a user that someone followed them."""
    if not _API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping follow notification to %s", to_email)
        return False
    try:
        import resend
        resend.api_key = _API_KEY
        profile_url = f"{_APP_URL}/@{follower_username}"
        unsub_url = f"{_APP_URL}/unsubscribe?token={unsubscribe_token}&type=follow"
        resend.Emails.send({
            "from": _FROM,
            "to": [to_email],
            "subject": f"{follower_display} started following you on PrintShelf",
            "html": f"""
<p><a href="{profile_url}">@{follower_username}</a> is now following you on PrintShelf.</p>
<p><a href="{profile_url}" style="background:#6c63ff;color:#fff;padding:10px 20px;
border-radius:6px;text-decoration:none;display:inline-block;">View their profile</a></p>
<p style="color:#888;font-size:12px;margin-top:24px;">
  <a href="{unsub_url}" style="color:#888;">Unsubscribe from follow notifications</a>
</p>
""",
        })
        return True
    except Exception:
        logger.exception("Failed to send follow notification to %s", to_email)
        return False


def send_welcome(to_email: str, username: str) -> bool:
    """Send a welcome email to a newly signed-up user."""
    if not _API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping welcome email to %s", to_email)
        return False
    try:
        import resend
        resend.api_key = _API_KEY
        shelf_url = f"{_APP_URL}/@{username}"
        resend.Emails.send({
            "from": _FROM,
            "to": [to_email],
            "subject": "Welcome to PrintShelf — your shelf is ready",
            "html": f"""
<p>Hey @{username} — your shelf is live.</p>
<p><a href="{shelf_url}" style="background:#ff6a3d;color:#fff;padding:10px 20px;
border-radius:6px;text-decoration:none;display:inline-block;">View your shelf →</a></p>
<p><strong>Quick start:</strong></p>
<ul>
  <li><a href="{_APP_URL}/dashboard/printers/new">Add your printer</a></li>
  <li><a href="{_APP_URL}/dashboard/filaments/new">Log a filament spool</a></li>
  <li><a href="{_APP_URL}/dashboard/prints/new">Log your first print</a></li>
  <li><a href="https://chromewebstore.google.com/detail/printshelf/ffomddhafgccgacapkifpcbgcmphdmkh">Install the Chrome extension</a> — one-click imports from Makerworld, Printables, and more</li>
</ul>
<p style="color:#888;font-size:12px;margin-top:24px;">
  Questions? Reply to this email or find us at <a href="{_APP_URL}" style="color:#888;">printshelf.app</a>.
</p>
""",
        })
        return True
    except Exception:
        logger.exception("Failed to send welcome email to %s", to_email)
        return False


def send_feed_notification(to_email: str, printer_username: str, printer_display: str, print_title: str, print_url: str, unsubscribe_token: str) -> bool:
    """Notify a follower that someone they follow logged a new print."""
    if not _API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping feed notification to %s", to_email)
        return False
    try:
        import resend
        resend.api_key = _API_KEY
        unsub_url = f"{_APP_URL}/unsubscribe?token={unsubscribe_token}&type=feed"
        resend.Emails.send({
            "from": _FROM,
            "to": [to_email],
            "subject": f"{printer_display} logged a new print on PrintShelf",
            "html": f"""
<p><a href="{_APP_URL}/@{printer_username}">@{printer_username}</a> just logged a new print:
<strong>{print_title}</strong></p>
<p><a href="{print_url}" style="background:#ff6a3d;color:#fff;padding:10px 20px;
border-radius:6px;text-decoration:none;display:inline-block;">View print</a></p>
<p style="color:#888;font-size:12px;margin-top:24px;">
  <a href="{unsub_url}" style="color:#888;">Unsubscribe from feed notifications</a>
</p>
""",
        })
        return True
    except Exception:
        logger.exception("Failed to send feed notification to %s", to_email)
        return False
