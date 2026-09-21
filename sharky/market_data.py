"""
Proveedor de datos de mercado para Sharky.

Reglas de honestidad de este módulo:
  * Toda cotización devuelve su divisa real y su procedencia (`PriceSource`).
    Nunca se entrega un precio simulado disfrazado de precio de mercado.
  * Cuando el proveedor declara una divisa distinta a la esperada, se usa la del
    proveedor y se registra la discrepancia: suele indicar un símbolo mal mapeado
    (p.ej. una línea de la LSE cotizada en peniques).
  * Hay caché con TTL para que el servicio 24/7 no castigue la API externa.
"""

from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import logging
import math
import threading

from sharky.config import PRICE_CACHE_TTL_SECONDS
from sharky.models import MarketSnapshot, PriceSource

# yfinance escribe trazas de error en stderr que ensucian los informes de la CLI.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

MACRO_TICKERS = ["SPY", "QQQ", "TLT", "GLD", "USO"]
CORE_WATCHLIST = [
    "NVDA", "ASML", "MSFT", "AAPL", "GOOGL", "TSM", "AMZN", "META",
    # Ampliación 2026-09: exposición a los ejes geopolíticos que ya
    # sostienen buena parte de la cartera real (rearme, minerales
    # críticos, ciclo nuclear, electrificación de la IA, ciberseguridad
    # como infraestructura crítica) pero en nombres individuales nuevos,
    # no ya cubiertos por los ETF que ya tienes. Ver UNIVERSO_CONVICCION
    # en opportunity_detector.py para la tesis de cada uno.
    "LDO", "GEV", "VRT", "CCJ", "MP", "CRWD",
]

# Registro de instrumentos: ticker interno -> (símbolo del proveedor, divisa de
# cotización esperada). El libro de posiciones puede sobrescribir ambos valores.
INSTRUMENT_REGISTRY: Dict[str, Tuple[str, str]] = {
    # Referencias macro (todas cotizan en USD)
    "SPY": ("SPY", "USD"),
    "QQQ": ("QQQ", "USD"),
    "TLT": ("TLT", "USD"),
    "GLD": ("GLD", "USD"),
    "USO": ("USO", "USD"),
    # Universo de vigilancia en mercados USA
    "NVDA": ("NVDA", "USD"),
    "ASML": ("ASML", "USD"),
    "MSFT": ("MSFT", "USD"),
    "AAPL": ("AAPL", "USD"),
    "GOOGL": ("GOOGL", "USD"),
    "TSM": ("TSM", "USD"),
    "AMZN": ("AMZN", "USD"),
    "META": ("META", "USD"),
    "BLK": ("BLK", "USD"),
    "LMT": ("LMT", "USD"),
    "NIO": ("NIO", "USD"),
    # Líneas europeas de la cartera real
    "RHM": ("RHM.DE", "EUR"),
    "NOK": ("NOKIA.HE", "EUR"),
    # Cripto cotizada directamente contra EUR
    "BTC": ("BTC-EUR", "EUR"),
    # Ampliación 2026-09: ejes geopolíticos (rearme europeo, electrificación
    # de la IA, ciclo del uranio, minerales críticos, ciberseguridad).
    "LDO": ("LDO.MI", "EUR"),   # Leonardo S.p.A., Borsa Italiana
    "GEV": ("GEV", "USD"),      # GE Vernova
    "VRT": ("VRT", "USD"),      # Vertiv Holdings
    "CCJ": ("CCJ", "USD"),      # Cameco Corporation
    "MP": ("MP", "USD"),        # MP Materials
    "CRWD": ("CRWD", "USD"),    # CrowdStrike Holdings
}

