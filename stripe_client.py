"""Stripe revenue sync for SoloLedger.

Modes (SOLOLEDGER_MODE):
  demo (default) — deterministic synthetic revenue rows, nothing leaves the machine.
  live           — read-only fetch from Stripe REST API using a RESTRICTED key.
                   Full sk_live_ keys are refused unless SOLOLEDGER_ALLOW_LIVE_KEY=1.
"""
import calendar
import os
from datetime import date, timedelta

import db

MODE = os.environ.get("SOLOLEDGER_MODE", "demo").strip().lower()
STRIPE_KEY = os.environ.get("SOLOLEDGER_STRIPE_KEY", "").strip()
ALLOW_LIVE_KEY = os.environ.get("SOLOLEDGER_ALLOW_LIVE_KEY", "0") == "1"

PRODUCTS = ["api-tool", "template-pack", "micro-saas"]


def _month_bounds(yyyymm):
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    days = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, days)


def seed_demo(yyyymm):
    """Deterministic demo revenue: 3 products, plausible indie numbers."""
    db.clear_source("demo")
    start, end = _month_bounds(yyyymm)
    # fixed per-product daily revenue (cents) — deterministic, no randomness
    daily = {"api-tool": 4120, "template-pack": 1890, "micro-saas": 7350}
    d = start
    while d <= end:
        for product, cents in daily.items():
            # weekday/weekend wobble, still deterministic
            wobble = 100 if d.weekday() < 5 else -80
            db.add_revenue(d.isoformat(), max(0, cents + wobble),
                           product=product, source="demo",
                           note="demo synthetic revenue")
        d += timedelta(days=1)
    # demo expenses so the P&L is interesting out of the box
    if not db.list_expenses(month=yyyymm):
        demo_exp = [
            ("hosting", 12000, "Vercel Pro + Supabase"),
            ("apis", 18450, "OpenAI API usage"),
            ("tools", 2900, "Resend + Plausible"),
            ("fees", 7310, "Stripe processing fees"),
            ("contractors", 25000, "Part-time designer"),
        ]
        for cat, cents, note in demo_exp:
            db.add_expense(f"{yyyymm}-05", cat, cents, product="all", note=note)


def fetch_live_month(yyyymm):
    """Read-only Stripe revenue for a month. Returns {product: cents}.

    Uses Balance Transactions (requires only read access) summed as net volume.
    Product attribution: live Stripe data lands under product 'stripe' — the
    founder renames/tags products in the dashboard.
    """
    if MODE != "live":
        raise RuntimeError("live fetch requires SOLOLEDGER_MODE=live")
    if not STRIPE_KEY:
        raise RuntimeError("SOLOLEDGER_STRIPE_KEY is not set")
    if STRIPE_KEY.startswith("sk_live_") and not ALLOW_LIVE_KEY:
        raise RuntimeError("refusing full sk_live_ key without SOLOLEDGER_ALLOW_LIVE_KEY=1; "
                           "use a restricted key instead")

    import requests  # local import: only needed in live mode

    start, end = _month_bounds(yyyymm)
    created_gte = int(start.strftime("%s"))
    created_lte = int((end + timedelta(days=1)).strftime("%s"))

    total = 0
    url = "https://api.stripe.com/v1/balance_transactions"
    params = {"limit": 100, "created[gte]": created_gte, "created[lte]": created_lte,
              "type": "charge"}
    headers = {"Authorization": f"Bearer {STRIPE_KEY}"}
    while url:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"stripe api error {r.status_code}: {r.text[:200]}")
        data = r.json()
        for tx in data.get("data", []):
            if tx.get("type") == "charge" and tx.get("status") == "available":
                total += int(tx.get("net", 0))
        if data.get("has_more"):
            last = data["data"][-1]["id"]
            params = dict(params, starting_after=last)
        else:
            url = None
    return {"stripe": total}


def sync_month(yyyymm):
    """Refresh revenue rows for a month from the active source. Returns summary."""
    if MODE == "live":
        per_product = fetch_live_month(yyyymm)
        db.clear_source("stripe")
        start, _ = _month_bounds(yyyymm)
        for product, cents in per_product.items():
            if cents:
                db.add_revenue(start.isoformat(), cents, product=product,
                               source="stripe", note="stripe balance transactions (net)")
        return {"mode": "live", "month": yyyymm, "revenue_cents": sum(per_product.values())}
    seed_demo(yyyymm)
    rows = db.list_revenue(month=yyyymm)
    return {"mode": "demo", "month": yyyymm,
            "revenue_cents": sum(r["amount_cents"] for r in rows)}
