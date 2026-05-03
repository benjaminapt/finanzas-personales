"""
Servicio para obtener historial de aportes y retiros por producto.

Fintual: API autenticada con cookies de sesión para obtener goal_id,
         luego scraping de la página de movimientos del goal.
Binance: endpoints autenticados de depósitos, retiros y compras P2P.
"""
import os
import re
import json
import hmac
import hashlib
import time
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SESSION_PATH = Path.home() / ".finanzas" / "fintual_session.json"

# Líneas de navegación a ignorar al parsear texto de Fintual
_NAV_SKIP = {
    "invierte", "aprende", "gana", "perfil", "home", "rentabilidad",
    "apv", "store", "personas", "términos y condiciones", "movimientos",
    "invertir", "retirar", "mover", "actualizado",
}


# ─── Fintual ─────────────────────────────────────────────────────────────────

def _get_fintual_goal_id(goal_name: str):
    """
    Llama a /api/goals con las cookies de sesión para obtener el ID del goal
    que corresponde a goal_name.
    """
    session = json.loads(SESSION_PATH.read_text())
    cookies = {c["name"]: c["value"] for c in session.get("cookies", [])
               if "fintual" in c.get("domain", "")}
    jwt = cookies.get("stocks-pricing_service_jwt", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/json",
    }
    r = requests.get("https://fintual.cl/api/goals", headers=headers,
                     cookies=cookies, timeout=10)
    if r.status_code != 200:
        return None

    goal_lower = goal_name.lower().strip()
    for item in r.json().get("data", []):
        name = item.get("attributes", {}).get("name", "")
        # Quitar emojis y espacios para comparar
        clean = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE).strip().lower()
        if goal_lower in clean or clean in goal_lower:
            return int(item["id"])
    return None


def get_fintual_flows(goal_name: str) -> list[dict]:
    """
    Obtiene historial de aportes y retiros de una meta Fintual.

    Pasos:
      1. Llama a /api/goals con cookies para encontrar el goal_id
      2. Navega a la URL de movimientos del goal con Playwright
      3. Parsea el texto estructurado (Tipo → Fecha → Monto en líneas consecutivas)

    Retorna lista de dicts:
        {"date": "YYYY-MM-DD", "type": "aporte"|"retiro", "amount_clp": float}
    ordenada por fecha descendente.
    """
    if not SESSION_PATH.exists():
        return []

    try:
        goal_id = _get_fintual_goal_id(goal_name)
        if not goal_id:
            print(f"[Flows/Fintual] No se encontró goal_id para '{goal_name}'")
            return []

        url = (f"https://fintual.cl/f/mutual-funds/"
               f"investible-objects-visualization/show-goal/{goal_id}/movements/")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                storage_state=str(SESSION_PATH),
            )
            page = ctx.new_page()

            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                time.sleep(2)

                if "sign-in" in page.url or "entrar" in page.url:
                    return []

                body_text = page.inner_text("body")
                ctx.storage_state(path=str(SESSION_PATH))
                return _parse_movements_text(body_text)

            finally:
                browser.close()

    except Exception as e:
        print(f"[Flows/Fintual] Error en '{goal_name}': {e}")
        return []


def _parse_movements_text(body_text: str) -> list[dict]:
    """
    Parsea el texto de la página de movimientos de Fintual.
    La página tiene un patrón consistente de 3 líneas por movimiento:
        Tipo de movimiento   (ej: "Depósito", "Retiro", "Movimiento desde otra inversión")
        Fecha                (ej: "09/04/2026")
        Monto                (ej: "$800.000")
    """
    date_re = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
    amount_re = re.compile(r"^\$\s*([\d.,]+)$")

    aporte_kw = {"depósito", "deposito", "aporte", "movimiento desde otra inversión",
                 "movimiento desde otra inversion", "transferencia recibida"}
    retiro_kw = {"rescate", "retiro", "withdrawal", "transferencia enviada"}

    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
    flows = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Buscar una línea de fecha
        dm = date_re.match(line)
        if dm:
            day, month, year = dm.group(1), dm.group(2), dm.group(3)
            date_str = f"{year}-{month}-{day}"

            # La línea anterior (no-nav) es el tipo
            flow_type = None
            for j in range(i - 1, max(i - 4, -1), -1):
                candidate = lines[j].lower()
                if candidate in _NAV_SKIP:
                    continue
                if any(k in candidate for k in aporte_kw):
                    flow_type = "aporte"
                elif any(k in candidate for k in retiro_kw):
                    flow_type = "retiro"
                break

            # La línea siguiente es el monto
            if flow_type and i + 1 < len(lines):
                am = amount_re.match(lines[i + 1])
                if am:
                    amount_str = am.group(1).replace(".", "").replace(",", "")
                    try:
                        amount = float(amount_str)
                        if amount > 0:
                            flows.append({
                                "date": date_str,
                                "type": flow_type,
                                "amount_clp": amount,
                            })
                    except ValueError:
                        pass

        i += 1

    flows.sort(key=lambda x: x["date"], reverse=True)
    return flows


