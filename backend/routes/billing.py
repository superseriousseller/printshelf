"""Stripe billing — Checkout, Customer Portal, and webhook handler."""
import logging
import os
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user_web_optional
from models import User, get_db

router = APIRouter(tags=["billing"])

_log = logging.getLogger(__name__)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))

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

@router.get("/dashboard/billing/success", response_class=HTMLResponse)
def billing_success(
    request: Request,
    session_id: str = "",
    current_user: Optional[User] = Depends(get_current_user_web_optional),
    db: Session = Depends(get_db),
):
    # Webhook handles the actual tier upgrade; this is just the thank-you page.
    return templates.TemplateResponse(request, "dashboard/upgrade_success.html", {
        "current_user": current_user,
        "user": current_user,
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
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    if not STRIPE_WEBHOOK_SECRET:
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
