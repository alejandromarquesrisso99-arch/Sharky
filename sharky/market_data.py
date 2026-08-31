"""
Proveedor de datos de mercado para Sharky.
Monitorea activos individuales, índices de referencia (SPY, QQQ) y macro-indicadores (TLT, GLD, USO).
"""

from typing import Dict, List, Optional
import datetime
from sharky.models import MarketSnapshot

MACRO_TICKERS = ["SPY", "QQQ", "TLT", "GLD", "USO"]
CORE_WATCHLIST = ["NVDA", "ASML", "MSFT", "AAPL", "GOOGL", "TSM", "AMZN", "META"]


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
        ticker = ticker.upper().strip()
        
        if self.has_yfinance:
            try:
                t = self.yf.Ticker(ticker)
                info = t.info or {}
                hist = t.history(period="2d")
                
                if len(hist) >= 1:
                    current_price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current_price
                    change_pct = ((current_price - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
                    vol = int(hist["Volume"].iloc[-1]) if "Volume" in hist else 0
                    
                    return MarketSnapshot(
                        ticker=ticker,
                        precio_actual=round(current_price, 2),
                        cambio_diario_pct=round(change_pct, 2),
                        volumen=vol,
                        pe_ratio=info.get("trailingPE"),
                        market_cap=info.get("marketCap"),
                        timestamp=datetime.datetime.now()
                    )
            except Exception:
                pass

        # Fallback offline con cotizaciones representativas de mercado y macro
        mock_prices = {
            "SPY": (560.20, +0.4),
            "QQQ": (485.50, +0.7),
            "TLT": (95.40, -0.3),
            "GLD": (230.10, +0.5),
            "USO": (78.30, -0.8),
            "NVDA": (125.50, +1.8),
            "ASML": (870.00, -0.4),
            "MSFT": (415.20, +0.6),
            "AAPL": (224.30, +0.2),
            "GOOGL": (168.90, +1.1),
            "TSM": (175.40, +2.3),
            "AMZN": (178.50, +0.9),
            "META": (510.80, +1.4),
        }
        base_price, base_change = mock_prices.get(ticker, (100.0, 0.0))
        return MarketSnapshot(
            ticker=ticker,
            precio_actual=base_price,
            cambio_diario_pct=base_change,
            volumen=1500000,
            pe_ratio=32.5,
            market_cap=2500000000000,
            timestamp=datetime.datetime.now()
        )

    def get_batch_snapshots(self, tickers: List[str]) -> Dict[str, MarketSnapshot]:
        """Obtiene datos de mercado para una lista de tickers."""
        return {t: self.get_snapshot(t) for t in tickers}

    def get_macro_overview(self) -> Dict[str, MarketSnapshot]:
        """Devuelve el estado de los indicadores macroeconómicos de referencia."""
        return self.get_batch_snapshots(MACRO_TICKERS)
