"""Regression tests for the Stripe webhook handler (routes/billing.py).

Run: python backend/scripts/test_stripe_webhook.py

Root cause these guard against (2026-11-10, prod webhook disable warning):
`construct_event` returns a StripeObject whose `.get` routes through
__getattr__ -> KeyError -> AttributeError in stripe-python 15.x. The handler
called `event["data"]["object"].get(...)`, so EVERY real delivery raised an
uncaught AttributeError and returned HTTP 500. Stripe flagged the endpoint for
disabling. Fix: verify the signature with construct_event, then read the event
from the RAW JSON as plain dicts. These tests assert a valid-signed event
returns 200 (not 500) for every handled type, a bad signature returns 400, and
the plain-dict path actually drives the tier change.
"""
import hashlib
import hmac
import json
import os
import sys
import time

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _BACKEND)                       # auth, models
sys.path.insert(0, os.path.join(_BACKEND, "routes"))  # billing

# Env must be set BEFORE importing billing (module reads these at import time).
TEST_SECRET = "whsec_test_" + "a" * 32
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = TEST_SECRET

import billing  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models import get_db  # noqa: E402

passed = 0
failed = 0


def check(label, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}: got {actual!r}, expected {expected!r}")


class FakeUser:
    def __init__(self, uid=1, tier="free"):
        self.id = uid
        self.tier = tier
        self.stripe_customer_id = None
        self.stripe_subscription_id = None


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._result


class FakeSession:
    """Returns `user` for any query; records commit/rollback calls."""
    def __init__(self, user=None):
        self.user = user
        self.committed = False
        self.rolled_back = False

    def query(self, *a, **k):
        return FakeQuery(self.user)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def make_client(user=None):
    app = FastAPI()
    app.include_router(billing.router)
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    return TestClient(app, raise_server_exceptions=False)


def sign(payload: bytes, secret: str = TEST_SECRET) -> str:
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


def event_bytes(etype, obj):
    return json.dumps({
        "id": "evt_test", "object": "event", "api_version": "2026-03-25.dahlia",
        "type": etype, "data": {"object": obj},
    }).encode()


def post(client, payload, header):
    return client.post("/stripe/webhook", content=payload,
                       headers={"stripe-signature": header, "Content-Type": "application/json"})


# --- 1. bad signature -> 400 (unchanged behavior) ---
c = make_client()
pl = event_bytes("invoice.payment_failed", {"object": "invoice", "customer": "cus_1"})
check("bad signature -> 400", post(c, pl, "t=1,v1=bogus").status_code, 400)

# --- 2. invoice.payment_failed valid sig -> 200 (was 500: the exact crash) ---
c = make_client()
pl = event_bytes("invoice.payment_failed", {"object": "invoice", "customer": "cus_1"})
r = post(c, pl, sign(pl))
check("invoice.payment_failed valid sig -> 200 (was 500)", r.status_code, 200)

# --- 3. checkout.session.completed drives the upgrade via the plain-dict path ---
user = FakeUser(uid=7, tier="free")
c = make_client(user)
pl = event_bytes("checkout.session.completed", {
    "object": "checkout.session", "metadata": {"user_id": "7"},
    "customer": "cus_7", "subscription": "sub_7",
})
r = post(c, pl, sign(pl))
check("checkout.completed -> 200", r.status_code, 200)
check("checkout.completed upgraded user tier=pro", user.tier, "pro")
check("checkout.completed set customer id", user.stripe_customer_id, "cus_7")

# --- 4. customer.subscription.deleted -> downgrade to free ---
user = FakeUser(uid=9, tier="pro")
user.stripe_customer_id = "cus_9"
c = make_client(user)
pl = event_bytes("customer.subscription.deleted", {
    "object": "subscription", "metadata": {"user_id": "9"},
    "customer": "cus_9", "status": "canceled",
})
r = post(c, pl, sign(pl))
check("subscription.deleted -> 200", r.status_code, 200)
check("subscription.deleted downgraded tier=free", user.tier, "free")

# --- 5. metadata missing/None must not crash (guard) -> 200 ---
c = make_client(None)
pl = event_bytes("checkout.session.completed", {"object": "checkout.session", "metadata": None})
check("checkout with metadata=None -> 200 (no crash)", post(c, pl, sign(pl)).status_code, 200)

# --- 6. unhandled event type -> 200 no-op ---
c = make_client()
pl = event_bytes("payment_intent.succeeded", {"object": "payment_intent"})
check("unhandled type -> 200", post(c, pl, sign(pl)).status_code, 200)

# --- 7. malformed JSON body with valid sig -> 400 (not 500) ---
c = make_client()
pl = b"not json at all"
check("malformed body -> 400", post(c, pl, sign(pl)).status_code, 400)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
