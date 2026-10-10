# SoloLedger — MVP (prod_1791487083)

**Stripe tells you what came in. SoloLedger tells you what you kept.**

True-profit P&L for one-person SaaS: revenue − every cost = what you actually keep.
Deterministic math (integer cents, no rounding drift). Zero paid APIs. Zero LLM calls.

## Run it

```bash
cd ~/workspace/agent-army/builds/prod_1791487083/app
./run.sh
```

First run creates `.venv/` and installs `fastapi` + `uvicorn` (free, open source).

Then open:
- **Landing:** http://127.0.0.1:8788/
- **Dashboard:** http://127.0.0.1:8788/dashboard
- **API docs:** http://127.0.0.1:8788/docs

SQLite database is created automatically (`sololedger.db`, override with `SOLOLEDGER_DB`).

## Modes

| Mode | Env | What happens |
|---|---|---|
| `demo` (default) | — | Deterministic synthetic portfolio: 3 products, ~$13k/mo revenue, realistic expenses. Nothing leaves your machine. |
| `live` | `SOLOLEDGER_MODE=live SOLOLEDGER_STRIPE_KEY=rk_...` | Read-only fetch of Stripe balance transactions (net). Use a **restricted key** (Balance Transactions: Read). Full `sk_live_` keys are refused unless `SOLOLEDGER_ALLOW_LIVE_KEY=1` is set. |

## What's implemented

- **P&L engine** (`ledger.py`) — monthly revenue − expenses = profit, margin %, per-category split, per-product breakdown (shared costs attributed proportionally), all in integer cents
- **"Rent covered?"** (`/api/rent`) — profit vs. your monthly nut (set in dashboard Settings)
- **Runway calculator** (`/api/runway`) — cash on hand ÷ monthly burn, or ∞ when profitable
- **Expense entry** — manual form + CSV import (`date, category, amount_cents|amount, product, note`); categories: hosting, apis, contractors, tools, fees, other
- **Revenue entry** — manual rows + demo seed + live Stripe sync (`POST /api/sync`)
- **Stripe client** (`stripe_client.py`) — demo generator + live read-only fetch, sk_live_ guard
- **Weekly digest** (`digest.py`) — kept/spent/top-cost-drivers snapshot; sends via Resend when `RESEND_API_KEY` + `SOLOLEDGER_DIGEST_TO` are set, otherwise preview-only. Run weekly: `python digest.py` (see `.github/workflows/digest.yml` for the cron template)
- **Dashboard** (`/dashboard`) — P&L cards, rent banner, category table, per-product table, runway, expense CRUD, CSV import, digest preview
- **Landing page** (`/`) — marketing copy from the product brief

## API quick reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | mode + version |
| GET | `/api/pnl?month=YYYY-MM` | monthly P&L |
| GET | `/api/rent?month=YYYY-MM` | rent-covered verdict |
| GET | `/api/runway` | runway from current month |
| GET/POST | `/api/expenses` | list / add expense |
| DELETE | `/api/expenses/{id}` | delete expense |
| POST | `/api/expenses/csv` | CSV import |
| GET/POST | `/api/revenue` | list / add manual revenue |
| POST | `/api/sync?month=YYYY-MM` | refresh revenue from active source |
| GET/POST | `/api/settings` | monthly nut + cash on hand |
| GET | `/api/digest?month=YYYY-MM` | preview weekly snapshot |
| POST | `/api/digest/send` | send via Resend (needs API key) |

## Env vars

See `.env.example`. No secrets are hardcoded — everything sensitive comes from the environment.

## Deploy notes (for the shipper)

- **Vercel + Supabase** per the brief: swap `db.py`'s sqlite3 for Supabase Postgres (same SQL shape), keep FastAPI as-is or port routes to Next.js API routes.
- **Weekly digest cron:** `.github/workflows/digest.yml` template included — runs `python digest.py` every Monday 09:00 UTC with `RESEND_API_KEY` + `SOLOLEDGER_DIGEST_TO` as GitHub secrets.
- **Blockers for Justin:** (1) Stripe OAuth app registration if moving beyond restricted-key sync to full OAuth; (2) Resend domain verification for the digest sender address; (3) Supabase project creation for production Postgres.
