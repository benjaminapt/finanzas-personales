import json
import os
import re
from datetime import datetime, timedelta

from models.portfolio import Portfolio, Position

# Cuando DATABASE_URL está definida → PostgreSQL (Supabase).
# Si no → SQLite local (comportamiento original sin cambios).
_DB_URL = os.getenv("DATABASE_URL")
_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "portfolio.db")
_PH = "%s" if _DB_URL else "?"   # placeholder de parámetros por driver


# ── Conexión ──────────────────────────────────────────────────────────────────

def _get_conn():
    if _DB_URL:
        import psycopg2
        conn = psycopg2.connect(_DB_URL)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    total_usd REAL NOT NULL,
                    positions_json TEXT NOT NULL,
                    ai_recommendation TEXT
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ts ON snapshots(timestamp)"
            )
        conn.commit()
        return conn
    else:
        import sqlite3
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_usd REAL NOT NULL,
                positions_json TEXT NOT NULL,
                ai_recommendation TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ts ON snapshots(timestamp)"
        )
        conn.commit()
        return conn


def _clean_fund_name(name: str) -> str:
    """Quita emojis del inicio del nombre para normalizar entre API y Playwright."""
    return re.sub(r"^[\U00010000-\U0010ffff\u2600-\u27BF\U0001F300-\U0001FAFF]+\s*", "", name).strip()


def _ensure_flows_table(conn):
    """Crea tabla binance_flows si no existe. Separada de _get_conn para no romper conexiones normales."""
    try:
        if _DB_URL:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS binance_flows (
                        id SERIAL PRIMARY KEY,
                        asset TEXT NOT NULL,
                        date TEXT NOT NULL,
                        type TEXT NOT NULL,
                        amount REAL NOT NULL,
                        fiat_amount REAL,
                        fiat TEXT,
                        order_id TEXT UNIQUE
                    )
                """)
            conn.commit()
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS binance_flows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT NOT NULL,
                    date TEXT NOT NULL,
                    type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    fiat_amount REAL,
                    fiat TEXT,
                    order_id TEXT UNIQUE
                )
            """)
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _fetchall(conn, sql, params=()):
    if _DB_URL:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    else:
        return conn.execute(sql, params).fetchall()


def _execute(conn, sql, params=()):
    if _DB_URL:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    else:
        conn.execute(sql, params)
        conn.commit()


# ── API pública ───────────────────────────────────────────────────────────────

def save_snapshot(portfolio: Portfolio, ai_recommendation=None) -> None:
    positions_data = [
        {
            "platform": p.platform,
            "name": p.name,
            "amount": p.amount,
            "value_usd": p.value_usd,
            "currency": p.currency,
        }
        for p in portfolio.positions
    ]
    conn = _get_conn()
    try:
        _execute(
            conn,
            f"INSERT INTO snapshots (timestamp, total_usd, positions_json, ai_recommendation) "
            f"VALUES ({_PH},{_PH},{_PH},{_PH})",
            (
                portfolio.timestamp.isoformat(),
                portfolio.total_usd,
                json.dumps(positions_data),
                ai_recommendation,
            ),
        )
    finally:
        conn.close()


def get_history(days=None) -> list[dict]:
    """Retorna snapshots ordenados por fecha. Si days=None, retorna todo el historial."""
    conn = _get_conn()
    try:
        if days is None:
            rows = _fetchall(
                conn,
                "SELECT timestamp, total_usd, positions_json, ai_recommendation "
                "FROM snapshots ORDER BY timestamp ASC",
            )
        else:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            rows = _fetchall(
                conn,
                f"SELECT timestamp, total_usd, positions_json, ai_recommendation "
                f"FROM snapshots WHERE timestamp >= {_PH} ORDER BY timestamp ASC",
                (since,),
            )
    finally:
        conn.close()

    return [
        {
            "timestamp": r[0],
            "total_usd": r[1],
            "positions": json.loads(r[2]),
            "ai_recommendation": r[3],
        }
        for r in rows
    ]


def get_last_snapshot():
    """Retorna el snapshot más reciente."""
    conn = _get_conn()
    try:
        rows = _fetchall(
            conn,
            "SELECT timestamp, total_usd, positions_json, ai_recommendation "
            "FROM snapshots ORDER BY timestamp DESC LIMIT 1",
        )
    finally:
        conn.close()

    if not rows:
        return None
    r = rows[0]
    return {
        "timestamp": r[0],
        "total_usd": r[1],
        "positions": json.loads(r[2]),
        "ai_recommendation": r[3],
    }


# ── Binance Flows (cache para cloud) ─────────────────────────────────────────

