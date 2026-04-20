import os
from datetime import datetime
import requests
from dotenv import load_dotenv

from connectors.fintual import FintualClient
from connectors.binance_client import BinanceClient
from models.portfolio import Portfolio, Position

load_dotenv()

# Tipo de cambio USD/CLP (fallback si la API falla)
_FALLBACK_USDCLP = 950.0


def _get_usdclp() -> float:
    """Obtiene el tipo de cambio USD/CLP desde exchangerate-api (gratuita, sin key)."""
    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["rates"]["CLP"]
    except Exception:
        return _FALLBACK_USDCLP


def get_portfolio() -> Portfolio:
    """Consolida posiciones de Fintual y Binance en un Portfolio unificado en USD."""
    positions: list[Position] = []
    usdclp = _get_usdclp()

    # --- Fintual ---
    try:
        fintual = FintualClient()
        goals = fintual.get_goals()
        for goal in goals:
            attrs = goal.get("attributes", {})
            name = attrs.get("name", f"Goal {goal.get('id')}")
            nav_clp = float(attrs.get("nav", 0))
            value_usd = nav_clp / usdclp
            positions.append(
                Position(
                    platform="fintual",
                    name=name,
                    amount=nav_clp,
                    value_usd=value_usd,
                    currency="CLP",
                )
            )
    except Exception as e:
        print(f"[Fintual] Error al obtener datos: {e}")

    # --- Binance ---
    try:
        binance = BinanceClient()
        balances = binance.get_balances()
        symbols = [b["asset"] for b in balances]
        prices = binance.get_prices(symbols)

        for balance in balances:
            asset = balance["asset"]
            amount = float(balance["free"]) + float(balance["locked"])
            price_usd = prices.get(asset, 0.0)
            value_usd = amount * price_usd
            if value_usd < 0.01:  # filtrar dust
                continue
            positions.append(
                Position(
                    platform="binance",
                    name=asset,
                    amount=amount,
                    value_usd=value_usd,
                    currency="USDT",
                )
            )
    except Exception as e:
        print(f"[Binance] Error al obtener datos: {e}")

    total_usd = sum(p.value_usd for p in positions)
    return Portfolio(
        timestamp=datetime.now(),
        positions=positions,
        total_usd=total_usd,
    )
