"""Unit tests for affiliate.py's tag-injection logic — no server/DB required.

Run: python backend/scripts/test_affiliate.py

Each store's mechanism is exercised with its env var(s) set (tagged case) and
unset (bare-passthrough case), so a store silently regressing to the wrong
mechanism (e.g. MatterHackers moving from direct to Awin) fails loudly here
instead of shipping untagged links.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib

passed = 0
failed = 0


def _reload_affiliate(env: dict):
    """Reload affiliate.py with a clean env so cached module state never leaks
    between cases (apply_affiliate reads os.environ live, but reload keeps
    every case explicit about exactly which vars are set)."""
    for key in (
        "AMAZON_AFFILIATE_TAG", "BAMBU_AFFILIATE_REF", "POLYMAKER_AFFILIATE_REF",
        "SUNLU_AFFILIATE_REF", "FLASHFORGE_IMPACT_PID", "AWIN_AFFILIATE_ID",
        "ANYCUBIC_AWIN_MERCHANT_ID", "MATTERHACKERS_AWIN_MERCHANT_ID",
        "ESUN_AWIN_MERCHANT_ID", "WEST3D_COLLABS_CODE",
    ):
        os.environ.pop(key, None)
    os.environ.update(env)
    import affiliate
    return importlib.reload(affiliate)


def check(label: str, actual, expected):
    global passed, failed
    ok = actual == expected
    if ok:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}\n      expected: {expected}\n      actual:   {actual}")


print("== MatterHackers: Awin, not direct ==")
aff = _reload_affiliate({"AWIN_AFFILIATE_ID": "2576687", "MATTERHACKERS_AWIN_MERCHANT_ID": "97427"})
check(
    "saved product URL -> Awin-wrapped",
    aff.apply_affiliate("https://www.matterhackers.com/store/c/some-filament"),
    "https://www.awin1.com/cread.php?awinmid=97427&awinaffid=2576687&"
    "ued=https%3A%2F%2Fwww.matterhackers.com%2Fstore%2Fc%2Fsome-filament",
)
check(
    "store-search fallback -> also Awin-wrapped",
    aff.store_search_url("MatterHackers", material="PLA", color="Black"),
    "https://www.awin1.com/cread.php?awinmid=97427&awinaffid=2576687&"
    "ued=https%3A%2F%2Fwww.matterhackers.com%2Fstore%2Fc%3Fq%3DPLA%2BBlack",
)
check(
    "MATTERHACKERS_AFFILIATE_REF (old direct env var) has no effect anymore",
    _reload_affiliate({
        "AWIN_AFFILIATE_ID": "2576687", "MATTERHACKERS_AWIN_MERCHANT_ID": "97427",
    }).apply_affiliate("https://www.matterhackers.com/store/c/x") ==
    _reload_affiliate({
        "AWIN_AFFILIATE_ID": "2576687", "MATTERHACKERS_AWIN_MERCHANT_ID": "97427",
        "MATTERHACKERS_AFFILIATE_REF": "should-be-ignored",
    }).apply_affiliate("https://www.matterhackers.com/store/c/x"),
    True,
)

print("== MatterHackers: bare passthrough when unset ==")
aff = _reload_affiliate({})
check(
    "no AWIN_AFFILIATE_ID / no merchant id -> bare URL, no crash",
    aff.apply_affiliate("https://www.matterhackers.com/store/c/x"),
    "https://www.matterhackers.com/store/c/x",
)
aff = _reload_affiliate({"AWIN_AFFILIATE_ID": "2576687"})
check(
    "publisher id set but merchant id missing -> bare URL, no crash",
    aff.apply_affiliate("https://www.matterhackers.com/store/c/x"),
    "https://www.matterhackers.com/store/c/x",
)

print("== No regression: other stores still tag correctly ==")
aff = _reload_affiliate({
    "AMAZON_AFFILIATE_TAG": "printshelf-20",
    "BAMBU_AFFILIATE_REF": "bambu-ref",
    "POLYMAKER_AFFILIATE_REF": "poly-ref",
    "SUNLU_AFFILIATE_REF": "sunlu-ref",
    "FLASHFORGE_IMPACT_PID": "7371845",
    "AWIN_AFFILIATE_ID": "2576687",
    "ANYCUBIC_AWIN_MERCHANT_ID": "69360",
    "MATTERHACKERS_AWIN_MERCHANT_ID": "97427",
})
check(
    "Amazon -> ?tag=",
    aff.apply_affiliate("https://www.amazon.com/dp/B000123456"),
    "https://www.amazon.com/dp/B000123456?tag=printshelf-20",
)
check(
    "Bambu Lab -> ?ref= (direct)",
    aff.apply_affiliate("https://us.store.bambulab.com/products/pla-basic"),
    "https://us.store.bambulab.com/products/pla-basic?ref=bambu-ref",
)
check(
    "Polymaker -> ?ref= (direct)",
    aff.apply_affiliate("https://us.polymaker.com/products/polyterra-pla"),
    "https://us.polymaker.com/products/polyterra-pla?ref=poly-ref",
)
check(
    "SUNLU -> ?sca_ref= (direct)",
    aff.apply_affiliate("https://store.sunlu.com/products/pla"),
    "https://store.sunlu.com/products/pla?sca_ref=sunlu-ref",
)
check(
    "Anycubic -> Awin-wrapped (unchanged)",
    aff.apply_affiliate("https://store.anycubic.com/products/pla"),
    "https://www.awin1.com/cread.php?awinmid=69360&awinaffid=2576687&"
    "ued=https%3A%2F%2Fstore.anycubic.com%2Fproducts%2Fpla",
)
check(
    "FlashForge -> Impact irpid (unchanged)",
    aff.apply_affiliate("https://www.flashforge.com/product/pla"),
    "https://www.flashforge.com/product/pla?irpid=7371845&irgwc=1&afsrc=1&utm_source=impact",
)

print("\n== West3D: Shopify Collabs discount-redirect ==")
aff = _reload_affiliate({"WEST3D_COLLABS_CODE": "PLUGGEDIN3D"})
check(
    "West3D product -> /discount/<code>?redirect=<path>",
    aff.apply_affiliate("https://west3d.com/products/ambrosia-asa"),
    "https://west3d.com/discount/PLUGGEDIN3D?redirect=%2Fproducts%2Fambrosia-asa",
)
check(
    "West3D product w/ variant -> query preserved (encoded)",
    aff.apply_affiliate("https://west3d.com/products/ambrosia-asa?variant=123"),
    "https://west3d.com/discount/PLUGGEDIN3D?redirect=%2Fproducts%2Fambrosia-asa%3Fvariant%3D123",
)
check(
    "West3D is an allowed link domain",
    aff.is_allowed_link_domain("https://west3d.com/products/x"),
    True,
)
aff = _reload_affiliate({})
check(
    "West3D bare passthrough when code unset (no crash)",
    aff.apply_affiliate("https://west3d.com/products/ambrosia-asa"),
    "https://west3d.com/products/ambrosia-asa",
)

print(f"\n{'=' * 40}\n  {passed}/{passed + failed} passed\n{'=' * 40}")
sys.exit(1 if failed else 0)
