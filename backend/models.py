"""
Database models for PrintShelf
3D print tracking with multi-user authentication.
"""
import enum
import os
import secrets
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Date, Text, ForeignKey, Index, JSON,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()


# ============== Enums (stored as strings for migration flexibility) ==============

class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"


class FilamentStatus(str, enum.Enum):
    OWN = "own"
    WANT = "want"
    USED_UP = "used_up"
    LOW = "low"


class PrintStatus(str, enum.Enum):
    QUEUED = "queued"
    PRINTED = "printed"
    FAILED = "failed"
    PARTIAL = "partial"


class SourcePlatform(str, enum.Enum):
    MAKERWORLD = "makerworld"
    PRINTABLES = "printables"
    CULTS3D = "cults3d"
    THINGIVERSE = "thingiverse"
    MANUAL = "manual"


# Free-tier limits — checked on POST /api/prints and POST /api/filaments
FREE_TIER_PRINT_LIMIT = 50
FREE_TIER_FILAMENT_LIMIT = 10


# ============== User ==============

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    # Public-facing identity (used in /@{username})
    username = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=True)

    # Profile
    avatar_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    socials = Column(JSON, nullable=True)  # {"makerworld": url, "instagram": url, ...}

    # Subscription
    tier = Column(String(20), default="free", nullable=False)
    stripe_customer_id = Column(String(100), nullable=True, unique=True, index=True)
    stripe_subscription_id = Column(String(100), nullable=True, index=True)

    # Email verification
    email_verified = Column(Boolean, default=False, nullable=False, server_default="0")

    # Chrome extension auth — regeneratable from settings
    api_key = Column(String(64), unique=True, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

    # Relationships
    printers = relationship("Printer", back_populates="user", cascade="all, delete-orphan")
    filaments = relationship("Filament", back_populates="user", cascade="all, delete-orphan")
    prints = relationship("Print", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, include_private: bool = False) -> dict:
        out = {
            "id": self.id,
            "username": self.username,
            "displayName": self.display_name or self.username,
            "avatarUrl": self.avatar_url,
            "bio": self.bio,
            "socials": self.socials or {},
            "tier": self.tier or "free",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
        if include_private:
            out.update({
                "email": self.email,
                "apiKey": self.api_key,
                "stripeCustomerId": self.stripe_customer_id,
                "stripeSubscriptionId": self.stripe_subscription_id,
                "lastLogin": self.last_login.isoformat() if self.last_login else None,
            })
        return out


# ============== Printer ==============

class Printer(Base):
    __tablename__ = "printers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(100), nullable=False)       # e.g. "My X1C"
    brand = Column(String(50), nullable=True)        # e.g. "Bambu Lab"
    model = Column(String(100), nullable=True)       # e.g. "X1 Carbon"

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="printers")
    prints = relationship("Print", back_populates="printer")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "model": self.model,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ============== Filament ==============

class Filament(Base):
    __tablename__ = "filaments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    brand = Column(String(100), nullable=False)
    material = Column(String(50), nullable=False)         # PLA, PETG, ABS, TPU, etc.
    color_name = Column(String(100), nullable=True)
    color_hex = Column(String(7), nullable=True)          # #RRGGBB
    diameter = Column(Float, default=1.75, nullable=False)  # 1.75 or 2.85

    status = Column(String(20), default="own", nullable=False)
    source_url = Column(String(1000), nullable=True)
    price_at_save = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="filaments")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "brand": self.brand,
            "material": self.material,
            "colorName": self.color_name,
            "colorHex": self.color_hex,
            "diameter": self.diameter,
            "status": self.status,
            "sourceUrl": self.source_url,
            "priceAtSave": self.price_at_save,
            "notes": self.notes,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ============== Print ==============

