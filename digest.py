"""Weekly profit snapshot: renders kept/spent/top-cost-drivers as text + HTML.

Send via Resend when RESEND_API_KEY is set; otherwise returns the rendered
content so the caller (or GitHub Actions cron) can see what would go out.
No spend, no LLM — pure deterministic math.
"""
import os
from datetime import date

import db
import ledger

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
DIGEST_TO = os.environ.get("SOLOLEDGER_DIGEST_TO", "").strip()
DIGEST_FROM = os.environ.get("SOLOLEDGER_DIGEST_FROM", "SoloLedger <digest@sololedger.app>")


def _last_full_month():
    y, m = date.today().year, date.today().month
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def build_snapshot(yyyymm=None):
    yyyymm = yyyymm or _last_full_month()
    pnl = ledger.monthly_pnl(yyyymm)
    rent = ledger.rent_covered(yyyymm)
    drivers = ledger.top_cost_drivers(yyyymm)

    kept = pnl["profit_cents"]
    spent = pnl["expenses_cents"]
    rev = pnl["revenue_cents"]

    if rent["covered"] is True:
        verdict = f"RENT COVERED — {ledger.fmt_cents(rent['surplus_cents'])} left over."
    elif rent["covered"] is False:
        verdict = (f"RENT NOT COVERED — short by {ledger.fmt_cents(rent['shortfall_cents'])} "
                   f"(nut is {ledger.fmt_cents(rent['monthly_nut_cents'])}).")
    else:
        verdict = "Set your monthly nut in Settings to get the rent-covered verdict."

    driver_lines = [f"- {d['category']}: {ledger.fmt_cents(d['amount_cents'])}" for d in drivers]
    drivers_txt = "\n".join(driver_lines) if driver_lines else "- no expenses logged"

    text = f"""SoloLedger weekly snapshot — {yyyymm}

Kept:   {ledger.fmt_cents(kept)}  (margin {pnl['margin_pct']}%)
Spent:  {ledger.fmt_cents(spent)}
Revenue:{ledger.fmt_cents(rev).rjust(9)}

{verdict}

Top cost drivers:
{drivers_txt}

Per product:
"""
    for pp in pnl["per_product"]:
        text += (f"- {pp['product']}: rev {ledger.fmt_cents(pp['revenue_cents'])}, "
                 f"cost {ledger.fmt_cents(pp['expenses_cents'])}, "
                 f"kept {ledger.fmt_cents(pp['profit_cents'])}\n")

    html = f"""<h2>SoloLedger weekly snapshot — {yyyymm}</h2>
<p><b>Kept:</b> {ledger.fmt_cents(kept)} (margin {pnl['margin_pct']}%)<br>
<b>Spent:</b> {ledger.fmt_cents(spent)}<br>
<b>Revenue:</b> {ledger.fmt_cents(rev)}</p>
<p><b>{verdict}</b></p>
<h3>Top cost drivers</h3><ul>
{''.join(f"<li>{d['category']}: {ledger.fmt_cents(d['amount_cents'])}</li>" for d in drivers)}
</ul><h3>Per product</h3><ul>
{''.join(f"<li>{pp['product']}: kept {ledger.fmt_cents(pp['profit_cents'])} on {ledger.fmt_cents(pp['revenue_cents'])} revenue</li>" for pp in pnl['per_product'])}
</ul>"""
    return {"month": yyyymm, "subject": f"SoloLedger snapshot — {yyyymm}: kept {ledger.fmt_cents(kept)}",
            "text": text, "html": html}


def send_snapshot(yyyymm=None):
    snap = build_snapshot(yyyymm)
    if not RESEND_API_KEY or not DIGEST_TO:
        return {"sent": False, "reason": "RESEND_API_KEY or SOLOLEDGER_DIGEST_TO not set",
                "snapshot": snap}
    import requests
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        json={"from": DIGEST_FROM, "to": [DIGEST_TO],
              "subject": snap["subject"], "text": snap["text"], "html": snap["html"]},
        timeout=20,
    )
    if r.status_code not in (200, 201):
        return {"sent": False, "reason": f"resend error {r.status_code}: {r.text[:200]}",
                "snapshot": snap}
    return {"sent": True, "id": r.json().get("id"), "snapshot": snap}


if __name__ == "__main__":
    import json
    result = send_snapshot()
    print(json.dumps({"sent": result["sent"],
                      "reason": result.get("reason"),
                      "subject": result["snapshot"]["subject"]}, indent=2))
