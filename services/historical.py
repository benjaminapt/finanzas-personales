"""
Servicio de rentabilidad histórica por instrumento.

Fintual: usa la API pública (sin auth) para obtener NAV diario de cada fondo.
Binance: usa la API pública de klines para obtener precio diario en USD.
"""
import requests
from datetime import datetime, date, timedelta

FINTUAL_API = "https://fintual.cl/api"
COINGECKO_API = "https://api.coingecko.com/api/v3"
_COINGECKO_IDS = {
    "BTC": "bitcoin", "ADA": "cardano", "ETH": "ethereum",
    "SOL": "solana", "DOT": "polkadot", "BNB": "binancecoin",
    "XRP": "ripple", "DOGE": "dogecoin", "MATIC": "matic-network",
}


def _find_real_asset_id(goal_name):
    """
    Busca el real_asset_id de Fintual para el fondo que corresponde al nombre de la meta.
    Hace dos llamadas:
      1. /conceptual_assets → encuentra el conceptual_asset_id por nombre
      2. /real_assets?conceptual_asset_id=X → selecciona Serie A (o el primero disponible)
    """
    name_lower = goal_name.lower()

    if any(k in name_lower for k in ["muy arriesgad", "very"]):
        search_kw = "very"
    elif any(k in name_lower for k in ["moderado", "moderate"]):
        search_kw = "moderate"
    elif any(k in name_lower for k in ["arriesgado", "risky"]):
        search_kw = "risky"
    else:
        search_kw = name_lower.split()[0]

    resp = requests.get(f"{FINTUAL_API}/conceptual_assets", timeout=10)
    resp.raise_for_status()
    assets = resp.json().get("data", [])

    conceptual_id = None
    for asset in assets:
        asset_name = asset.get("attributes", {}).get("name", "").lower()
        if search_kw == "very" and "very" in asset_name:
            conceptual_id = int(asset["id"])
            break
        elif search_kw == "moderate" and "moderate" in asset_name and "very" not in asset_name:
            conceptual_id = int(asset["id"])
            break
        elif search_kw == "risky" and "risky" in asset_name and "very" not in asset_name:
            conceptual_id = int(asset["id"])
            break

    if not conceptual_id:
        return None

    resp2 = requests.get(
        f"{FINTUAL_API}/real_assets",
        params={"conceptual_asset_id": conceptual_id},
        timeout=10,
    )
    resp2.raise_for_status()
    real_assets = resp2.json().get("data", [])

    if not real_assets:
        return None

    # Preferir Serie A (inversión normal, no APV)
    for ra in real_assets:
        if ra.get("attributes", {}).get("serie", "").upper() == "A":
            return int(ra["id"])

    return int(real_assets[0]["id"])


def get_fintual_nav_history(goal_name, days=365):
    """
    Retorna historial diario de NAV para un fondo Fintual via API pública.

    Retorna lista de dicts: {"date": "YYYY-MM-DD", "price": float, "pct": float}
    donde pct es el % de retorno acumulado respecto al primer día del período.
    """
    try:
        asset_id = _find_real_asset_id(goal_name)
        if not asset_id:
            return []

        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        resp = requests.get(
            f"{FINTUAL_API}/real_assets/{asset_id}/days",
            params={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        if not data:
            return []

        prices = [
            {
                "date": d["attributes"]["date"],
                "price": float(d["attributes"]["price"]),
            }
            for d in data
        ]

        first_price = prices[0]["price"] if prices else 1.0
        for p in prices:
            p["pct"] = (p["price"] / first_price - 1) * 100

        return prices

    except Exception as e:
        print(f"[Historical/Fintual] Error para '{goal_name}': {e}")
        return []


def get_binance_price_history(symbol, days=365):
    """
    Retorna historial diario de precio en USD para un asset crypto via CoinGecko.
    (CoinGecko es público, sin auth y sin geo-restricción — funciona desde cloud.)

    Retorna lista de dicts: {"date": "YYYY-MM-DD", "price": float, "pct": float}
    donde pct es el % de retorno acumulado respecto al primer día del período.
    """
    try:
        cg_id = _COINGECKO_IDS.get(symbol.upper())
        if not cg_id:
            print(f"[Historical/Crypto] Symbol '{symbol}' no tiene mapeo CoinGecko")
            return []

        resp = requests.get(
            f"{COINGECKO_API}/coins/{cg_id}/market_chart",
            params={"vs_currency": "usd", "days": str(days)},
            timeout=15,
        )
        resp.raise_for_status()
        raw_prices = resp.json().get("prices", [])  # [[timestamp_ms, price], ...]

        if not raw_prices:
            return []

        # Agrupar por día (CoinGecko puede dar múltiples puntos por día)
        daily = {}
        for ts_ms, price in raw_prices:
            d = str(datetime.fromtimestamp(ts_ms / 1000).date())
            daily[d] = price  # último precio del día

        prices = [{"date": d, "price": p} for d, p in sorted(daily.items())]

        first_price = prices[0]["price"] if prices else 1.0
        for p in prices:
            p["pct"] = (p["price"] / first_price - 1) * 100

        return prices

    except Exception as e:
        import traceback
        print(f"[Historical/Crypto] Error para '{symbol}': {e}")
        traceback.print_exc()
        return []
