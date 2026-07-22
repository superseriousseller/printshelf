"""Public homepage at /.

Server-rendered marketing page with a real visual hook: a gallery of
the most recent public prints across all users. Empty at fresh-launch;
fills out as people sign up and log prints.
"""
import os
import logging
import random
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from affiliate import build_preview_catalog, store_search_url
from auth import filament_preview_enabled, instruments_index_enabled, get_current_user_web_optional
from instruments_pricing import compute_costs, staleness_state
from sqlalchemy import func, nullslast, or_

from models import AffiliateClick, Filament, FilamentPrice, InstrumentsNotifySignup, Like, Print, Printer, RegistryEntry, User, get_db, print_url_id, PRINT_CATEGORIES

router = APIRouter(tags=["homepage"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BACKEND_DIR, "templates"))
# base.html topbar has a gated "Preview" link → this instance renders public pages.
templates.env.globals["filament_preview_enabled"] = filament_preview_enabled
templates.env.globals["instruments_index_enabled"] = instruments_index_enabled


def _format_cost(value):
    """Jinja filter: None -> None (template decides the fallback text);
    a (low, high) tuple -> '$X' if they collapse to one number, else '$X–$Y';
    a plain number -> '$X'."""
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        low, high = value
        if round(low) == round(high):
            return f"${low:,.0f}"
        return f"${low:,.0f}–${high:,.0f}"
    return f"${value:,.0f}"


templates.env.filters["cost_display"] = _format_cost

# Preferred display order for known instrument families — NOT a hardcoded
# allowlist. _group_by_family() iterates whatever families actually exist in
# the data and only uses this list to order the known ones; any family not
# listed here still renders (sorted after), so a future family can't silently
# vanish from the page the way the HTML prototype's hardcoded FAM_ORDER would.
INSTRUMENT_FAMILY_ORDER = ["Woodwind", "Brass", "Percussion", "Strings"]


def _group_by_family(entries):
    groups = {}
    for entry in entries:
        groups.setdefault(entry.family or "Other", []).append(entry)
    known = [f for f in INSTRUMENT_FAMILY_ORDER if f in groups]
    extra = sorted(f for f in groups if f not in INSTRUMENT_FAMILY_ORDER)
    return [(family, groups[family]) for family in known + extra]

FEATURED_LIMIT = 6


