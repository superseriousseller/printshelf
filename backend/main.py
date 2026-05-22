"""
PrintShelf API — 3D print tracking with multi-user authentication.

Endpoints in this file cover the v1 build order steps 1-2:
  - /api/health
  - /api/auth/register, /api/auth/login, /api/auth/me
  - /api/auth/api-key/regenerate

Layered features (printers, filaments, prints, import-url, uploads,
profiles, stats, stripe, community filaments) are added in subsequent
modules and routed from here.
"""
from dotenv import load_dotenv
load_dotenv()

import logging
import os
import sys
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import User, get_db, init_db
from auth import (
    create_user, authenticate_user, create_access_token,
    get_current_user, regenerate_api_key,
)
from routes import printers as printers_routes
from routes import filaments as filaments_routes
from routes import prints as prints_routes
from routes import profile as profile_routes
from routes import web_auth as web_auth_routes

# --- Logging ---
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

APP_ENV = os.environ.get("APP_ENV", "development")
APP_DOMAIN = os.environ.get("APP_DOMAIN", "printshelf.app")
APP_URL = os.environ.get("APP_URL", "https://printshelf.app")
APP_VERSION = "0.1.0"

# --- Sentry (optional, gated on env + DSN) ---
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN and APP_ENV in ("production", "staging"):
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=APP_ENV,
            traces_sample_rate=0.1,
            send_default_pii=False,
            max_breadcrumbs=50,
            integrations=[FastApiIntegration()],
        )
        logger.info("Sentry initialized")
    except Exception as e:
        logger.error(f"Sentry init failed: {e}")


app = FastAPI(
    title="PrintShelf API",
    description="3D print tracking for makers",
    version=APP_VERSION,
)


# --- CORS ---
# Chrome extension origin (chrome-extension://<id>) must be in ALLOWED_ORIGINS.
_default_origins = "http://localhost:5173,http://localhost:3000"
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", _default_origins)
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(printers_routes.router)
app.include_router(filaments_routes.router)
app.include_router(prints_routes.router)
app.include_router(profile_routes.router)
app.include_router(web_auth_routes.router)

# Serve /static/* (CSS, future favicon etc.)
from fastapi.staticfiles import StaticFiles  # noqa: E402
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_BACKEND_DIR, "static")), name="static")


# --- Lifecycle ---
@app.on_event("startup")
def _startup() -> None:
    init_db()
    logger.info(f"PrintShelf {APP_VERSION} started in {APP_ENV}")


# --- Health ---
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "env": APP_ENV,
    }


# --- Auth schemas ---
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    username: str = Field(min_length=3, max_length=30)
    display_name: Optional[str] = Field(default=None, max_length=100)


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=100)
    bio: Optional[str] = Field(default=None, max_length=2000)
    avatar_url: Optional[str] = Field(default=None, max_length=500)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


# --- Auth endpoints ---
@app.post("/api/auth/register", response_model=AuthResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = create_user(
        db,
        email=body.email,
        password=body.password,
        username=body.username,
        display_name=body.display_name,
    )
    token = create_access_token(user.id)
    return AuthResponse(token=token, user=user.to_dict(include_private=True))


@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.id)
    return AuthResponse(token=token, user=user.to_dict(include_private=True))


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user.to_dict(include_private=True)


@app.patch("/api/auth/me")
def update_me(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip()
        setattr(user, k, v)
    db.commit()
    db.refresh(user)
    return user.to_dict(include_private=True)


@app.post("/api/auth/api-key/regenerate")
def regen_api_key(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    new_key = regenerate_api_key(db, user)
    return {"apiKey": new_key}
