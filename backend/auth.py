"""
Authentication for PrintShelf.

Two auth paths share the same Bearer-token header:
  1. JWT (web)             — short-lived signed token, 30-day expiry
  2. API key (extension)   — long-lived per-user UUID stored on the User row

Both flows resolve to the same `User` dependency via `get_current_user`.
The API key path lets the Chrome extension authenticate without a login flow.
"""
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from jwt.exceptions import PyJWTError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from models import User, get_db, generate_api_key

SESSION_COOKIE_NAME = "session"

# --- JWT config ---
_secret_key = os.environ.get("SECRET_KEY")
_is_production = bool(os.environ.get("DATABASE_URL"))

if _is_production and not _secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is required in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

SECRET_KEY = _secret_key or secrets.token_hex(32)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,30}$")

security = HTTPBearer(auto_error=False)


# --- Password hashing ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# --- JWT ---

def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except PyJWTError:
        return None


# --- Bearer resolution: JWT first, then API key ---

def _user_from_credentials(
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
) -> Optional[User]:
    if not credentials:
        return None
    token = credentials.credentials.strip()
    if not token:
        return None

    # Try JWT
    user_id = decode_token(token)
    if user_id is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if user is not None:
            return user

    # Fall back to API key (used by Chrome extension)
    user = db.query(User).filter(User.api_key == token).first()
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_credentials(credentials, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    return _user_from_credentials(credentials, db)


def get_current_user_web_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Web UI auth: reads the session cookie set by the login form.

    Returns None instead of raising so handlers can redirect to /login.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = decode_token(token)
    if user_id is None:
        return None
    return db.query(User).filter(User.id == user_id).first()


# --- User creation / login ---

def _normalize_email(email: str) -> str:
    return email.lower().strip()


def _normalize_username(username: str) -> str:
    return username.strip()


def create_user(
    db: Session,
    email: str,
    password: str,
    username: str,
    display_name: Optional[str] = None,
) -> User:
    """Register a new user.

    Raises HTTPException(409) if email or username is taken.
    Raises HTTPException(400) if username format is invalid.
    """
    email_n = _normalize_email(email)
    username_n = _normalize_username(username)

    if not USERNAME_RE.match(username_n):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-30 chars: letters, numbers, underscore, dash.",
        )

    if db.query(User).filter(User.email == email_n).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if db.query(User).filter(User.username == username_n).first():
        raise HTTPException(status_code=409, detail="Username taken")

    user = User(
        email=email_n,
        password_hash=hash_password(password),
        username=username_n,
        display_name=(display_name or username_n).strip(),
        api_key=generate_api_key(),
        tier="free",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.email == _normalize_email(email)).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.utcnow()
    db.commit()
    return user


def regenerate_api_key(db: Session, user: User) -> str:
    user.api_key = generate_api_key()
    db.commit()
    db.refresh(user)
    return user.api_key
