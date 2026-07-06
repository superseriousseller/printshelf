"""
Database models for PrintShelf
3D print tracking with multi-user authentication.
"""
import enum
import os
import re
import secrets
import unicodedata
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Date, Text, ForeignKey, Index, JSON, text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, validates

Base = declarative_base()


def slugify(text_value: str, max_len: int = 60) -> str:
    """URL-safe slug from a title: lowercase, alnum runs joined by hyphens.

    Decorative only — the numeric ID is the real key, so an empty result
    (e.g. an all-emoji title) is fine and yields a bare-ID URL.
    """
    if not text_value:
        return ""
    # Fold accents to ASCII (café → cafe) before stripping non-alnum.
    folded = unicodedata.normalize("NFKD", text_value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    if len(slug) > max_len:
        # trim to max_len, then back off to the last clean word boundary
        slug = slug[:max_len].rsplit("-", 1)[0] if "-" in slug[:max_len] else slug[:max_len]
    return slug.strip("-")


def print_url_id(print_id: int, title: str) -> str:
    """Canonical print path segment `{id}-{slug}`, or bare `{id}` if slug empty.

    Single source of truth for the URL format — used by Print.url_id and the
    sitemap builder so the two can never drift apart.
    """
    slug = slugify(title)
    return f"{print_id}-{slug}" if slug else str(print_id)


# Canonical display names for brands users type many ways. Keyed by the brand
# lowercased with all non-alphanumerics stripped. Only known brands are folded;
# unknown brands are returned trimmed-but-verbatim (never mangled). Used by the
# Filament/Printer `brand` validators (every write) + the one-time backfill, so
# facet dropdowns and "Buy" matching see one spelling per brand.
_BRAND_CANON = {
    "bambu": "Bambu Lab",
    "bambulab": "Bambu Lab",
    "bambulabs": "Bambu Lab",
    "polymaker": "Polymaker",
    "polyterra": "PolyTerra",
    "polylite": "PolyLite",
    "panchroma": "Panchroma",
    "sunlu": "SUNLU",
    "anycubic": "Anycubic",
    "flashforge": "FlashForge",
    "matterhackers": "MatterHackers",
    "hatchbox": "Hatchbox",
    "overture": "Overture",
    "esun": "eSun",
    "elegoo": "Elegoo",
    "creality": "Creality",
    "prusament": "Prusament",
    "inland": "Inland",
    "protopasta": "Protopasta",
}


def canonical_brand(raw: "str | None") -> "str | None":
    """Fold known brand spellings to one canonical display name; trim others."""
    if not raw:
        return raw
    s = raw.strip()
    if not s:
        return s
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    return _BRAND_CANON.get(key, s)


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
    SLICER = "slicer"          # auto-imported via the slicer post-processing script


# Free-tier limits — checked on POST /api/prints and POST /api/filaments
FREE_TIER_PRINT_LIMIT = 50
FREE_TIER_FILAMENT_LIMIT = 10
FREE_TIER_COLLECTION_LIMIT = 10


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
    email_verified = Column(Boolean, default=False, nullable=False, server_default=text('false'))

    # Notification preferences
    notify_follow = Column(Boolean, default=True, nullable=False, server_default=text('true'))
    notify_feed = Column(Boolean, default=True, nullable=False, server_default=text('true'))
    unsubscribe_token = Column(String(32), nullable=True)

    # Shelf analytics
    profile_views = Column(Integer, default=0, nullable=False, server_default=text('0'))

    # Onboarding drip email tracking
    drip_day2_sent = Column(Boolean, default=False, nullable=False, server_default=text('false'))
    drip_day7_sent = Column(Boolean, default=False, nullable=False, server_default=text('false'))

    # Chrome extension auth — regeneratable from settings
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    google_sub = Column(String(64), nullable=True, unique=True, index=True)  # Google account id (OAuth login)

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

    @validates("brand")
    def _canon_brand(self, key, value):
        return canonical_brand(value)

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
    color_hex_source = Column(String(10), nullable=True)  # "scraped" | "guessed"
    diameter = Column(Float, default=1.75, nullable=False)  # 1.75 or 2.85

    finish = Column(String(100), nullable=True)      # Silk, Matte, Glow, Wood, Carbon Fiber, etc.
    status = Column(String(20), default="own", nullable=False)
    source_url = Column(String(1000), nullable=True)
    price_at_save = Column(Float, nullable=True)   # purchase price of the spool
    spool_weight_g = Column(Integer, nullable=True) # spool weight in grams (1000, 500, 250…)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="filaments")

    @validates("brand")
    def _canon_brand(self, key, value):
        return canonical_brand(value)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "brand": self.brand,
            "material": self.material,
            "colorName": self.color_name,
            "colorHex": self.color_hex,
            "colorHexSource": self.color_hex_source,
            "diameter": self.diameter,
            "status": self.status,
            "sourceUrl": self.source_url,
            "priceAtSave": self.price_at_save,
            "spoolWeightG": self.spool_weight_g,
            "finish": self.finish,
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

    # Engagement counters (denormalized for cheap sort/display)
    like_count = Column(Integer, default=0, nullable=False, server_default="0")
    view_count = Column(Integer, default=0, nullable=False, server_default="0")

    queued = Column(Boolean, default=False, nullable=False, index=True)
    is_public = Column(Boolean, default=True, nullable=False, index=True)

    # Print settings
    layer_height = Column(Float, nullable=True)      # mm, e.g. 0.20
    infill_pct = Column(Integer, nullable=True)      # %, e.g. 15
    supports = Column(Boolean, nullable=True)        # True/False/None (not set)
    print_time_mins = Column(Integer, nullable=True) # total minutes
    filament_used_g = Column(Float, nullable=True)   # grams

    video_url = Column(String(1000), nullable=True)   # YouTube/TikTok/Instagram link
    focal_x = Column(Float, nullable=True)             # thumbnail focus point, 0–100 (default 50)
    focal_y = Column(Float, nullable=True)             # thumbnail focus point, 0–100 (default 50)
    category = Column(String(50), nullable=True)       # explore filter category

    print_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="prints")
    printer = relationship("Printer", back_populates="prints")

    @property
    def slug(self) -> str:
        """Decorative URL suffix derived from the title (see slugify)."""
        return slugify(self.title)

    @property
    def url_id(self) -> str:
        """Canonical path segment `{id}-{slug}`, or bare `{id}` if slug empty."""
        return print_url_id(self.id, self.title)

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
            "videoUrl": self.video_url,
            "focalX": self.focal_x,
            "focalY": self.focal_y,
            "category": self.category,
            "likeCount": self.like_count,
            "viewCount": self.view_count,
        }


