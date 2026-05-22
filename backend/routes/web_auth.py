"""Web UI auth: signup, login, logout, plus a dashboard stub.

Cookie-based session — JWT same as the API uses, but stored in an HttpOnly
SameSite=Lax cookie so the browser carries it on every request without JS.
"""
import os
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
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
)
from models import User, get_db

router = APIRouter(tags=["web-auth"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))

_PROD = os.environ.get("APP_ENV", "development") in {"production", "staging"}
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days, matches JWT expiry


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
    if user:
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"errors": [], "values": {}, "next": next, "current_user": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
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


# ---- Dashboard stub (real CRUD UI in Task #11) ----

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: Optional[User] = Depends(get_current_user_web_optional)):
    if user is None:
        return RedirectResponse("/login?next=/dashboard", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "current_user": user})