def save_binance_flows(flows: list) -> int:
    """Guarda flujos Binance en DB. Usa order_id como clave única (upsert)."""
    conn = _get_conn()
    _ensure_flows_table(conn)
    saved = 0
    try:
        for f in flows:
            order_id = f.get("order_id") or f"{f.get('date','')}-{f.get('type','')}-{f.get('amount',0)}"
            try:
                if _DB_URL:
                    _execute(
                        conn,
                        f"INSERT INTO binance_flows (asset, date, type, amount, fiat_amount, fiat, order_id) "
                        f"VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH}) "
                        f"ON CONFLICT (order_id) DO NOTHING",
                        (f.get("asset", ""), f.get("date", ""), f.get("type", ""),
                         float(f.get("amount", 0)), float(f.get("fiat_amount", 0) or 0),
                         f.get("fiat", ""), order_id),
                    )
                else:
                    _execute(
                        conn,
                        f"INSERT OR IGNORE INTO binance_flows (asset, date, type, amount, fiat_amount, fiat, order_id) "
                        f"VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH})",
                        (f.get("asset", ""), f.get("date", ""), f.get("type", ""),
                         float(f.get("amount", 0)), float(f.get("fiat_amount", 0) or 0),
                         f.get("fiat", ""), order_id),
                    )
                saved += 1
            except Exception:
                pass  # duplicado o error de inserción
    finally:
        conn.close()
    return saved


def get_binance_flows_cached(asset: str = None) -> list:
    """Lee flujos Binance de DB. Si asset es None, retorna todos."""
    conn = _get_conn()
    try:
        if asset:
            rows = _fetchall(
                conn,
                f"SELECT asset, date, type, amount, fiat_amount, fiat "
                f"FROM binance_flows WHERE asset = {_PH} ORDER BY date DESC",
                (asset,),
            )
        else:
            rows = _fetchall(
                conn,
                "SELECT asset, date, type, amount, fiat_amount, fiat "
                "FROM binance_flows ORDER BY date DESC",
            )
    finally:
        conn.close()

    return [
        {
            "asset": r[0], "date": r[1], "type": r[2],
            "amount": r[3], "fiat_amount": r[4], "fiat": r[5] or "",
        }
        for r in rows
    ]


# ── Fintual Flows (cache para cloud) ─────────────────────────────────────────

def _ensure_fintual_flows_table(conn):
    """Crea tabla fintual_flows si no existe."""
    try:
        if _DB_URL:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fintual_flows (
                        id SERIAL PRIMARY KEY,
                        fund_name TEXT NOT NULL,
                        date TEXT NOT NULL,
                        type TEXT NOT NULL,
                        amount_clp REAL NOT NULL,
                        UNIQUE(fund_name, date, type, amount_clp)
                    )
                """)
            conn.commit()
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fintual_flows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fund_name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    type TEXT NOT NULL,
                    amount_clp REAL NOT NULL,
                    UNIQUE(fund_name, date, type, amount_clp)
                )
            """)
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def save_fintual_flows(fund_name: str, flows: list) -> int:
    """Guarda flujos Fintual en DB. Usa clave compuesta como unique."""
    fund_name = _clean_fund_name(fund_name)
    conn = _get_conn()
    _ensure_fintual_flows_table(conn)
    saved = 0
    try:
        for f in flows:
            try:
                if _DB_URL:
                    _execute(
                        conn,
                        f"INSERT INTO fintual_flows (fund_name, date, type, amount_clp) "
                        f"VALUES ({_PH},{_PH},{_PH},{_PH}) "
                        f"ON CONFLICT (fund_name, date, type, amount_clp) DO NOTHING",
                        (fund_name, f.get("date", ""), f.get("type", ""),
                         float(f.get("amount_clp", 0))),
                    )
                else:
                    _execute(
                        conn,
                        f"INSERT OR IGNORE INTO fintual_flows (fund_name, date, type, amount_clp) "
                        f"VALUES ({_PH},{_PH},{_PH},{_PH})",
                        (fund_name, f.get("date", ""), f.get("type", ""),
                         float(f.get("amount_clp", 0))),
                    )
                saved += 1
            except Exception:
                pass
    finally:
        conn.close()
    return saved


def get_fintual_flows_cached(fund_name: str = None) -> list:
    """Lee flujos Fintual de DB. Retorna formato compatible con get_fintual_flows."""
    if fund_name:
        fund_name = _clean_fund_name(fund_name)
    conn = _get_conn()
    try:
        if fund_name:
            rows = _fetchall(
                conn,
                f"SELECT date, type, amount_clp "
                f"FROM fintual_flows WHERE fund_name = {_PH} ORDER BY date DESC",
                (fund_name,),
            )
        else:
            rows = _fetchall(
                conn,
                "SELECT date, type, amount_clp "
                "FROM fintual_flows ORDER BY date DESC",
            )
    finally:
        conn.close()

    return [
        {"date": r[0], "type": r[1], "amount_clp": r[2]}
        for r in rows
    ]
