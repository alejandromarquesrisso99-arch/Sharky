"""
Proveedor de datos de mercado para Sharky.
Monitorea activos individuales, índices de referencia (SPY, QQQ) y macro-indicadores (TLT, GLD, USO).
"""

from typing import Dict, List, Optional
import datetime
from sharky.models import MarketSnapshot

MACRO_TICKERS = ["SPY", "QQQ", "TLT", "GLD", "USO"]
CORE_WATCHLIST = ["NVDA", "ASML", "MSFT", "AAPL", "GOOGL", "TSM", "AMZN", "META"]


TICKER_ALIASES = {
    "RHM": "RHM.DE",
    "URNU": "URNU.L",
    "BTC": "BTC-USD",
    "GLD": "GLD",
    "LMT": "LMT",
    "MSFT": "MSFT",
    "BLK": "BLK",
    "NIO": "NIO",
    "NOK": "NOK",
}

# Fallback offline con cotizaciones representativas de mercado, macro y cartera real
DEFAULT_MOCK_PRICES = {
    # Índices Macro y Coberturas
    "SPY": (560.20, +0.4, 28.5, 52000000000000),
    "QQQ": (485.50, +0.7, 32.0, 24000000000000),
    "TLT": (95.40, -0.3, None, None),
    "GLD": (230.10, +0.5, None, None),
    "USO": (78.30, -0.8, None, None),
    # Cartera Real & Tesis Activas
    "RHM": (1145.00, +0.5, 34.2, 50000000000),
    "LMT": (492.50, +1.2, 19.8, 120000000000),
    "URNU": (24.50, +2.3, None, None),
    "MSFT": (442.00, +0.5, 36.4, 3280000000000),
    "NVDA": (125.50, +1.8, 48.0, 3100000000000),
    "BLK": (998.00, +0.1, 22.4, 150000000000),
    "NIO": (3.75, +3.3, None, 7800000000),
    "NOK": (8.90, +0.7, 14.5, 22000000000),
    "BTC": (67500.00, +1.5, None, 1330000000000),
    # Universo Tecnológico y Radar
    "ASML": (870.00, -0.4, 42.0, 350000000000),
    "TSM": (175.40, +2.3, 26.5, 910000000000),
    "AAPL": (224.30, +0.2, 33.1, 3450000000000),
    "GOOGL": (168.90, +1.1, 24.2, 2100000000000),
    "AMZN": (178.50, +0.9, 41.5, 1860000000000),
    "META": (510.80, +1.4, 25.8, 1300000000000),
}


class MarketDataProvider:
    def __init__(self):
        self.has_yfinance = False
        try:
            import yfinance as yf
            self.yf = yf
            self.has_yfinance = True
        except ImportError:
            self.has_yfinance = False

    def get_snapshot(self, ticker: str) -> MarketSnapshot:
        """Obtiene una instantánea de mercado para un ticker (precio, cambio diario, volumen)."""
        clean_ticker = ticker.upper().strip()
        query_ticker = TICKER_ALIASES.get(clean_ticker, clean_ticker)
        
        if self.has_yfinance:
            try:
                t = self.yf.Ticker(query_ticker)
                info = t.info or {}
                hist = t.history(period="2d")
                
                if len(hist) >= 1:
                    current_price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_price
                    change_pct = ((current_price - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
                    vol = int(hist["Volume"].iloc[-1]) if "Volume" in hist else 0
                    
                    return MarketSnapshot(
                        ticker=clean_ticker,
                        precio_actual=round(current_price, 2),
                        cambio_diario_pct=round(change_pct, 2),
                        volumen=vol,
                        pe_ratio=info.get("trailingPE"),
                        market_cap=info.get("marketCap"),
                        timestamp=datetime.datetime.now()
                    )
            except Exception:
                pass

        # Fallback offline con cotizaciones representativas
        mock_data = DEFAULT_MOCK_PRICES.get(clean_ticker, (100.0, 0.0, 25.0, 10000000000))
        base_price = mock_data[0]
        base_change = mock_data[1]
        pe_ratio = mock_data[2] if len(mock_data) > 2 else 25.0
        mcap = mock_data[3] if len(mock_data) > 3 else 10000000000

        return MarketSnapshot(
            ticker=clean_ticker,
            precio_actual=base_price,
            cambio_diario_pct=base_change,
            volumen=1500000,
            pe_ratio=pe_ratio,
            market_cap=mcap,
            timestamp=datetime.datetime.now()
        )

    def get_batch_snapshots(self, tickers: List[str]) -> Dict[str, MarketSnapshot]:
        """Obtiene datos de mercado para una lista de tickers."""
        return {t: self.get_snapshot(t) for t in tickers}

    def get_macro_overview(self) -> Dict[str, MarketSnapshot]:
        """Devuelve el estado de los indicadores macroeconómicos de referencia."""
        return self.get_batch_snapshots(MACRO_TICKERS)

