import os
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()


class BinanceClient:
    def __init__(self):
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("Faltan BINANCE_API_KEY o BINANCE_API_SECRET en el .env")

        self._api_key = api_key
        self._secret = api_secret
        self._client = Client(api_key, api_secret)

    def get_balances(self) -> list[dict]:
        """Retorna todos los assets con balance > 0 (Spot + Funding wallet)."""
        balances = {}

        # Spot wallet
        account = self._client.get_account()
        for b in account["balances"]:
            total = float(b["free"]) + float(b["locked"])
            if total > 0:
                balances[b["asset"]] = balances.get(b["asset"], 0) + total

        # Funding wallet
        import time, hmac, hashlib, requests
        ts = int(time.time() * 1000)
        params = f"timestamp={ts}&needBtcValuation=true"
        sig = hmac.new(
            self._secret.encode(), params.encode(), hashlib.sha256
        ).hexdigest()
        r = requests.post(
            f"https://api.binance.com/sapi/v1/asset/get-funding-asset?{params}&signature={sig}",
            headers={"X-MBX-APIKEY": self._api_key},
            timeout=10,
        )
        if r.status_code == 200:
            for b in r.json():
                total = float(b["free"]) + float(b["locked"]) + float(b["freeze"])
                if total > 0:
                    balances[b["asset"]] = balances.get(b["asset"], 0) + total

        return [{"asset": k, "free": str(v), "locked": "0"} for k, v in balances.items()]

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """Retorna precio en USDT para cada symbol dado (ej: ['BTC', 'ETH'])."""
        prices = {}
        all_tickers = {t["symbol"]: float(t["price"]) for t in self._client.get_all_tickers()}

        for symbol in symbols:
            if symbol == "USDT":
                prices[symbol] = 1.0
            elif symbol == "BUSD":
                prices[symbol] = 1.0
            elif f"{symbol}USDT" in all_tickers:
                prices[symbol] = all_tickers[f"{symbol}USDT"]
            elif f"{symbol}BTC" in all_tickers and "BTCUSDT" in all_tickers:
                prices[symbol] = all_tickers[f"{symbol}BTC"] * all_tickers["BTCUSDT"]
            else:
                prices[symbol] = 0.0

        return prices