# ─── Binance ─────────────────────────────────────────────────────────────────

# NOTA IMPORTANTE: Las compras de ADA/BTC se hicieron por P2P en CLP (pesos
# chilenos). El endpoint C2C de Binance solo devuelve los últimos 30 días sin
# parámetros de fecha → hay que paginar por ventanas de tiempo para recuperar
# el historial completo. Esto es distinto a compras en USD vía spot o fiat.

_WINDOW_MS = 30 * 24 * 60 * 60 * 1000  # 30 días en milisegundos
_HISTORY_MONTHS = 30                     # cuántos meses hacia atrás buscar


def _time_windows(months_back=_HISTORY_MONTHS):
    """Genera ventanas (start_ms, end_ms) de 30 días hacia atrás."""
    end_ms = int(time.time() * 1000)
    for _ in range(months_back):
        start_ms = end_ms - _WINDOW_MS
        yield start_ms, end_ms
        end_ms = start_ms


def get_binance_flows(asset: str = None) -> list[dict]:
    """
    Obtiene historial de movimientos de Binance:
    - Depósitos directos de crypto
    - Retiros de crypto
    - Compras/ventas via P2P C2C (paginando por ventanas de 30 días para
      recuperar historial completo, incluyendo compras antiguas en CLP)
    - Compras/ventas via Fiat (Binance Pay, tarjeta, etc.)

    Args:
        asset: filtrar por asset (ej: "BTC", "ADA"). None = todos.

    Retorna lista de dicts:
        {"date": "YYYY-MM-DD", "asset": str, "type": str, "amount": float}
    ordenada por fecha descendente.
    """
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    if not api_key or not api_secret:
        return []

    def signed_request(endpoint: str, params: dict) -> list:
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"https://api.binance.com{endpoint}?{query}&signature={sig}"
        r = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=15)
        if r.status_code != 200:
            print(f"[Flows/Binance] {endpoint} → {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            inner = data.get("data") or data.get("list") or []
            return inner if isinstance(inner, list) else []
        return []

    flows = []
    seen_ids = set()  # deduplicar por orderNumber/txId

    # ── Depósitos directos de crypto ─────────────────────────────────────────
    try:
        params = {}
        if asset:
            params["coin"] = asset
        for d in signed_request("/sapi/v1/capital/deposit/hisrec", params):
            if float(d.get("amount", 0)) > 0:
                tx_id = d.get("txId", "")
                if tx_id and tx_id in seen_ids:
                    continue
                if tx_id:
                    seen_ids.add(tx_id)
                ts_ms = int(d.get("insertTime", 0))
                date_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d") if ts_ms else "N/A"
                flows.append({
                    "date": date_str,
                    "asset": d.get("coin", ""),
                    "type": "deposito",
                    "amount": float(d.get("amount", 0)),
                })
    except Exception as e:
        print(f"[Flows/Binance] Error depósitos: {e}")

    # ── Retiros de crypto ─────────────────────────────────────────────────────
    try:
        params = {}
        if asset:
            params["coin"] = asset
        for w in signed_request("/sapi/v1/capital/withdraw/history", params):
            if float(w.get("amount", 0)) > 0:
                apply_time = w.get("applyTime", "")
                date_str = apply_time[:10] if apply_time else "N/A"
                flows.append({
                    "date": date_str,
                    "asset": w.get("coin", ""),
                    "type": "retiro",
                    "amount": float(w.get("amount", 0)),
                })
    except Exception as e:
        print(f"[Flows/Binance] Error retiros: {e}")

    # ── Compras/ventas P2P C2C (paginando por tiempo) ─────────────────────────
    # IMPORTANTE: compras en CLP via P2P requieren iterar ventanas de 30 días.
    # Sin startTimestamp el endpoint solo devuelve ~últimos 30 días.
    for trade_type, flow_label in [("BUY", "p2p_compra"), ("SELL", "p2p_venta")]:
        try:
            for start_ms, end_ms in _time_windows():
                orders = signed_request(
                    "/sapi/v1/c2c/orderMatch/listUserOrderHistory",
                    {
                        "tradeType": trade_type,
                        "startTimestamp": start_ms,
                        "endTimestamp": end_ms,
                        "page": 1,
                        "rows": 100,
                    },
                )
                for order in orders:
                    if order.get("orderStatus") not in ("COMPLETED", "TRADING"):
                        continue
                    order_no = order.get("orderNumber", "")
                    if order_no and order_no in seen_ids:
                        continue
                    if order_no:
                        seen_ids.add(order_no)
                    asset_code = order.get("asset", "")
                    if asset and asset.upper() != asset_code.upper():
                        continue
                    ts_ms = int(order.get("createTime", 0))
                    date_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d") if ts_ms else "N/A"
                    # amount = crypto recibida, totalPrice = CLP pagado
                    flows.append({
                        "date": date_str,
                        "asset": asset_code,
                        "type": flow_label,
                        "amount": float(order.get("amount", 0)),
                        "fiat_amount": float(order.get("totalPrice", 0)),
                        "fiat": order.get("fiatUnit", ""),
                    })
        except Exception as e:
            print(f"[Flows/Binance] Error P2P {trade_type}: {e}")

    # ── Compras con fiat (Binance Pay / tarjeta / transferencia bancaria) ──────
    # Cubre el caso en que se compraron crypto directamente con CLP via Binance
    try:
        for start_ms, end_ms in _time_windows():
            for fiat_type in ("0", "1"):  # 0=depósito fiat, 1=retiro fiat
                for d in signed_request(
                    "/sapi/v1/fiat/orders",
                    {"transactionType": fiat_type,
                     "beginTime": start_ms, "endTime": end_ms,
                     "rows": 100, "page": 1},
                ):
                    if d.get("status") != "Successful":
                        continue
                    order_no = d.get("orderNo", "")
                    if order_no and order_no in seen_ids:
                        continue
                    if order_no:
                        seen_ids.add(order_no)
                    create_time = d.get("createTime", 0)
                    date_str = datetime.fromtimestamp(int(create_time) / 1000).strftime("%Y-%m-%d") if create_time else "N/A"
                    flow_type = "fiat_compra" if fiat_type == "0" else "fiat_retiro"
                    flows.append({
                        "date": date_str,
                        "asset": d.get("cryptoCurrency", ""),
                        "type": flow_type,
                        "amount": float(d.get("obtainAmount", 0)),
                        "fiat_amount": float(d.get("sourceAmount", 0)),
                        "fiat": d.get("fiatCurrency", ""),
                    })
    except Exception as e:
        print(f"[Flows/Binance] Error fiat orders: {e}")

    # ── Spot market trades (compras/ventas en mercado spot, ej: USDT→ETH) ────
    # Captura conversiones que no son P2P ni fiat, como comprar ETH con USDT
    _SPOT_QUOTE = "USDT"
    assets_to_check = [asset.upper()] if asset else [
        "ETH", "BTC", "ADA", "SOL", "DOT", "BNB", "XRP", "DOGE",
    ]
    for base in assets_to_check:
        if base == _SPOT_QUOTE:
            continue
        symbol = f"{base}{_SPOT_QUOTE}"
        try:
            trades = signed_request("/api/v3/myTrades", {"symbol": symbol, "limit": 1000})
            for t in trades:
                trade_id = f"spot-{symbol}-{t.get('id', '')}"
                if trade_id in seen_ids:
                    continue
                seen_ids.add(trade_id)
                ts_ms = int(t.get("time", 0))
                date_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d") if ts_ms else "N/A"
                qty = float(t.get("qty", 0))
                quote_qty = float(t.get("quoteQty", 0))
                if qty <= 0:
                    continue
                flows.append({
                    "date": date_str,
                    "asset": base,
                    "type": "spot_compra" if t.get("isBuyer") else "spot_venta",
                    "amount": qty,
                    "fiat_amount": quote_qty,
                    "fiat": _SPOT_QUOTE,
                    "order_id": trade_id,
                })
        except Exception as e:
            print(f"[Flows/Binance] Error spot trades {symbol}: {e}")

    # ── Convert trades (Binance Convert, ej: USDT→ETH directo) ──────────────
    try:
        for start_ms, end_ms in _time_windows():
            converts = signed_request(
                "/sapi/v1/convert/tradeFlow",
                {"startTime": start_ms, "endTime": end_ms, "limit": 100},
            )
            for c in converts:
                oid = f"convert-{c.get('orderId', '')}"
                if oid in seen_ids:
                    continue
                seen_ids.add(oid)
                to_asset = c.get("toAsset", "")
                from_asset = c.get("fromAsset", "")
                target = (asset or "").upper()
                if target and target not in (to_asset.upper(), from_asset.upper()):
                    continue
                ts_ms = int(c.get("createTime", 0))
                date_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d") if ts_ms else "N/A"
                if not target or to_asset.upper() == target:
                    flows.append({
                        "date": date_str,
                        "asset": to_asset,
                        "type": "convert_compra",
                        "amount": float(c.get("toAmount", 0)),
                        "fiat_amount": float(c.get("fromAmount", 0)),
                        "fiat": from_asset,
                        "order_id": oid,
                    })
                else:
                    flows.append({
                        "date": date_str,
                        "asset": from_asset,
                        "type": "convert_venta",
                        "amount": float(c.get("fromAmount", 0)),
                        "fiat_amount": float(c.get("toAmount", 0)),
                        "fiat": to_asset,
                        "order_id": oid,
                    })
    except Exception as e:
        print(f"[Flows/Binance] Error convert: {e}")

    flows.sort(key=lambda x: x["date"], reverse=True)
    return flows
