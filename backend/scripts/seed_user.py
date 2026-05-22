"""Seed a PrintShelf user with printers, filaments, and prints from a YAML file.

Idempotent-ish: if the user already exists, logs in instead of registering.
Filaments are de-duped by (brand, material, color_name).
Printers are de-duped by name.

Usage:
    python seed_user.py --config seed/cam.yaml --base https://staging.printshelf.app
    python seed_user.py --config seed/cam.yaml --base https://printshelf.app

Pass --dry-run to print the plan without making API calls.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml


class SeedError(Exception):
    pass


def _auth(client: httpx.Client, base: str, user: dict) -> tuple[str, str, dict]:
    """Register or log in. Returns (token, api_key, user_dict)."""
    creds = {"email": user["email"], "password": user["password"]}
    register_payload = {**creds, "username": user["username"]}
    if user.get("display_name"):
        register_payload["display_name"] = user["display_name"]

    r = client.post(f"{base}/api/auth/register", json=register_payload)
    if r.status_code == 200:
        data = r.json()
        print(f"  registered: {data['user']['username']}")
        return data["token"], data["user"]["apiKey"], data["user"]

    # 409 = email or username already taken — try logging in
    if r.status_code == 409:
        r = client.post(f"{base}/api/auth/login", json=creds)
        if r.status_code == 200:
            data = r.json()
            print(f"  logged in: {data['user']['username']}")
            return data["token"], data["user"]["apiKey"], data["user"]
        raise SeedError(f"login failed: {r.status_code} {r.text}")

    raise SeedError(f"register failed: {r.status_code} {r.text}")


def _patch_profile(client: httpx.Client, base: str, token: str, user_cfg: dict) -> None:
    body = {k: user_cfg[k] for k in ("display_name", "bio", "avatar_url") if user_cfg.get(k)}
    if not body:
        return
    r = client.patch(
        f"{base}/api/auth/me",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code != 200:
        raise SeedError(f"profile update failed: {r.status_code} {r.text}")
    print(f"  profile updated: {sorted(body.keys())}")


def _ensure_printers(client: httpx.Client, base: str, token: str, printers_cfg: list[dict]) -> dict[str, int]:
    """Returns {printer_name: printer_id}. De-duped by name."""
    hdr = {"Authorization": f"Bearer {token}"}
    existing = {p["name"]: p["id"] for p in client.get(f"{base}/api/printers", headers=hdr).json()["items"]}
    out = dict(existing)
    for cfg in printers_cfg:
        name = cfg["name"]
        if name in out:
            continue
        body = {"name": name, "brand": cfg.get("brand"), "model": cfg.get("model")}
        r = client.post(f"{base}/api/printers", json=body, headers=hdr)
        if r.status_code != 201:
            raise SeedError(f"create printer {name!r}: {r.status_code} {r.text}")
        out[name] = r.json()["id"]
        print(f"  + printer: {name}")
    return out


def _ensure_filaments(client: httpx.Client, base: str, token: str, filaments_cfg: list[dict]) -> dict[str, int]:
    """Returns {filament_key: filament_id}. De-duped by (brand, material, color_name)."""
    hdr = {"Authorization": f"Bearer {token}"}
    existing_items = client.get(f"{base}/api/filaments?limit=200", headers=hdr).json()["items"]
    existing_by_sig = {(f["brand"], f["material"], f.get("colorName")): f["id"] for f in existing_items}
    out: dict[str, int] = {}
    for cfg in filaments_cfg:
        sig = (cfg["brand"], cfg["material"], cfg.get("color_name"))
        if sig in existing_by_sig:
            out[cfg["key"]] = existing_by_sig[sig]
            continue
        body = {
            "brand": cfg["brand"],
            "material": cfg["material"],
            "color_name": cfg.get("color_name"),
            "color_hex": cfg.get("color_hex"),
            "diameter": cfg.get("diameter", 1.75),
            "status": cfg.get("status", "own"),
            "source_url": cfg.get("source_url"),
            "notes": cfg.get("notes"),
        }
        r = client.post(f"{base}/api/filaments", json=body, headers=hdr)
        if r.status_code != 201:
            raise SeedError(f"create filament {cfg['key']!r}: {r.status_code} {r.text}")
        fid = r.json()["id"]
        out[cfg["key"]] = fid
        existing_by_sig[sig] = fid
        print(f"  + filament: {cfg['key']} → id={fid}")
    return out


def _create_prints(
    client: httpx.Client,
    base: str,
    token: str,
    prints_cfg: list[dict],
    printer_ids: dict[str, int],
    filament_ids: dict[str, int],
) -> int:
    hdr = {"Authorization": f"Bearer {token}"}
    created = 0
    for cfg in prints_cfg:
        fil_keys = cfg.get("filaments") or []
        try:
            fil_ids = [filament_ids[k] for k in fil_keys]
        except KeyError as e:
            raise SeedError(f"print {cfg.get('title')!r} references unknown filament key {e}") from None
        body: dict[str, Any] = {
            "title": cfg["title"],
            "designer": cfg.get("designer"),
            "source_url": cfg.get("source_url"),
            "source_platform": cfg.get("source_platform", "manual"),
            "thumbnail_url": cfg.get("thumbnail_url"),
            "photo_url": cfg.get("photo_url"),
            "printer_id": printer_ids.get(cfg["printer"]) if cfg.get("printer") else None,
            "filament_ids": fil_ids,
            "status": cfg.get("status", "printed"),
            "rating": cfg.get("rating"),
            "notes": cfg.get("notes"),
            "queued": False,
            "is_public": cfg.get("is_public", True),
        }
        if cfg.get("print_date"):
            body["print_date"] = str(cfg["print_date"])
        body = {k: v for k, v in body.items() if v is not None}
        r = client.post(f"{base}/api/prints", json=body, headers=hdr)
        if r.status_code != 201:
            raise SeedError(f"create print {cfg.get('title')!r}: {r.status_code} {r.text}")
        created += 1
        print(f"  + print: {cfg['title']}")
    return created


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="path to YAML seed file")
    ap.add_argument("--base", default="http://127.0.0.1:8765", help="API base URL")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 2
    cfg = yaml.safe_load(cfg_path.read_text())

    user_cfg = cfg["user"]
    printers_cfg = cfg.get("printers") or []
    filaments_cfg = cfg.get("filaments") or []
    prints_cfg = cfg.get("prints") or []

    print(f"Seeding {user_cfg['username']!r} against {args.base}")
    print(f"  printers: {len(printers_cfg)}, filaments: {len(filaments_cfg)}, prints: {len(prints_cfg)}")

    if args.dry_run:
        print("(dry-run: stopping here)")
        return 0

    with httpx.Client(timeout=30.0) as client:
        token, api_key, _ = _auth(client, args.base, user_cfg)
        _patch_profile(client, args.base, token, user_cfg)
        printer_ids = _ensure_printers(client, args.base, token, printers_cfg)
        filament_ids = _ensure_filaments(client, args.base, token, filaments_cfg)
        created = _create_prints(client, args.base, token, prints_cfg, printer_ids, filament_ids)

    print()
    print(f"Done. Created {created} print(s). API key for {user_cfg['username']!r}:")
    print(f"  {api_key}")
    print(f"View at: {args.base.replace('/api', '')}/u/{user_cfg['username']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
