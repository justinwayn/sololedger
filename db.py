"""SoloLedger SQLite layer. stdlib only. All money stored as integer cents."""
import os
import sqlite3
import time

DB_PATH = os.environ.get("SOLOLEDGER_DB", os.path.join(os.path.dirname(__file__), "sololedger.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,              -- YYYY-MM-DD
    category TEXT NOT NULL,          -- hosting|apis|contractors|tools|fees|other
    amount_cents INTEGER NOT NULL,   -- positive integer
    product TEXT NOT NULL DEFAULT 'all',
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,              -- YYYY-MM-DD
    amount_cents INTEGER NOT NULL,
    product TEXT NOT NULL DEFAULT 'all',
    source TEXT NOT NULL DEFAULT 'manual',  -- manual|stripe|demo
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date);
CREATE INDEX IF NOT EXISTS idx_revenue_date ON revenue_entries(date);
"""

CATEGORIES = ["hosting", "apis", "contractors", "tools", "fees", "other"]


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = connect()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = connect()
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()
    conn.close()


def add_expense(date, category, amount_cents, product="all", note=""):
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; must be one of {CATEGORIES}")
    if amount_cents <= 0:
        raise ValueError("amount must be positive cents")
    conn = connect()
    cur = conn.execute(
        "INSERT INTO expenses(date,category,amount_cents,product,note,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (date, category, int(amount_cents), product or "all", note or "", int(time.time())),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def list_expenses(month=None, product=None):
    """month = 'YYYY-MM' or None for all."""
    conn = connect()
    q = "SELECT * FROM expenses"
    clauses, params = [], []
    if month:
        clauses.append("substr(date,1,7)=?")
        params.append(month)
    if product and product != "all":
        clauses.append("product=?")
        params.append(product)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY date DESC, id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    return rows


def delete_expense(eid):
    conn = connect()
    cur = conn.execute("DELETE FROM expenses WHERE id=?", (eid,))
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n > 0


def add_revenue(date, amount_cents, product="all", source="manual", note=""):
    if amount_cents < 0:
        raise ValueError("revenue amount cannot be negative")
    conn = connect()
    cur = conn.execute(
        "INSERT INTO revenue_entries(date,amount_cents,product,source,note,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (date, int(amount_cents), product or "all", source, note or "", int(time.time())),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def list_revenue(month=None, product=None):
    conn = connect()
    q = "SELECT * FROM revenue_entries"
    clauses, params = [], []
    if month:
        clauses.append("substr(date,1,7)=?")
        params.append(month)
    if product and product != "all":
        clauses.append("product=?")
        params.append(product)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY date DESC, id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    return rows


def clear_source(source):
    """Remove all rows from a given source (used to refresh demo/stripe data)."""
    conn = connect()
    conn.execute("DELETE FROM revenue_entries WHERE source=?", (source,))
    conn.commit()
    conn.close()