class Print(Base):
    __tablename__ = "prints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    title = Column(String(300), nullable=False)
    designer = Column(String(200), nullable=True)
    source_platform = Column(String(30), default="manual", nullable=False)
    source_url = Column(String(1000), nullable=True)

    # External thumbnail (from source platform) vs. user-uploaded photo (R2)
    thumbnail_url = Column(String(1000), nullable=True)
    photo_url = Column(String(1000), nullable=True)

    printer_id = Column(Integer, ForeignKey("printers.id", ondelete="SET NULL"), nullable=True, index=True)

    # Multi-material support — store filament IDs as JSON array
    filament_ids = Column(JSON, nullable=True, default=list)

    status = Column(String(20), default="printed", nullable=False)
    rating = Column(Integer, nullable=True)              # 1-5
    notes = Column(Text, nullable=True)

    queued = Column(Boolean, default=False, nullable=False, index=True)
    is_public = Column(Boolean, default=True, nullable=False, index=True)

    # Print settings
    layer_height = Column(Float, nullable=True)      # mm, e.g. 0.20
    infill_pct = Column(Integer, nullable=True)      # %, e.g. 15
    supports = Column(Boolean, nullable=True)        # True/False/None (not set)
    print_time_mins = Column(Integer, nullable=True) # total minutes
    filament_used_g = Column(Float, nullable=True)   # grams

    print_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="prints")
    printer = relationship("Printer", back_populates="prints")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "designer": self.designer,
            "sourcePlatform": self.source_platform,
            "sourceUrl": self.source_url,
            "thumbnailUrl": self.thumbnail_url,
            "photoUrl": self.photo_url,
            "printerId": self.printer_id,
            "filamentIds": self.filament_ids or [],
            "status": self.status,
            "rating": self.rating,
            "notes": self.notes,
            "queued": self.queued,
            "isPublic": self.is_public,
            "printDate": self.print_date.isoformat() if self.print_date else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "layerHeight": self.layer_height,
            "infillPct": self.infill_pct,
            "supports": self.supports,
            "printTimeMins": self.print_time_mins,
            "filamentUsedG": self.filament_used_g,
        }


Index("ix_prints_user_queued", Print.user_id, Print.queued)
Index("ix_prints_user_created", Print.user_id, Print.created_at.desc())


# ============== Follow ==============

class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_follows_pair", Follow.follower_id, Follow.following_id, unique=True)


# ============== Affiliate Click ==============

class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    filament_id = Column(Integer, nullable=True)   # not FK — filament may be deleted
    store = Column(String(50), nullable=True, index=True)  # amazon, bambu, polymaker, etc.
    clicked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ============== Community Filament (shared autocomplete DB) ==============

class CommunityFilament(Base):
    __tablename__ = "community_filaments"

    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(100), nullable=False, index=True)
    material = Column(String(50), nullable=False, index=True)
    color_name = Column(String(100), nullable=True)
    color_hex = Column(String(7), nullable=True)
    diameter = Column(Float, default=1.75, nullable=False)
    source_url_template = Column(String(1000), nullable=True)
    verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "brand": self.brand,
            "material": self.material,
            "colorName": self.color_name,
            "colorHex": self.color_hex,
            "diameter": self.diameter,
            "sourceUrlTemplate": self.source_url_template,
            "verified": self.verified,
        }


Index("ix_community_filaments_brand_material", CommunityFilament.brand, CommunityFilament.material)


# ============== Password Reset Token ==============

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)

    user = relationship("User")


# ============== Email Verification Token ==============

class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)

    user = relationship("User")


# ============== URL Import Cache ==============

class ImportCache(Base):
    """Cache for /api/import-url so the same source URL isn't scraped twice."""
    __tablename__ = "import_cache"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String(1000), unique=True, nullable=False, index=True)
    platform = Column(String(30), nullable=False)
    title = Column(String(300), nullable=True)
    designer = Column(String(200), nullable=True)
    thumbnail_url = Column(String(1000), nullable=True)
    raw_metadata = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "title": self.title,
            "designer": self.designer,
            "thumbnailUrl": self.thumbnail_url,
            "sourceUrl": self.source_url,
        }


# ============== Database Setup ==============

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Production: PostgreSQL on Railway
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        pool_recycle=300,
        pool_timeout=10,
        echo=False,
    )
else:
    # Local development: SQLite
    from sqlalchemy.pool import StaticPool
    from sqlalchemy import event

    DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(DB_DIR, exist_ok=True)
    DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'printshelf.db')}"

    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_api_key() -> str:
    """64-char URL-safe API key for Chrome extension auth."""
    return secrets.token_urlsafe(48)[:64]


def init_db() -> None:
    """Initialize the database using Alembic migrations.

    - Fresh DB: runs all migrations to create tables.
    - DB already at a tracked revision: runs any pending migrations.
    - DB with tables but no alembic_version: stamps initial baseline, then upgrades.
    """
    from sqlalchemy import inspect, text
    from alembic.config import Config
    from alembic import command

    backend_dir = os.path.dirname(os.path.abspath(__file__))
    alembic_cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    has_data_tables = "users" in existing_tables

    has_tracked_revision = False
    if "alembic_version" in existing_tables:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            has_tracked_revision = row is not None

    if has_tracked_revision:
        print("=== Alembic: running pending migrations ===")
        command.upgrade(alembic_cfg, "head")
    elif has_data_tables:
        # Existing DB without tracking — should not happen on fresh PrintShelf,
        # but supported for safety. Replace INITIAL_REVISION once it exists.
        print("=== Alembic: existing tables found, stamping to head ===")
        command.stamp(alembic_cfg, "head")
    else:
        print("=== Alembic: fresh database, running all migrations ===")
        command.upgrade(alembic_cfg, "head")

    print("=== Alembic: initialization complete ===")
