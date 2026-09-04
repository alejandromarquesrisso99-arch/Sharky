"""
Conversión de divisas para Sharky.

Existe porque la cartera está denominada en EUR mientras que buena parte de los
activos cotiza en USD. Comparar un coste base en EUR contra un precio en USD
produce PnL inventado, así que toda conversión pasa obligatoriamente por aquí y
queda etiquetada con su procedencia.
"""

from typing import Dict, Optional
from datetime import datetime, timedelta

from sharky.config import BASE_CURRENCY, PRICE_CACHE_TTL_SECONDS
from sharky.models import FxRate, PriceSource

# Tasas de referencia de emergencia. Sólo se usan cuando el proveedor no
# responde, y cualquier valoración que dependa de ellas se marca como no fiable.
FALLBACK_RATES_TO_EUR: Dict[str, float] = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.17,
    "GBp": 0.0117,   # peniques (cotizaciones de la LSE)
    "CHF": 1.05,
    "JPY": 0.0060,
    "SEK": 0.088,
    "DKK": 0.134,
    "NOK": 0.086,
}


class FxProvider:
    """Obtiene tipos de cambio hacia la divisa base, con caché y fallback."""

    def __init__(self, base_currency: str = BASE_CURRENCY, ttl_seconds: int = PRICE_CACHE_TTL_SECONDS):
        self.base_currency = base_currency.upper()
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache: Dict[str, FxRate] = {}
        try:
            import yfinance as yf
            self.yf = yf
            self.has_yfinance = True
        except ImportError:
            self.yf = None
            self.has_yfinance = False

    def get_rate(self, from_currency: str) -> FxRate:
        """Devuelve el tipo de cambio `from_currency` -> divisa base.

        `GBp` (peniques) se distingue de `GBP` (libras): Yahoo cotiza los ETF de
        la LSE en peniques, y confundirlos es un error de factor 100.
        """
        origen = (from_currency or self.base_currency).strip()

        # Subunidades: se cotizan en centésimas de la divisa principal.
        subunidades = {"GBp": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}
        divisa_matriz, divisor = subunidades.get(origen, (origen.upper(), 1.0))

        if divisa_matriz == self.base_currency and divisor == 1.0:
            return FxRate(par=f"{self.base_currency}/{self.base_currency}", tasa=1.0)

        cached = self._cache.get(origen)
        if cached and (datetime.now() - cached.timestamp) < self.ttl:
            return FxRate(
                par=cached.par,
                tasa=cached.tasa,
                fuente=PriceSource.CACHE if cached.fuente.es_fiable else cached.fuente,
                timestamp=cached.timestamp,
            )

        par = f"{origen}/{self.base_currency}"
        bruta = self._fetch_live_rate(divisa_matriz)
        if bruta is not None and bruta > 0:
            fx = FxRate(par=par, tasa=bruta / divisor, fuente=PriceSource.MERCADO)
            self._cache[origen] = fx
            return fx

        fallback = FALLBACK_RATES_TO_EUR.get(origen)
        if fallback is None:
            base = FALLBACK_RATES_TO_EUR.get(divisa_matriz)
            fallback = base / divisor if base is not None else None
        if fallback is None:
            raise ValueError(
                f"No hay tipo de cambio disponible para {origen} -> {self.base_currency}. "
                f"Añádelo a FALLBACK_RATES_TO_EUR o corrige la divisa de la posición."
            )
        return FxRate(par=par, tasa=fallback, fuente=PriceSource.SIMULADO)

    def _fetch_live_rate(self, currency: str) -> Optional[float]:
        if not self.has_yfinance:
            return None
        symbol = f"{currency}{self.base_currency}=X"
        try:
            hist = self.yf.Ticker(symbol).history(period="5d")
            if hist is None or hist.empty or "Close" not in hist:
                return None
            closes = hist["Close"].dropna()
            if closes.empty:
                return None
            valor = float(closes.iloc[-1])
            return valor if valor > 0 else None
        except Exception:
            return None

    def to_base(self, amount: float, from_currency: str) -> tuple:
        """Convierte `amount` a la divisa base. Devuelve (importe, FxRate)."""
        fx = self.get_rate(from_currency)
        return round(amount * fx.tasa, 6), fx
