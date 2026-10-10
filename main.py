"""SoloLedger MVP — true-profit P&L for one-person SaaS.

Run:  ./run.sh   (or: pip install -r requirements.txt && uvicorn main:app --port 8788)
"""
import csv
import io
import os
from datetime import date

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import ledger
import stripe_client
import digest as digest_mod

HERE = os.path.dirname(__file__)
DEFAULT_MONTH = date.today().strftime("%Y-%m")

app = FastAPI(title="SoloLedger", version="0.1.0")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

db.init()
# seed demo revenue on first boot so the dashboard is alive immediately
if stripe_client.MODE == "demo" and not db.list_revenue(month=DEFAULT_MONTH):
    stripe_client.seed_demo(DEFAULT_MONTH)


# ---------- models ----------
class ExpenseIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    category: str
    amount_cents: int = Field(gt=0)
    product: str = "all"
    note: str = ""


class RevenueIn(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount_cents: int = Field(ge=0)
    product: str = "all"
    note: str = ""


class SettingsIn(BaseModel):
    monthly_nut_cents: int | None = Field(default=None, ge=0)
    cash_on_hand_cents: int | None = Field(default=None, ge=0)


# ---------- pages ----------
@app.get("/")
def landing():
    return FileResponse(os.path.join(HERE, "static", "landing.html"))


@app.get("/dashboard")
def dashboard():
    return FileResponse(os.path.join(HERE, "static", "dashboard.html"))


# ---------- api ----------
@app.get("/api/health")
def health():
    return {"ok": True, "mode": stripe_client.MODE, "version": "0.1.0"}


@app.get("/api/pnl")
def pnl(month: str = DEFAULT_MONTH):
    try:
        return {"ok": True, "pnl": ledger.monthly_pnl(month)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/rent")
def rent(month: str = DEFAULT_MONTH):
    return {"ok": True, "rent": ledger.rent_covered(month)}


@app.get("/api/runway")
def runway():
    return {"ok": True, "runway": ledger.runway()}


@app.get("/api/expenses")
def get_expenses(month: str | None = None, product: str | None = None):
    return {"ok": True, "expenses": db.list_expenses(month=month, product=product),
            "categories": db.CATEGORIES}


@app.post("/api/expenses")
def create_expense(e: ExpenseIn):
    try:
        eid = db.add_expense(e.date, e.category, e.amount_cents, e.product, e.note)
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    return {"ok": True, "id": eid}


@app.delete("/api/expenses/{eid}")
def remove_expense(eid: int):
    if not db.delete_expense(eid):
        raise HTTPException(404, "expense not found")
    return {"ok": True}


@app.post("/api/expenses/csv")
async def import_csv(file: UploadFile = File(...)):
    """CSV columns: date(YYYY-MM-DD), category, amount_cents, product, note.
    Amount may also be given as dollars in an 'amount' column (converted)."""
    raw = (await file.read()).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    added, errors = 0, []
    for i, row in enumerate(reader, start=2):
        try:
            d = (row.get("date") or "").strip()
            cat = (row.get("category") or "").strip().lower()
            product = (row.get("product") or "all").strip()
            note = (row.get("note") or "").strip()
            if row.get("amount_cents"):
                cents = int(float(row["amount_cents"]))
            elif row.get("amount"):
                cents = int(round(float(row["amount"]) * 100))
            else:
                raise ValueError("missing amount_cents/amount")
            db.add_expense(d, cat, cents, product, note)
            added += 1
        except Exception as e:
            errors.append(f"row {i}: {e}")
    return {"ok": True, "added": added, "errors": errors}


@app.get("/api/revenue")
def get_revenue(month: str | None = None):
    return {"ok": True, "revenue": db.list_revenue(month=month)}


@app.post("/api/revenue")
def create_revenue(r: RevenueIn):
    try:
        rid = db.add_revenue(r.date, r.amount_cents, r.product, "manual", r.note)
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    return {"ok": True, "id": rid}


@app.post("/api/sync")
def sync(month: str = DEFAULT_MONTH):
    """Refresh revenue from the active source (demo seed or live Stripe)."""
    try:
        return {"ok": True, "sync": stripe_client.sync_month(month)}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/settings")
def get_settings():
    return {"ok": True, "settings": {
        "monthly_nut_cents": int(db.get_setting("monthly_nut_cents", "0") or 0),
        "cash_on_hand_cents": int(db.get_setting("cash_on_hand_cents", "0") or 0),
    }}


@app.post("/api/settings")
def update_settings(s: SettingsIn):
    if s.monthly_nut_cents is not None:
        db.set_setting("monthly_nut_cents", s.monthly_nut_cents)
    if s.cash_on_hand_cents is not None:
        db.set_setting("cash_on_hand_cents", s.cash_on_hand_cents)
    current = {
        "monthly_nut_cents": int(db.get_setting("monthly_nut_cents", "0") or 0),
        "cash_on_hand_cents": int(db.get_setting("cash_on_hand_cents", "0") or 0),
    }
    return {"ok": True, "settings": current}


@app.get("/api/digest")
def preview_digest(month: str | None = None):
    """Preview the weekly snapshot (what the email would contain)."""
    snap = digest_mod.build_snapshot(month)
    return {"ok": True, "subject": snap["subject"], "text": snap["text"]}


@app.post("/api/digest/send")
def send_digest(month: str | None = None):
    result = digest_mod.send_snapshot(month)
    if not result["sent"]:
        raise HTTPException(502, result["reason"])
    return {"ok": True, "id": result.get("id")}