@router.get("/", response_class=HTMLResponse)
def homepage(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    # Pull the most recent public, non-queued prints with photos.
    # Joined so we can render the maker's username under each card.
    rows = (
        db.query(Print, User.username, User.display_name)
        .join(User, Print.user_id == User.id)
        .filter(
            Print.is_public == True,  # noqa: E712
            Print.queued == False,    # noqa: E712
        )
        .order_by(Print.created_at.desc())
        .limit(FEATURED_LIMIT)
        .all()
    )
    featured = [
        {
            "title": p.title,
            "designer": p.designer,
            "thumbnail": p.photo_url or p.thumbnail_url,
            "rating": p.rating,
            "username": uname,
            "maker": display_name or uname,
            "status": p.status,
            "focal_x": p.focal_x,
            "focal_y": p.focal_y,
        }
        for p, uname, display_name in rows
        if p.photo_url or p.thumbnail_url  # require an image — visual hook only
    ]

    return templates.TemplateResponse(
        request,
        "homepage.html",
        {
            "current_user": current_user,
            "featured": featured,
        },
    )


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    query = (q or "").strip()
    users, prints, users_by_id = [], [], {}

    if query:
        pattern = f"%{query}%"
        users = (
            db.query(User)
            .filter(or_(User.username.ilike(pattern), User.display_name.ilike(pattern)))
            .order_by(User.username)
            .limit(10)
            .all()
        )
        print_rows = (
            db.query(Print, User.username)
            .join(User, Print.user_id == User.id)
            .filter(
                Print.is_public == True,   # noqa: E712
                Print.queued == False,     # noqa: E712
                or_(Print.title.ilike(pattern), Print.designer.ilike(pattern)),
            )
            .order_by(Print.created_at.desc())
            .limit(24)
            .all()
        )
        prints = [{"print": p, "username": uname} for p, uname in print_rows]

    return templates.TemplateResponse(
        request,
        "search.html",
        {"current_user": current_user, "q": query, "users": users, "prints": prints},
    )


EXPLORE_LIMIT = 24
TRENDING_WINDOW_DAYS = 7


_EXPLORE_SORT = {
    "newest": (Print.created_at.desc(),),
    "oldest": (Print.created_at.asc(),),
    "rating": (nullslast(Print.rating.desc()),),
    "popular": (Print.like_count.desc(), Print.created_at.desc()),
}
# "trending" is handled separately (needs a recent-likes join), not in this dict.
_EXPLORE_SORTS = set(_EXPLORE_SORT) | {"trending"}


@router.get("/explore", response_class=HTMLResponse)
def explore(
    request: Request,
    page: int = 1,
    sort: str = "newest",
    category: Optional[str] = None,
    failed: Optional[str] = None,
    material: Optional[str] = None,
    fbrand: Optional[str] = None,
    printer: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    page = max(1, page)
    sort = sort if sort in _EXPLORE_SORTS else "newest"
    offset = (page - 1) * EXPLORE_LIMIT

    # Facet option lists (distinct values across the catalog — cheap, drive the
    # dropdowns). Active facet values are validated against these so unknown/junk
    # input is ignored rather than yielding a confusing empty page.
    material_opts = [m for (m,) in db.query(Filament.material).filter(Filament.material.isnot(None)).distinct().order_by(Filament.material) if m]
    fbrand_opts = [b for (b,) in db.query(Filament.brand).filter(Filament.brand.isnot(None)).distinct().order_by(Filament.brand) if b]
    printer_opts = [b for (b,) in db.query(Printer.brand).filter(Printer.brand.isnot(None)).distinct().order_by(Printer.brand) if b]
    material = material if material in material_opts else None
    fbrand = fbrand if fbrand in fbrand_opts else None
    printer = printer if printer in printer_opts else None

    q = (
        db.query(Print, User.username, User.avatar_url)
        .join(User, Print.user_id == User.id)
        .filter(
            Print.is_public == True,  # noqa: E712
            Print.queued == False,    # noqa: E712
            or_(Print.photo_url.isnot(None), Print.thumbnail_url.isnot(None)),
        )
    )
    category_filter = category if category and category != "all" else None
    failed_filter = failed == "1"
    if category_filter:
        q = q.filter(Print.category == category_filter)
    if failed_filter:
        q = q.filter(Print.status == "failed")

    # Material / filament-brand live on Filament, referenced by the Print.filament_ids
    # JSON array (no reverse index, not portably SQL-filterable). Resolve matching
    # filament IDs, then a lightweight scan of (id, filament_ids) over public prints
    # yields the qualifying print IDs — sort + pagination then run unchanged.
    if material or fbrand:
        mat_fids = (
            {fid for (fid,) in db.query(Filament.id).filter(Filament.material == material).all()}
            if material else None
        )
        brand_fids = (
            {fid for (fid,) in db.query(Filament.id).filter(Filament.brand == fbrand).all()}
            if fbrand else None
        )
        scan = db.query(Print.id, Print.filament_ids).filter(
            Print.is_public == True,   # noqa: E712
            Print.queued == False,     # noqa: E712
            or_(Print.photo_url.isnot(None), Print.thumbnail_url.isnot(None)),
        ).all()
        qualifying = []
        for pid, fids in scan:
            s = set(fids or [])
            if mat_fids is not None and not (s & mat_fids):
                continue
            if brand_fids is not None and not (s & brand_fids):
                continue
            qualifying.append(pid)
        q = q.filter(Print.id.in_(qualifying))

    if printer:
        q = q.join(Printer, Print.printer_id == Printer.id).filter(Printer.brand == printer)

    if sort == "trending":
        # Rank by engagement in the recent window, so a print with a few likes
        # this week outranks one with many lifetime likes from a year ago.
        # Portable across SQLite/Postgres: cutoff is a Python-computed bind param,
        # no DB-specific date arithmetic. Prints with no recent likes get rc=0 and
        # fall back to newest order — never an empty page.
        cutoff = datetime.utcnow() - timedelta(days=TRENDING_WINDOW_DAYS)
        recent = (
            db.query(Like.print_id.label("pid"), func.count(Like.id).label("rc"))
            .filter(Like.created_at >= cutoff)
            .group_by(Like.print_id)
            .subquery()
        )
        q = q.outerjoin(recent, Print.id == recent.c.pid).order_by(
            func.coalesce(recent.c.rc, 0).desc(), Print.created_at.desc()
        )
    else:
        q = q.order_by(*_EXPLORE_SORT[sort])

    rows = (
        q.offset(offset)
        .limit(EXPLORE_LIMIT + 1)
        .all()
    )
    has_next = len(rows) > EXPLORE_LIMIT
    rows = rows[:EXPLORE_LIMIT]
    prints = [
        {
            "id": p.id,
            "url_id": p.url_id,
            "title": p.title,
            "thumbnail": p.photo_url or p.thumbnail_url,
            "rating": p.rating,
            "username": uname,
            "avatar_url": avatar_url,
            "status": p.status,
            "focal_x": p.focal_x,
            "focal_y": p.focal_y,
            "like_count": p.like_count,
        }
        for p, uname, avatar_url in rows
    ]

    # Pre-build query strings so the template doesn't hand-concatenate params.
    # facet_qs = sort + facets (category pills append it, since they set category);
    # pager_qs = everything active incl. category/failed (the pager appends &page=N).
    def _qs(include_cat_failed: bool) -> str:
        pairs = []
        if sort != "newest":
            pairs.append(("sort", sort))
        if include_cat_failed:
            if category_filter:
                pairs.append(("category", category_filter))
            if failed_filter:
                pairs.append(("failed", "1"))
        if material:
            pairs.append(("material", material))
        if fbrand:
            pairs.append(("fbrand", fbrand))
        if printer:
            pairs.append(("printer", printer))
        return urlencode(pairs)

    return templates.TemplateResponse(
        request,
        "explore.html",
        {
            "current_user": current_user,
            "prints": prints,
            "page": page,
            "has_next": has_next,
            "has_prev": page > 1,
            "sort": sort,
            "category": category_filter,
            "failed": failed_filter,
            "categories": PRINT_CATEGORIES,
            "material": material,
            "fbrand": fbrand,
            "printer": printer,
            "material_opts": material_opts,
            "fbrand_opts": fbrand_opts,
            "printer_opts": printer_opts,
            "facet_qs": _qs(False),
            "pager_qs": _qs(True),
            "has_facets": bool(material or fbrand or printer),
        },
    )


# ============== Public filament preview (no login) ==============

@router.get("/preview", response_class=HTMLResponse)
def public_preview(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """No-login filament preview studio — catalog filaments + upload-your-own,
    all client-side. Top-of-funnel: non-users can try it before signing up."""
    if not filament_preview_enabled():
        return RedirectResponse("/", status_code=303)
    catalog = build_preview_catalog(db, exclude_keys=set(), buy_base="/preview/buy")
    return templates.TemplateResponse(
        request, "preview_public.html",
        {
            "current_user": current_user,
            "filaments": [],
            "catalog": catalog,
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
        },
    )


@router.get("/preview/buy")
def public_preview_buy(
    brand: str = "",
    material: str = "",
    color: str = "",
    finish: str = "",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Tracked Buy for a catalog filament from the public demo (anonymous OK)."""
    target = store_search_url(brand, material, color, finish)
    if not target:
        return RedirectResponse("/preview", status_code=303)
    from filament_import_service import detect_store
    store = detect_store(target)
    db.add(AffiliateClick(user_id=(current_user.id if current_user else None), filament_id=None, store=store or None, surface="preview_public_buy"))
    db.commit()
    return RedirectResponse(target, status_code=302)


# ============== Printed Instruments Index (public, flag-hidden) ==============

_PLAYABILITY_OPTS = {"0": "Decoration", "1": "Plays, with caveats", "2": "Playable", "3": "Verified on video"}


@router.get("/instruments", response_class=HTMLResponse)
def instruments_index(
    request: Request,
    q: str = "",
    family: str = "",
    playability: str = "",
    notify: str = "",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Curated registry of 3D-printable instruments — no login required.
    Flag-hidden on prod until all 4 slices land (see instruments_index_enabled).
    Slice 3: real cost computation + staleness. Slice 2b: search/filter."""
    if not instruments_index_enabled():
        return RedirectResponse("/", status_code=303)

    listed = (
        db.query(RegistryEntry)
        .filter(RegistryEntry.vertical == "instruments", RegistryEntry.status == "listed")
        .order_by(RegistryEntry.name)
        .all()
    )
    frontier = (
        db.query(RegistryEntry)
        .filter(RegistryEntry.vertical == "instruments", RegistryEntry.status == "frontier")
        .order_by(RegistryEntry.name)
        .all()
    )

    # Facet option lists driven by whatever's actually in the data (mirrors the
    # Explore facets pattern) — unknown/junk query values are ignored rather
    # than yielding a confusing empty page.
    family_opts = [f for (f,) in db.query(RegistryEntry.family).filter(RegistryEntry.vertical == "instruments", RegistryEntry.status == "listed", RegistryEntry.family.isnot(None)).distinct().order_by(RegistryEntry.family) if f]
    family = family if family in family_opts else ""
    playability = playability if playability in _PLAYABILITY_OPTS else ""
    q_norm = q.strip().lower()

    def _matches_text(entry, *fields):
        return any(q_norm in (getattr(entry, f, None) or "").lower() for f in fields)

    if q_norm:
        listed = [e for e in listed if _matches_text(e, "name", "designer", "note")]
    if family:
        listed = [e for e in listed if e.family == family]
    if playability:
        listed = [e for e in listed if str(e.function_axis) == playability]

    has_facets = bool(q_norm or family or playability)
    # Frontier entries carry no family/playability taxonomy (that's the point —
    # nothing confidently fits those axes yet), so a facet filter hides the
    # section entirely rather than showing it half-filtered; text search still
    # applies since frontier rows have real names/gap text to match against.
    if family or playability:
        frontier = []
    elif q_norm:
        frontier = [e for e in frontier if _matches_text(e, "name", "gap_why", "gap_closest")]

    price_table = {p.material: p.price_per_kg for p in db.query(FilamentPrice).all()}
    pricing = {}
    audio = {}
    for entry in listed:
        costs = compute_costs(entry, price_table)
        pricing[entry.id] = {
            **costs,
            "retail_budget_state": staleness_state(entry.retail_budget_checked_at),
            "retail_premium_state": staleness_state(entry.retail_premium_checked_at),
        }

        # Blind A/B: only render when both clips exist (honesty pattern —
        # no placeholder player). Position is shuffled per-request so the
        # printed clip isn't predictably always slot A/B across visits —
        # the "kind" itself never reaches the template/DOM, only a/b slots.
        media = entry.media or []
        printed_clip = next((m for m in media if m.get("kind") == "audio_printed"), None)
        real_clip = next((m for m in media if m.get("kind") == "audio_real"), None)
        if printed_clip and real_clip:
            pair = [("printed", printed_clip), ("real", real_clip)]
            random.shuffle(pair)
            audio[entry.id] = {
                "clip_a_url": pair[0][1]["url"],
                "clip_b_url": pair[1][1]["url"],
                "real_slot": "a" if pair[0][0] == "real" else "b",
                "phrase": printed_clip.get("phrase"),
            }

    return templates.TemplateResponse(
        request, "instruments_index.html",
        {
            "current_user": current_user,
            "families": _group_by_family(listed),
            "frontier": frontier,
            "pricing": pricing,
            "audio": audio,
            "q": q,
            "family": family,
            "family_opts": family_opts,
            "playability": playability,
            "playability_opts": list(_PLAYABILITY_OPTS.items()),
            "has_facets": has_facets,
            "notify": notify if notify in {"ok", "invalid"} else "",
            "app_url": os.environ.get("APP_URL", "https://printshelf.app"),
        },
    )


@router.post("/instruments/notify", response_class=RedirectResponse)
def instruments_notify(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    """Notify-me signup (Slice 4) — no login required, matches the page's own gate."""
    if not instruments_index_enabled():
        return RedirectResponse("/", status_code=303)

    email_n = email.strip().lower()
    if "@" not in email_n or "." not in email_n.split("@")[-1] or len(email_n) > 255:
        return RedirectResponse("/instruments?notify=invalid", status_code=303)

    existing = db.query(InstrumentsNotifySignup).filter(InstrumentsNotifySignup.email == email_n).first()
    if not existing:
        db.add(InstrumentsNotifySignup(email=email_n))
        db.commit()
    return RedirectResponse("/instruments?notify=ok", status_code=303)


# ============== PWA: service worker + offline page ==============

# Bump CACHE version when the SW logic or precache list changes, so clients
# fetch the new worker and drop the stale cache on activate.
_SERVICE_WORKER_JS = """\
const CACHE = 'printshelf-v17';
const OFFLINE_URL = '/offline';
const PRECACHE = ['/offline', '/static/app.css?v=29'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  // Navigations: network-first, fall back to the cached offline page.
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  // Same-origin static assets: cache-first, then populate the cache.
  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return resp;
      }))
    );
  }
});
"""


@router.get("/sw.js")
def service_worker():
    # Served from root so its scope is the whole site (no Service-Worker-Allowed
    # header needed). no-cache so worker updates propagate on next load.
    return Response(
        _SERVICE_WORKER_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/offline", response_class=HTMLResponse)
def offline_page(request: Request):
    return templates.TemplateResponse(request, "offline.html", {})


@router.get("/terms", response_class=HTMLResponse)
def terms_of_service(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    return templates.TemplateResponse(
        request, "terms.html", {"current_user": current_user},
    )


@router.get("/share", response_class=HTMLResponse)
def share_capture(
    request: Request,
    url: str = "",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Mobile share-sheet landing (like the SS Books ?share= flow): log a shared
    model link to the shelf. Auth is the browser session — no API key needed."""
    from urllib.parse import quote
    from fastapi import HTTPException as _HTTPException
    if current_user is None:
        return RedirectResponse("/login?next=" + quote("/share?url=" + url, safe=""), status_code=303)
    base_ctx = {"request": request, "current_user": current_user,
                "app_url": os.environ.get("APP_URL", "https://printshelf.app")}
    link = (url or "").strip()
    if not link:
        return templates.TemplateResponse(
            request, "share_result.html",
            {**base_ctx, "error": "No link was shared. Open a model and use Share \u2192 Add to PrintShelf."})
    from routes.prints import log_print_from_model_url
    try:
        pr, deduped = log_print_from_model_url(db, current_user, link)
    except _HTTPException as e:
        return templates.TemplateResponse(
            request, "share_result.html",
            {**base_ctx, "error": e.detail, "attempted_url": link})
    return templates.TemplateResponse(
        request, "share_result.html",
        {**base_ctx, "print_": pr, "deduped": deduped, "username": current_user.username})


@router.get("/sitemap.xml")
def sitemap(
    request: Request,
    db: Session = Depends(get_db),
):
    app_url = os.environ.get("APP_URL", "https://printshelf.app").rstrip("/")
    static_urls = ["/", "/explore", "/signup", "/login"]

    user_rows = (
        db.query(User.username)
        .join(Print, Print.user_id == User.id)
        .filter(Print.is_public == True, Print.queued == False)  # noqa: E712
        .distinct()
        .all()
    )
    usernames = [r.username for r in user_rows]

    print_rows = (
        db.query(Print.id, Print.title, User.username)
        .join(User, Print.user_id == User.id)
        .filter(Print.is_public == True, Print.queued == False)  # noqa: E712
        .order_by(Print.created_at.desc())
        .limit(5000)
        .all()
    )

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in static_urls:
        lines.append(f"  <url><loc>{app_url}{path}</loc></url>")
    for uname in usernames:
        lines.append(f"  <url><loc>{app_url}/@{uname}</loc></url>")
    for print_id, title, uname in print_rows:
        url_id = print_url_id(print_id, title)
        lines.append(f"  <url><loc>{app_url}/@{uname}/prints/{url_id}</loc></url>")
    lines.append("</urlset>")

    return Response("\n".join(lines), media_type="application/xml")


@router.get("/developers", response_class=HTMLResponse)
def developers(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    return templates.TemplateResponse(
        request, "developers.html", {"current_user": current_user},
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy_policy(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_web_optional),
):
    """Privacy policy page. Linked from the Chrome Web Store listing and
    from the extension's options page. Kept terse and accurate — the
    Council flagged that an over-researched GDPR/CCPA draft is a rabbit
    hole for a solo product at this stage."""
    return templates.TemplateResponse(
        request, "privacy.html", {"current_user": current_user},
    )
