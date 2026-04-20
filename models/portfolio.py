from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Position:
    platform: str       # "fintual" | "binance"
    name: str           # Nombre del fondo o asset (BTC, ETH, Risky Norris, etc.)
    amount: float       # Cantidad de unidades
    value_usd: float    # Valor en USD
    currency: str       # "CLP" | "USD" | "USDT"


@dataclass
class Portfolio:
    timestamp: datetime
    positions: list[Position] = field(default_factory=list)
    total_usd: float = 0.0

    def fintual_positions(self) -> list[Position]:
        return [p for p in self.positions if p.platform == "fintual"]

    def binance_positions(self) -> list[Position]:
        return [p for p in self.positions if p.platform == "binance"]

    def fintual_total_usd(self) -> float:
        return sum(p.value_usd for p in self.fintual_positions())

    def binance_total_usd(self) -> float:
        return sum(p.value_usd for p in self.binance_positions())
