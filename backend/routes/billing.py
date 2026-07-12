"""Stripe billing — Checkout, Customer Portal, and webhook handler."""
import logging
import os
from typing import Optional

import httpx
import stripe
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import filament_preview_enabled, get_current_user_web_optional, instruments_index_enabled
from models import User, get_db

router = APIRouter(tags=["billing"])

_log = logging.getLogger(__name__)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))
# Shared dashboard layout calls this; register on this instance (renders upgrade pages).
templates.env.globals["filament_preview_enabled"] = filament_preview_enabled
templates.env.globals["instruments_index_enabled"] = instruments_index_enabled

_APP_URL = os.environ.get("APP_URL", "https://printshelf.app")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY = os.environ.get("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_ANNUAL = os.environ.get("STRIPE_PRICE_ANNUAL", "")


def _stripe():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured.")
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


# ---- Upgrade page ----

@router.get("/dashboard/upgrade", response_class=HTMLResponse)
def upgrade_page(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login?next=/dashboard/upgrade", status_code=303)
    if (current_user.tier or "free") == "pro":
        return RedirectResponse("/dashboard/account#billing", status_code=303)
    return templates.TemplateResponse(request, "dashboard/upgrade.html", {
        "current_user": current_user,
        "user": current_user,
        "monthly_price": "4.99",
        "annual_price": "39",
        "annual_monthly_equiv": "3.25",
    })


# ---- Checkout ----

@router.post("/dashboard/billing/checkout")
def create_checkout(
    request: Request,
    plan: str = Form(...),  # "monthly" or "annual"
    current_user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login?next=/dashboard/upgrade", status_code=303)
    s = _stripe()

    price_id = STRIPE_PRICE_MONTHLY if plan == "monthly" else STRIPE_PRICE_ANNUAL
    if not price_id:
        raise HTTPException(status_code=503, detail="Billing price not configured.")

    # Reuse existing Stripe customer if we have one
    customer_kwargs = {}
    if current_user.stripe_customer_id:
        customer_kwargs["customer"] = current_user.stripe_customer_id
    else:
        customer_kwargs["customer_email"] = current_user.email

    session = s.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{_APP_URL}/dashboard/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{_APP_URL}/dashboard/upgrade",
        metadata={"user_id": str(current_user.id)},
        subscription_data={"metadata": {"user_id": str(current_user.id)}},
        **customer_kwargs,
    )
    return RedirectResponse(session.url, status_code=303)


# ---- Success landing ----

@router.get("/dashboard/billing/success")
def billing_success(
    request: Request,
    session_id: str = "",
    current_user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    _log.info("billing_success hit session_id=%r user=%s", session_id, current_user.id if current_user else None)
    debug_error: Optional[str] = None

    if not session_id:
        return templates.TemplateResponse(request, "dashboard/upgrade_success.html", {
            "current_user": current_user, "user": current_user, "debug_error": "no session_id",
        })

    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        _log.error("billing_success: STRIPE_SECRET_KEY not set")
        return templates.TemplateResponse(request, "dashboard/upgrade_success.html", {
            "current_user": current_user, "user": current_user, "debug_error": "STRIPE_SECRET_KEY not configured",
        })

    try:
        # Use httpx directly — bypasses any Stripe SDK v8 compatibility issues
        resp = httpx.get(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
            auth=(stripe_key, ""),
            timeout=10.0,
        )
        resp.raise_for_status()
        cs = resp.json()
        payment_status = cs.get("payment_status")
        status = cs.get("status")
        _log.info("billing_success cs.status=%s cs.payment_status=%s", status, payment_status)

        if status == "complete" and payment_status == "paid":
            meta_user_id = int((cs.get("metadata") or {}).get("user_id", 0))
            _log.info("billing_success meta_user_id=%s", meta_user_id)
            if meta_user_id:
                target = db.query(User).filter(User.id == meta_user_id).first()
                _log.info("billing_success target_id=%s tier=%s", target.id if target else None, target.tier if target else None)
                if target and target.tier != "pro":
                    target.tier = "pro"
                    if cs.get("customer"):
                        target.stripe_customer_id = cs["customer"]
                    if cs.get("subscription"):
                        target.stripe_subscription_id = cs["subscription"]
                    db.commit()
                    _log.info("billing_success upgraded user_id=%s to pro session=%s", meta_user_id, session_id)
                    return RedirectResponse("/dashboard/account#billing", status_code=303)
                debug_error = f"target tier already={target.tier if target else 'not found'}"
        else:
            debug_error = f"unexpected state: status={status} payment_status={payment_status}"
            _log.warning("billing_success %s", debug_error)
    except Exception as exc:
        debug_error = str(exc)
        _log.error("billing_success error session=%s: %s", session_id, exc, exc_info=True)

    return templates.TemplateResponse(request, "dashboard/upgrade_success.html", {
        "current_user": current_user, "user": current_user, "debug_error": debug_error,
    })


# ---- Customer Portal (manage / cancel) ----

@router.post("/dashboard/billing/portal")
def customer_portal(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return RedirectResponse("/login", status_code=303)
    if not current_user.stripe_customer_id:
        return RedirectResponse("/dashboard/upgrade", status_code=303)
    s = _stripe()
    session = s.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=f"{_APP_URL}/dashboard/account#billing",
    )
    return RedirectResponse(session.url, status_code=303)


# ---- Webhook ----

@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.body()
    stripe_signature = request.headers.get("stripe-signature")
    _log.info("stripe_webhook received payload_len=%d sig_present=%s", len(payload), bool(stripe_signature))
    if not STRIPE_WEBHOOK_SECRET:
        _log.error("stripe_webhook called but STRIPE_WEBHOOK_SECRET not set")
        raise HTTPException(status_code=503, detail="Webhook secret not configured.")
    s = _stripe()
    try:
        event = s.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    etype = event["type"]
    _log.info("stripe_webhook event=%s", etype)

    if etype == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"], db)
    elif etype in ("customer.subscription.deleted", "customer.subscription.updated"):
        _handle_subscription_change(event["data"]["object"], db)
    elif etype == "invoice.payment_failed":
        _log.warning("stripe payment_failed customer=%s", event["data"]["object"].get("customer"))

    return {"ok": True}


def _handle_checkout_completed(session, db: Session) -> None:
    user_id = int(session.get("metadata", {}).get("user_id", 0))
    if not user_id:
        return
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return
    user.tier = "pro"
    user.stripe_customer_id = session.get("customer")
    user.stripe_subscription_id = session.get("subscription")
    db.commit()
    _log.info("upgraded user_id=%s to pro via checkout", user_id)


def _handle_subscription_change(subscription, db: Session) -> None:
    user_id = int(subscription.get("metadata", {}).get("user_id", 0))
    customer_id = subscription.get("customer")
    status = subscription.get("status")

    # Look up by user_id metadata first, fall back to customer_id
    user = None
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
    if not user and customer_id:
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        return

    if status in ("active", "trialing"):
        user.tier = "pro"
    elif status in ("canceled", "unpaid", "incomplete_expired"):
        user.tier = "free"
    db.commit()
    _log.info("subscription_change user_id=%s status=%s tier=%s", user.id, status, user.tier)