# Cotizaciones de referencia para demos y tests deterministas. NO son datos de
# mercado: todo snapshot que salga de aquí se marca como PriceSource.SIMULADO.
REFERENCE_PRICES: Dict[str, Tuple[float, float, str]] = {
    "SPY": (560.20, 0.4, "USD"),
    "QQQ": (485.50, 0.7, "USD"),
    "TLT": (95.40, -0.3, "USD"),
    "GLD": (230.10, 0.5, "USD"),
    "USO": (78.30, -0.8, "USD"),
    "NVDA": (125.50, 1.8, "USD"),
    "ASML": (870.00, -0.4, "USD"),
    "MSFT": (442.00, 0.5, "USD"),
    "AAPL": (224.30, 0.2, "USD"),
    "GOOGL": (168.90, 1.1, "USD"),
    "TSM": (175.40, 2.3, "USD"),
    "AMZN": (178.50, 0.9, "USD"),
    "META": (510.80, 1.4, "USD"),
    "BLK": (998.00, 0.1, "USD"),
    "LMT": (492.50, 1.2, "USD"),
    "NIO": (3.75, 3.3, "USD"),
    "RHM": (1145.00, 0.5, "EUR"),
    "NOK": (8.90, 0.7, "EUR"),
    "BTC": (58000.00, 1.5, "EUR"),
    "LDO": (48.00, 0.6, "EUR"),
    "GEV": (390.00, 1.0, "USD"),
    "VRT": (145.00, 0.8, "USD"),
    "CCJ": (72.00, 1.5, "USD"),
    "MP": (58.00, 2.0, "USD"),
    "CRWD": (450.00, 0.9, "USD"),
}


