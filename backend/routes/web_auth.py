"""Web UI auth: signup, login, logout, plus a dashboard stub.

Cookie-based session — JWT same as the API uses, but stored in an HttpOnly
SameSite=Lax cookie so the browser carries it on every request without JS.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from auth import (
    SESSION_COOKIE_NAME,
    USERNAME_RE,
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user_web_optional,
    hash_password,
)
from email_service import send_password_reset, send_verification_email, send_welcome
from models import EmailVerificationToken, Filament, PasswordResetToken, Print, Printer, User, generate_api_key, get_db, slugify
import rate_limiter

_log = logging.getLogger(__name__)

router = APIRouter(tags=["web-auth"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))

_PROD = os.environ.get("APP_ENV", "development") in {"production", "staging"}
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days, matches JWT expiry


def _send_verification(db: Session, user: User) -> None:
    """Create a fresh verification token and send the email. Silent on failure."""
    from datetime import timedelta
    token = secrets.token_urlsafe(48)[:64]
    record = EmailVerificationToken(
        token=token,
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(record)
    db.commit()
    send_verification_email(user.email, token)


def _set_session_cookie(response: RedirectResponse, user_id: int) -> None:
    token = create_access_token(user_id, expires_delta=timedelta(days=30))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=_PROD,
        samesite="lax",
        path="/",
    )


# ---- Signup ----

@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, user: Optional[User] = Depends(get_current_user_web_optional)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"errors": [], "values": {}, "current_user": None})


@router.post("/signup")
def signup_submit(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    display_name: str = Form(""),
    db: Session = Depends(get_db),
):
    ip = rate_limiter.client_ip(request)
    if not rate_limiter.check(ip, "signup", max_attempts=5, window_secs=300):
        raise HTTPException(status_code=429, detail="Too many signup attempts. Try again in a few minutes.")
    values = {"email": email, "username": username, "display_name": display_name}
    errors: list[str] = []

    if password != password_confirm:
        errors.append("Passwords don't match.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if not USERNAME_RE.match(username.strip()):
        errors.append("Username must be 3-30 chars: letters, numbers, underscore, dash.")

    if errors:
        return templates.TemplateResponse(
            request, "signup.html", {"errors": errors, "values": values, "current_user": None}, status_code=400
        )

    try:
        new_user = create_user(
            db,
            email=email,
            password=password,
            username=username,
            display_name=display_name or None,
        )
    except Exception as exc:
        # create_user raises HTTPException(409) for duplicates
        msg = getattr(exc, "detail", str(exc))
        errors.append(str(msg))
        return templates.TemplateResponse(
            request, "signup.html", {"errors": errors, "values": values, "current_user": None}, status_code=400
        )

    _send_verification(db, new_user)
    send_welcome(new_user.email, new_user.username)
    response = RedirectResponse("/dashboard", status_code=303)
    _set_session_cookie(response, new_user.id)
    return response


# ---- Login ----

@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    next: str = "/dashboard",
    user: Optional[User] = Depends(get_current_user_web_optional),
):
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/dashboard"
    if user:
        return RedirectResponse(safe_next, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"errors": [], "values": {}, "next": safe_next, "current_user": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    ip = rate_limiter.client_ip(request)
    if not rate_limiter.check(ip, "login", max_attempts=10, window_secs=300):
        return templates.TemplateResponse(
            request, "login.html",
            {"errors": ["Too many login attempts. Try again in a few minutes."], "values": {"email": email}, "next": next, "current_user": None},
            status_code=429,
        )
    user = authenticate_user(db, email, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "errors": ["Email or password is wrong."],
                "values": {"email": email},
                "next": next,
                "current_user": None,
            },
            status_code=400,
        )

    # Restrict redirect target to local paths (no open-redirect)
    target = next if next.startswith("/") and not next.startswith("//") else "/dashboard"
    response = RedirectResponse(target, status_code=303)
    _set_session_cookie(response, user.id)
    return response


# ---- Logout ----

@router.post("/logout")
def logout_submit():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


# ---- Google OAuth ----

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_OAUTH_STATE_COOKIE = "g_oauth_state"


def _google_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


# Expose to login/signup templates without threading it through every context.
templates.env.globals["google_login_enabled"] = _google_configured


def _google_redirect_uri() -> str:
    base = os.environ.get("APP_URL", "https://printshelf.app").rstrip("/")
    return f"{base}/auth/google/callback"


def _safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/dashboard"


def _unique_username(db: Session, base: str) -> str:
    """A valid, unique username (USERNAME_RE: 3-30 [a-zA-Z0-9_-]) from a name/email."""
    slug = (slugify(base) or "maker")[:30]
    if len(slug) < 3:
        slug = (slug + "maker")[:30]
    candidate = slug
    while db.query(User).filter(User.username.ilike(candidate)).first() is not None:
        candidate = f"{slug[:25]}-{secrets.token_hex(2)}"
    return candidate


def _find_or_create_google_user(db: Session, sub: str, email: str, name: Optional[str], picture: Optional[str]) -> User:
    # 1) Known Google account.
    user = db.query(User).filter(User.google_sub == sub).first()
    if user:
        user.last_login = datetime.utcnow()
        db.commit()
        return user
    # 2) Existing account with the same (Google-verified) email → link.
    user = db.query(User).filter(User.email == email).first()
    if user:
        if not user.google_sub:
            user.google_sub = sub
        if not user.avatar_url and picture:
            user.avatar_url = picture[:500]
        user.last_login = datetime.utcnow()
        db.commit()
        return user
    # 3) New account. Random unusable password (they log in via Google; can reset later).
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        username=_unique_username(db, name or email.split("@")[0]),
        api_key=generate_api_key(),
        tier="free",
        unsubscribe_token=secrets.token_hex(16),
        email_verified=True,
        google_sub=sub,
        avatar_url=(picture or None) and picture[:500],
        last_login=datetime.utcnow(),
    )
    user.display_name = (name or user.username).strip()[:100]
    db.add(user)
    db.commit()
    db.refresh(user)
    try:
        send_welcome(user.email, user.username)
    except Exception:
        _log.warning("send_welcome failed for google signup user_id=%s", user.id)
    return user


@router.get("/auth/google/login")
def google_login(request: Request, next: str = "/dashboard"):
    if not _google_configured():
        return RedirectResponse("/login", status_code=303)
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(GOOGLE_AUTH_URL + "?" + urlencode(params), status_code=303)
    # CSRF: stash state (+ desired post-login target) in a short-lived HttpOnly cookie.
    resp.set_cookie(
        _OAUTH_STATE_COOKIE, f"{state}|{_safe_next(next)}",
        max_age=600, httponly=True, secure=_PROD, samesite="lax", path="/",
    )
    return resp


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    def _fail(reason: str):
        _log.warning("google oauth callback failed: %s", reason)
        r = RedirectResponse("/login?oauth_error=1", status_code=303)
        r.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
        return r

    if not _google_configured():
        return RedirectResponse("/login", status_code=303)

    cookie_state, _, next_target = request.cookies.get(_OAUTH_STATE_COOKIE, "").partition("|")
    next_target = _safe_next(next_target or "/dashboard")
    if error or not code or not state or not cookie_state or state != cookie_state:
        return _fail("state/params")

    try:
        with httpx.Client(timeout=10) as client:
            tok = client.post(GOOGLE_TOKEN_URL, data={
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _google_redirect_uri(),
            })
            if tok.status_code != 200:
                return _fail(f"token {tok.status_code}")
            access_token = tok.json().get("access_token")
            if not access_token:
                return _fail("no access_token")
            ui = client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            if ui.status_code != 200:
                return _fail(f"userinfo {ui.status_code}")
            info = ui.json()
    except Exception as exc:
        return _fail(f"exception {exc!r}")

    sub = info.get("sub")
    email = (info.get("email") or "").strip().lower()
    if not sub or not email or not info.get("email_verified", False):
        return _fail("missing sub/email/unverified")

    user = _find_or_create_google_user(db, sub, email, info.get("name"), info.get("picture"))
    resp = RedirectResponse(next_target, status_code=303)
    _set_session_cookie(resp, user.id)
    resp.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    _log.info("google oauth login user_id=%s", user.id)
    return resp


# ---- Forgot password ----

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_form(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html", {"sent": False, "current_user": None})


@router.post("/forgot-password")
def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = rate_limiter.client_ip(request)
    if not rate_limiter.check(ip, "forgot-password", max_attempts=5, window_secs=300):
        return templates.TemplateResponse(request, "forgot_password.html", {"sent": True, "current_user": None})
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if user:
        token = secrets.token_urlsafe(48)[:64]
        reset = PasswordResetToken(
            token=token,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(reset)
        db.commit()
        send_password_reset(user.email, token)

    # Always show "check your email" — don't leak whether address exists
    return templates.TemplateResponse(request, "forgot_password.html", {"sent": True, "current_user": None})


# ---- Reset password ----

@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_form(request: Request, token: str = ""):
    record = _valid_token(token, db=next(get_db()))
    if not record:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"token": token, "invalid": True, "errors": [], "current_user": None},
        )
    return templates.TemplateResponse(
        request, "reset_password.html",
        {"token": token, "invalid": False, "errors": [], "current_user": None},
    )


@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    record = _valid_token(token, db)
    if not record:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"token": token, "invalid": True, "errors": [], "current_user": None},
            status_code=400,
        )

    errors: list[str] = []
    if password != password_confirm:
        errors.append("Passwords don't match.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")

    if errors:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"token": token, "invalid": False, "errors": errors, "current_user": None},
            status_code=400,
        )

    record.user.password_hash = hash_password(password)
    record.used_at = datetime.utcnow()
    db.commit()

    return RedirectResponse("/login?reset=1", status_code=303)


def _valid_token(token: str, db: Session) -> Optional[PasswordResetToken]:
    if not token:
        return None
    record = db.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()
    if not record:
        return None
    if record.used_at is not None:
        return None
    if record.expires_at < datetime.utcnow():
        return None
    return record


# ---- Email verification ----

@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(
    request: Request,
    token: str = "",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    if not token:
        return RedirectResponse("/dashboard", status_code=303)
    record = db.query(EmailVerificationToken).filter(
        EmailVerificationToken.token == token
    ).first()
    if not record or record.used_at is not None:
        return templates.TemplateResponse(
            request, "verify_email.html",
            {"state": "invalid", "current_user": current_user},
            status_code=400,
        )
    if record.expires_at < datetime.utcnow():
        return templates.TemplateResponse(
            request, "verify_email.html",
            {"state": "expired", "current_user": current_user},
            status_code=400,
        )
    record.user.email_verified = True
    record.used_at = datetime.utcnow()
    db.commit()
    return templates.TemplateResponse(
        request, "verify_email.html",
        {"state": "success", "current_user": record.user},
    )


@router.post("/resend-verification")
def resend_verification(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=303)
    if current_user.email_verified:
        return RedirectResponse("/dashboard", status_code=303)
    ip = rate_limiter.client_ip(request)
    if not rate_limiter.check(ip, "resend-verification", max_attempts=3, window_secs=300):
        return RedirectResponse("/dashboard?resend=limited", status_code=303)
    _send_verification(db, current_user)
    return RedirectResponse("/dashboard?resend=sent", status_code=303)


# ---- Unsubscribe ----

@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    request: Request,
    token: str = "",
    type: str = "",
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.unsubscribe_token == token).first() if token else None
    if not user or type not in ("follow", "feed"):
        return templates.TemplateResponse(request, "unsubscribe.html", {"state": "invalid", "current_user": None})
    if type == "follow":
        user.notify_follow = False
    else:
        user.notify_feed = False
    db.commit()
    return templates.TemplateResponse(request, "unsubscribe.html", {"state": "success", "type": type, "current_user": None})


# ---- Dashboard stub (real CRUD UI in Task #11) ----

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    resend: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login?next=/dashboard", status_code=303)
    total_prints = db.query(Print).filter(Print.user_id == user.id, Print.queued == False).count()  # noqa: E712
    queued = db.query(Print).filter(Print.user_id == user.id, Print.queued == True).count()  # noqa: E712
    success = db.query(Print).filter(Print.user_id == user.id, Print.queued == False, Print.status == "printed").count()  # noqa: E712
    filaments_count = db.query(Filament).filter(Filament.user_id == user.id).count()
    printers = db.query(Printer).filter(Printer.user_id == user.id).count()

    # Estimated total filament spend — one query for all filaments, then iterate prints
    all_prints = db.query(Print).filter(Print.user_id == user.id, Print.queued == False, Print.filament_used_g.isnot(None)).all()  # noqa: E712
    all_filaments = db.query(Filament).filter(Filament.user_id == user.id, Filament.price_at_save.isnot(None), Filament.spool_weight_g.isnot(None)).all()
    fil_by_id = {f.id: f for f in all_filaments}
    total_spend: float = 0.0
    for p in all_prints:
        if p.filament_ids:
            fils = [fil_by_id[fid] for fid in p.filament_ids if fid in fil_by_id]
            if fils:
                cost_per_g = sum(f.price_at_save / f.spool_weight_g for f in fils) / len(fils)
                total_spend += p.filament_used_g * cost_per_g

    stats = {
        "total_prints": total_prints,
        "queued": queued,
        "success_pct": round((success / total_prints) * 100) if total_prints > 0 else 0,
        "filaments": filaments_count,
        "printers": printers,
        "total_spend": round(total_spend, 2) if total_spend else None,
        "profile_views": user.profile_views,
    }
    resend_notice = None
    if resend == "sent":
        resend_notice = "Verification email sent — check your inbox."
    elif resend == "limited":
        resend_notice = "Too many resend requests. Try again in a few minutes."
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "current_user": user,
        "stats": stats,
        "sidebar_prints": total_prints,
        "sidebar_queue": queued,
        "sidebar_filaments": filaments_count,
        "resend_notice": resend_notice,
    })