# Slugs are stable (existing prints keep working); display labels can change freely.
PRINT_CATEGORIES = [
    ("functional", "Functional Parts"),
    ("tools", "Tools & Jigs"),
    ("toys-games", "Toys & Games"),
    ("miniatures", "Miniatures & Figurines"),
    ("household", "Home & Decor"),
    ("art", "Art & Sculpture"),
    ("gadgets", "Gadgets & Electronics"),
    ("cosplay-props", "Cosplay & Props"),
    ("replacement-parts", "Replacement Parts"),
    ("education", "Education & Science"),
    ("other", "Other"),
]
VALID_PRINT_CATEGORIES = {slug for slug, _ in PRINT_CATEGORIES}
PRINT_CATEGORY_LABELS = dict(PRINT_CATEGORIES)

Index("ix_prints_user_queued", Print.user_id, Print.queued)
Index("ix_prints_user_created", Print.user_id, Print.created_at.desc())


# ============== PrintLink ==============

class PrintLink(Base):
    __tablename__ = "print_links"

    id = Column(Integer, primary_key=True, index=True)
    print_id = Column(Integer, ForeignKey("prints.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(200), nullable=False)
    url = Column(String(2000), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)


# ============== Follow ==============

class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_follows_pair", Follow.follower_id, Follow.following_id, unique=True)


# ============== Like ==============

class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    print_id = Column(Integer, ForeignKey("prints.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_likes_pair", Like.user_id, Like.print_id, unique=True)
Index("ix_likes_created_at", Like.created_at)


# ============== Collection ==============

class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    @property
    def slug(self) -> str:
        """Decorative URL suffix derived from the name (see slugify)."""
        return slugify(self.name)

    @property
    def url_id(self) -> str:
        """Canonical path segment `{id}-{slug}`, or bare `{id}` if slug empty."""
        return print_url_id(self.id, self.name)


class CollectionPrint(Base):
    __tablename__ = "collection_prints"

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    print_id = Column(Integer, ForeignKey("prints.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_collection_prints_pair", CollectionPrint.collection_id, CollectionPrint.print_id, unique=True)


# ============== Registry Entry ==============
# Vertical-agnostic "verified registry of things you didn't know you could
# print" — instruments is the first vertical (flat `vertical` column, not a
# join table: one vertical exists today). Fully curated (no public
# submissions), so `bom`/`filament_usage`/`media` are JSON rather than
# normalized tables — matches the Print.filament_ids precedent, no relational
# query need at this scale.
#
# No number here is ever fabricated: axes/cost fields stay null until real
# data arrives (slicer weights, effort-rubric backfill, checked prices).
# Render layer must treat null as "pending verification," never default it
# to something that looks like data.

class RegistryEntry(Base):
    __tablename__ = "registry_entries"

    id = Column(Integer, primary_key=True, index=True)
    vertical = Column(String(30), nullable=False, default="instruments")
    slug = Column(String(120), nullable=False)          # real key here (unlike Print.slug) — Cam-authored, not user content
    name = Column(String(200), nullable=False)
    designer = Column(String(200), nullable=True)
    family = Column(String(50), nullable=True)           # Woodwind/Brass/Percussion/Strings/Practice aid
    status = Column(String(20), nullable=False, default="listed")  # listed | frontier

    # Four-axis honesty card. function_axis is the only one with real seed
    # data (from the HTML's playability `level`); the rest stay null until
    # Cam's slicer/rubric backfill.
    function_axis = Column(Integer, nullable=True)        # 0-3 playability
    fidelity_axis = Column(Integer, nullable=True)         # 0-5 tone fidelity
    objective_score = Column(Float, nullable=True)         # librosa spectral score, Slice 3+
    effort_print_load = Column(String(10), nullable=True)  # S/M/L/XL bucket
    effort_assembly_skill = Column(Integer, nullable=True)  # 1-5 rubric
    verified_by_owner = Column(Boolean, default=False, nullable=False, server_default="false")

    license = Column(String(200), nullable=True)
    source_url = Column(String(1000), nullable=True)
    demo_url = Column(String(1000), nullable=True)
    note = Column(Text, nullable=True)

    # Frontier-only narrative fields (status == "frontier")
    gap_why = Column(Text, nullable=True)
    gap_status = Column(String(100), nullable=True)   # e.g. "Open · hard mode" — distinct from `status` above
    gap_closest = Column(Text, nullable=True)          # plain text (HTML stripped at seed time)

    # Retail comparison — fixed-shape pair, flat columns (not JSON)
    retail_budget_price = Column(Float, nullable=True)
    retail_budget_url = Column(String(1000), nullable=True)
    retail_budget_checked_at = Column(DateTime, nullable=True)
    retail_premium_price = Column(Float, nullable=True)
    retail_premium_url = Column(String(1000), nullable=True)
    retail_premium_checked_at = Column(DateTime, nullable=True)

    # filament_usage: [{material, grams}]
    # bom: [{spec, qty, tier, consumable, fulfillments:[{vendor,url,price,currency,checked_at,availability,affiliate}]}]
    # media: [] — Slice 3 audio A/B bolts on here
    filament_usage = Column(JSON, nullable=True, default=list)
    bom = Column(JSON, nullable=True, default=list)
    media = Column(JSON, nullable=True, default=list)

    owner_build_print_id = Column(Integer, ForeignKey("prints.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_build_episode_url = Column(String(1000), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner_build_print = relationship("Print")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "vertical": self.vertical,
            "slug": self.slug,
            "name": self.name,
            "designer": self.designer,
            "family": self.family,
            "status": self.status,
            "axes": {
                "function": self.function_axis,
                "fidelity": self.fidelity_axis,
                "objectiveScore": self.objective_score,
                "effortPrintLoad": self.effort_print_load,
                "effortAssemblySkill": self.effort_assembly_skill,
            },
            "verifiedByOwner": self.verified_by_owner,
            "license": self.license,
            "sourceUrl": self.source_url,
            "demoUrl": self.demo_url,
            "note": self.note,
            "gapWhy": self.gap_why,
            "gapStatus": self.gap_status,
            "gapClosest": self.gap_closest,
            "retail": {
                "budget": {
                    "price": self.retail_budget_price,
                    "url": self.retail_budget_url,
                    "checkedAt": self.retail_budget_checked_at.isoformat() if self.retail_budget_checked_at else None,
                },
                "premium": {
                    "price": self.retail_premium_price,
                    "url": self.retail_premium_url,
                    "checkedAt": self.retail_premium_checked_at.isoformat() if self.retail_premium_checked_at else None,
                },
            },
            "filamentUsage": self.filament_usage or [],
            "bom": self.bom or [],
            "media": self.media or [],
            "ownerBuildPrintId": self.owner_build_print_id,
            "ownerBuildEpisodeUrl": self.owner_build_episode_url,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


Index("ix_registry_entries_vertical_slug", RegistryEntry.vertical, RegistryEntry.slug, unique=True)
Index("ix_registry_entries_vertical_status", RegistryEntry.vertical, RegistryEntry.status)


# ============== Affiliate Click ==============

class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    filament_id = Column(Integer, nullable=True)   # not FK — filament may be deleted
    store = Column(String(50), nullable=True, index=True)  # amazon, bambu, polymaker, etc.
    clicked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ============== Filament Prices (instruments pricing, Slice 3) ==============
# The one maintained pricing input for the instruments registry: material ->
# $/kg. Everything else (spool/build/play cost) is computed at render time,
# never stored — see instruments_pricing.py.

class FilamentPrice(Base):
    __tablename__ = "filament_prices"

    id = Column(Integer, primary_key=True, index=True)
    material = Column(String(50), nullable=False)
    price_per_kg = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_filament_prices_material", FilamentPrice.material, unique=True)


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