class MarketDataProvider:
    def __init__(self, ttl_seconds: int = PRICE_CACHE_TTL_SECONDS, allow_reference_prices: bool = True):
        self.ttl = timedelta(seconds=ttl_seconds)
        self.allow_reference_prices = allow_reference_prices
        self._cache: Dict[str, MarketSnapshot] = {}
        self._tecnicos_cache: Dict[str, Tuple[datetime, Dict[str, float]]] = {}
        self._lock = threading.Lock()
        self.discrepancias_divisa: List[str] = []
        try:
            import yfinance as yf
            self.yf = yf
            self.has_yfinance = True
        except ImportError:
            self.yf = None
            self.has_yfinance = False

    # ------------------------------------------------------------------
    # Resolución de símbolos
    # ------------------------------------------------------------------
    def resolve(self, ticker: str) -> Tuple[Optional[str], str]:
        """Devuelve (símbolo del proveedor, divisa esperada) para un ticker."""
        clave = ticker.upper().strip()
        if clave in INSTRUMENT_REGISTRY:
            return INSTRUMENT_REGISTRY[clave]
        # Ticker desconocido: se intenta tal cual y se asume USD, la divisa por
        # defecto de Yahoo para símbolos sin sufijo de mercado.
        return clave, "USD"

    @staticmethod
    def is_known(ticker: str) -> bool:
        """True si el ticker está en `INSTRUMENT_REGISTRY`.

        A diferencia de `resolve`, no fabrica una divisa por defecto: lo usa
        `TradeRecorder` para exigir `--divisa` explícita en vez de asumir USD
        para un instrumento que nunca se declaró.
        """
        return ticker.upper().strip() in INSTRUMENT_REGISTRY

    # ------------------------------------------------------------------
    # Cotización individual
    # ------------------------------------------------------------------
    def get_snapshot(
        self,
        ticker: str,
        symbol: Optional[str] = None,
        divisa: Optional[str] = None,
        with_fundamentals: bool = False,
    ) -> MarketSnapshot:
        """Instantánea de mercado de un ticker.

        `symbol` y `divisa` permiten al libro de posiciones imponer el mapeo
        correcto sin depender del registro global. Si `symbol` es None, la
        posición no tiene cotización y se devuelve un snapshot marcado COSTE
        para que el valorador use el coste base.
        """
        clave = ticker.upper().strip()
        symbol_resuelto, divisa_esperada = self.resolve(clave)
        symbol = symbol if symbol is not None else symbol_resuelto
        divisa_esperada = (divisa or divisa_esperada or "USD")

        if not symbol:
            return MarketSnapshot(
                ticker=clave,
                precio_actual=0.0,
                divisa=divisa_esperada,
                fuente=PriceSource.COSTE,
            )

        cached = self._get_cached(symbol)
        if cached is not None:
            return cached.model_copy(update={"ticker": clave, "fuente": PriceSource.CACHE})

        live = self._fetch_live(clave, symbol, divisa_esperada, with_fundamentals)
        if live is not None:
            self._put_cached(symbol, live)
            return live

        return self._reference_snapshot(clave, divisa_esperada)

    def _fetch_live(
        self, clave: str, symbol: str, divisa_esperada: str, with_fundamentals: bool
    ) -> Optional[MarketSnapshot]:
        if not self.has_yfinance:
            return None
        try:
            t = self.yf.Ticker(symbol)
            hist = t.history(period="5d")
            if hist is None or hist.empty or "Close" not in hist:
                return None

            closes = hist["Close"].dropna()
            if closes.empty:
                return None
            precio = float(closes.iloc[-1])
            if math.isnan(precio) or precio <= 0:
                return None

            prev = float(closes.iloc[-2]) if len(closes) > 1 else precio
            cambio_pct = ((precio - prev) / prev * 100.0) if prev > 0 else 0.0

            volumen = 0
            if "Volume" in hist:
                vols = hist["Volume"].dropna()
                if not vols.empty:
                    volumen = int(vols.iloc[-1])

            divisa_real = self._detect_currency(t) or divisa_esperada
            if divisa_real.upper() != divisa_esperada.upper():
                aviso = (
                    f"{clave} ({symbol}): el proveedor cotiza en {divisa_real}, "
                    f"no en {divisa_esperada}. Se usa {divisa_real}."
                )
                if aviso not in self.discrepancias_divisa:
                    self.discrepancias_divisa.append(aviso)

            pe_ratio, market_cap = (None, None)
            if with_fundamentals:
                pe_ratio, market_cap = self._fetch_fundamentals(t)

            return MarketSnapshot(
                ticker=clave,
                precio_actual=round(precio, 4),
                divisa=divisa_real,
                cambio_diario_pct=round(cambio_pct, 2),
                volumen=volumen,
                pe_ratio=pe_ratio,
                market_cap=market_cap,
                fuente=PriceSource.MERCADO,
                timestamp=datetime.now(),
            )
        except Exception:
            return None

    @staticmethod
    def _detect_currency(ticker_obj) -> Optional[str]:
        """Divisa declarada por el proveedor. Preserva `GBp` frente a `GBP`."""
        for attr in ("fast_info", "info"):
            try:
                data = getattr(ticker_obj, attr, None)
                if not data:
                    continue
                cur = data.get("currency") if hasattr(data, "get") else None
                if cur:
                    return str(cur)
            # yfinance falla de formas muy distintas según el atributo (red,
            # KeyError, TypeError...); si uno no da la divisa, se prueba el otro.
            except Exception:  # nosec B112
                continue
        return None

    @staticmethod
    def _fetch_fundamentals(ticker_obj) -> Tuple[Optional[float], Optional[float]]:
        """P/E y capitalización reales. Devuelve (None, None) si no hay dato."""
        pe_ratio, market_cap = None, None
        try:
            info = ticker_obj.info or {}
            pe_raw = info.get("trailingPE") or info.get("forwardPE")
            if pe_raw is not None:
                pe_val = float(pe_raw)
                if not math.isnan(pe_val) and pe_val > 0:
                    pe_ratio = round(pe_val, 2)
            mc_raw = info.get("marketCap")
            if mc_raw:
                mc_val = float(mc_raw)
                if not math.isnan(mc_val) and mc_val > 0:
                    market_cap = mc_val
        # Los fundamentales son opcionales: si yfinance falla se devuelve lo
        # que se llegara a leer, y lo que falte queda como None (sin dato).
        except Exception:  # nosec B110
            pass
        return pe_ratio, market_cap

    def _reference_snapshot(self, clave: str, divisa_esperada: str) -> MarketSnapshot:
        """Último recurso: precio de referencia, explícitamente marcado."""
        if not self.allow_reference_prices:
            return MarketSnapshot(
                ticker=clave,
                precio_actual=0.0,
                divisa=divisa_esperada,
                fuente=PriceSource.COSTE,
            )
        precio, cambio, divisa = REFERENCE_PRICES.get(clave, (0.0, 0.0, divisa_esperada))
        if precio <= 0:
            return MarketSnapshot(
                ticker=clave,
                precio_actual=0.0,
                divisa=divisa_esperada,
                fuente=PriceSource.COSTE,
            )
        return MarketSnapshot(
            ticker=clave,
            precio_actual=precio,
            divisa=divisa,
            cambio_diario_pct=cambio,
            fuente=PriceSource.SIMULADO,
        )

    # ------------------------------------------------------------------
    # Caché
    # ------------------------------------------------------------------
    def _get_cached(self, symbol: str) -> Optional[MarketSnapshot]:
        with self._lock:
            snap = self._cache.get(symbol)
            if snap and (datetime.now() - snap.timestamp) < self.ttl:
                return snap
        return None

    def _put_cached(self, symbol: str, snap: MarketSnapshot) -> None:
        with self._lock:
            self._cache[symbol] = snap

    # ------------------------------------------------------------------
    # Lotes
    # ------------------------------------------------------------------
    def get_batch_snapshots(
        self, tickers: List[str], with_fundamentals: bool = False
    ) -> Dict[str, MarketSnapshot]:
        """Cotizaciones en paralelo. La clave del dict es el ticker interno."""
        unicos = [t for t in dict.fromkeys(t.upper().strip() for t in tickers) if t]
        if not unicos:
            return {}

        resultados: Dict[str, MarketSnapshot] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(unicos))) as executor:
            futuros = {
                executor.submit(self.get_snapshot, t, None, None, with_fundamentals): t
                for t in unicos
            }
            for fut in as_completed(futuros):
                t = futuros[fut]
                try:
                    resultados[t] = fut.result()
                except Exception:
                    resultados[t] = self._reference_snapshot(t, self.resolve(t)[1])
        return resultados

    def get_macro_overview(self) -> Dict[str, MarketSnapshot]:
        """Termómetro macro de referencia (SPY, QQQ, TLT, GLD, USO)."""
        return self.get_batch_snapshots(MACRO_TICKERS)

    def get_technicals(self, ticker: str, symbol: Optional[str] = None) -> Optional[Dict[str, float]]:
        """Estructura de precio de los últimos 12 meses.

        Devuelve None si no hay histórico suficiente: sin datos no se emite
        señal, en lugar de inventarse una.
        """
        if not self.has_yfinance:
            return None
        simbolo = symbol or self.resolve(ticker)[0]
        if not simbolo:
            return None

        cacheado = self._tecnicos_cache.get(simbolo)
        if cacheado and (datetime.now() - cacheado[0]) < self.ttl:
            return cacheado[1]

        try:
            hist = self.yf.Ticker(simbolo).history(period="1y")
            if hist is None or hist.empty or "Close" not in hist:
                return None
            cierres = hist["Close"].dropna()
            # Menos de 6 meses de histórico no permite hablar de estructura anual.
            if len(cierres) < 120:
                return None

            precio = float(cierres.iloc[-1])
            maximo = float(cierres.max())
            minimo = float(cierres.min())
            sma200 = float(cierres.tail(200).mean())
            retornos = cierres.pct_change().dropna().tail(20)
            vol_diaria = float(retornos.std()) if len(retornos) > 5 else 0.0

            if precio <= 0 or maximo <= 0:
                return None

            tecnicos = {
                "precio": precio,
                "max_52s": maximo,
                "min_52s": minimo,
                "sma_200": sma200,
                "vol_diaria": vol_diaria,
                "caida_desde_max_pct": round((maximo - precio) / maximo * 100.0, 2),
                "sobre_sma200_pct": round((precio - sma200) / sma200 * 100.0, 2) if sma200 > 0 else 0.0,
            }
            self._tecnicos_cache[simbolo] = (datetime.now(), tecnicos)
            return tecnicos
        except Exception:
            return None

    def find_symbol_by_isin(self, isin: str) -> Optional[str]:
        """Intenta resolver un ISIN a símbolo de Yahoo. Puede devolver None.

        Sirve para completar el libro de posiciones de forma asistida; el
        resultado debe confirmarse a mano antes de darlo por bueno.
        """
        if not self.has_yfinance or not isin:
            return None
        try:
            from yfinance import utils as yf_utils
            resultado = yf_utils.get_ticker_by_isin(isin)
            return resultado or None
        except Exception:
            return None
