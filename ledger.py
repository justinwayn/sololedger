"""SoloLedger P&L math. Deterministic, integer cents throughout. No LLM, no network."""
import calendar
from datetime import date

import db


def fmt_cents(cents):
    """12345 -> '$123.45'; -500 -> '-$5.00'."""
    sign = "-" if cents < 0 else ""
    c = abs(int(cents))
    return f"{sign}${c // 100}.{c % 100:02d}"


def month_range(yyyymm):
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    days = calendar.monthrange(y, m)[1]
    return f"{yyyymm}-01", f"{yyyymm}-{days:02d}"


def monthly_pnl(yyyymm, stripe_revenue_cents=None):
    """True-profit P&L for one month.

    stripe_revenue_cents: optional dict {product: cents} from live Stripe sync.
    Manual/demo revenue rows in the DB always count; stripe figures are added
    on top only when provided (live mode).
    """
    expenses = db.list_expenses(month=yyyymm)
    rev_rows = db.list_revenue(month=yyyymm)

    by_category = {c: 0 for c in db.CATEGORIES}
    total_expenses = 0
    for e in expenses:
        by_category[e["category"]] += e["amount_cents"]
        total_expenses += e["amount_cents"]

    by_product_rev = {}
    total_revenue = 0
    for r in rev_rows:
        by_product_rev[r["product"]] = by_product_rev.get(r["product"], 0) + r["amount_cents"]
        total_revenue += r["amount_cents"]

    if stripe_revenue_cents:
        for product, cents in stripe_revenue_cents.items():
            by_product_rev[product] = by_product_rev.get(product, 0) + cents
            total_revenue += cents

    # per-product expense split
    by_product_exp = {}
    for e in expenses:
        by_product_exp[e["product"]] = by_product_exp.get(e["product"], 0) + e["amount_cents"]

    products = sorted(set(list(by_product_rev.keys()) + list(by_product_exp.keys())))
    per_product = []
    for p in products:
        rev = by_product_rev.get(p, 0)
        exp = by_product_exp.get(p, 0)
        # shared ("all") expenses are attributed proportionally by revenue share
        per_product.append({"product": p, "revenue_cents": rev,
                            "expenses_cents": exp, "profit_cents": rev - exp})

    # Attribute shared expenses proportionally for a fair per-product view
    shared = by_product_exp.get("all", 0)
    if shared and total_revenue > 0:
        for pp in per_product:
            if pp["product"] == "all":
                continue
            share = pp["revenue_cents"] / total_revenue
            attr = round(shared * share)
            pp["expenses_cents"] += attr
            pp["profit_cents"] = pp["revenue_cents"] - pp["expenses_cents"]

    profit = total_revenue - total_expenses
    margin_pct = round(1000 * profit / total_revenue) / 10 if total_revenue else 0.0

    return {
        "month": yyyymm,
        "revenue_cents": total_revenue,
        "expenses_cents": total_expenses,
        "profit_cents": profit,
        "margin_pct": margin_pct,
        "by_category_cents": by_category,
        "per_product": per_product,
        "expense_count": len(expenses),
        "revenue_count": len(rev_rows),
    }


def rent_covered(yyyymm, stripe_revenue_cents=None):
    """'Rent covered?' — monthly profit vs founder's monthly nut."""
    pnl = monthly_pnl(yyyymm, stripe_revenue_cents)
    nut = int(db.get_setting("monthly_nut_cents", "0") or 0)
    profit = pnl["profit_cents"]
    covered = profit >= nut if nut > 0 else None
    return {
        "month": yyyymm,
        "profit_cents": profit,
        "monthly_nut_cents": nut,
        "covered": covered,
        "shortfall_cents": max(0, nut - profit),
        "surplus_cents": max(0, profit - nut),
    }


def runway(stripe_revenue_cents=None):
    """Runway from current monthly profit. Uses the current calendar month."""
    today = date.today().strftime("%Y-%m")
    pnl = monthly_pnl(today, stripe_revenue_cents)
    cash = int(db.get_setting("cash_on_hand_cents", "0") or 0)
    monthly = pnl["profit_cents"]
    if monthly >= 0:
        return {"cash_on_hand_cents": cash, "monthly_profit_cents": monthly,
                "runway_months": None, "status": "profitable",
                "note": "Profitable this month — runway is infinite at this pace."}
    burn = -monthly
    months = round(cash / burn, 1) if burn else 0
    return {"cash_on_hand_cents": cash, "monthly_profit_cents": monthly,
            "runway_months": months, "status": "burning",
            "note": f"At this burn, cash lasts ~{months} months."}


def top_cost_drivers(yyyymm, limit=3):
    pnl = monthly_pnl(yyyymm)
    ranked = sorted(pnl["by_category_cents"].items(), key=lambda kv: kv[1], reverse=True)
    return [{"category": c, "amount_cents": a} for c, a in ranked[:limit] if a > 0]
