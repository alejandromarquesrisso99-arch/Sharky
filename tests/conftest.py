"""
Fixtures y dobles de prueba.

Los tests no tocan la red ni la bóveda real: cada uno recibe una bóveda
temporal y proveedores de mercado y divisas deterministas. Así los resultados
no dependen de la cotización del día.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from sharky.models import (
    AssetClass,
    FxRate,
    MarketSnapshot,
    Portfolio,
    Position,
    PriceSource,
)
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.vault_manager import VaultManager


class FakeMarket:
    """Proveedor de mercado con cotizaciones fijas y técnicos opcionales."""

    def __init__(
        self,
        precios: Optional[Dict[str, Tuple[float, str]]] = None,
        tecnicos: Optional[Dict[str, Dict[str, float]]] = None,
        fuente: PriceSource = PriceSource.MERCADO,
    ):
        self.precios = precios or {}
        self.tecnicos = tecnicos or {}
        self.fuente = fuente
        self.discrepancias_divisa: List[str] = []
        self.llamadas: List[str] = []

    def resolve(self, ticker: str) -> Tuple[Optional[str], str]:
        clave = ticker.upper().strip()
        if clave in {k.upper() for k in self.precios}:
            return clave, self._divisa(clave)
        return clave, "USD"

    def _divisa(self, ticker: str) -> str:
        for k, (_, div) in self.precios.items():
            if k.upper() == ticker.upper():
                return div
        return "USD"

    def get_snapshot(
        self,
        ticker: str,
        symbol: Optional[str] = None,
        divisa: Optional[str] = None,
        with_fundamentals: bool = False,
    ) -> MarketSnapshot:
        self.llamadas.append(ticker)
        # El proveedor real cotiza por SÍMBOLO, no por ticker interno: la ficha
        # `Physical_Gold` se cotiza como `IGLN.L`. El doble debe imitarlo o los
        # tests valorarían todo a coste sin querer.
        claves = [k for k in (symbol, ticker) if k]
        entrada = None
        for clave in claves:
            for k, v in self.precios.items():
                if k.upper() == clave.upper():
                    entrada = v
                    break
            if entrada is not None:
                break
        if entrada is None:
            return MarketSnapshot(
                ticker=ticker, precio_actual=0.0, divisa=divisa or "USD",
                fuente=PriceSource.COSTE,
            )
        precio, div = entrada
        return MarketSnapshot(
            ticker=ticker,
            precio_actual=precio,
            divisa=div,
            cambio_diario_pct=0.5,
            pe_ratio=20.0 if with_fundamentals else None,
            market_cap=1e12 if with_fundamentals else None,
            fuente=self.fuente,
            timestamp=datetime.now(),
        )

    def get_batch_snapshots(self, tickers, with_fundamentals: bool = False):
        return {t: self.get_snapshot(t, with_fundamentals=with_fundamentals) for t in dict.fromkeys(tickers)}

    def get_macro_overview(self):
        return self.get_batch_snapshots(["SPY", "QQQ", "TLT", "GLD", "USO"])

    def get_technicals(self, ticker: str, symbol: Optional[str] = None):
        return self.tecnicos.get(ticker)

    def find_symbol_by_isin(self, isin: str):
        return None


class FakeFx:
    """Tipos de cambio fijos. USD/EUR = 0.90 para que las cuentas sean obvias."""

    def __init__(self, tasas: Optional[Dict[str, float]] = None, fuente: PriceSource = PriceSource.MERCADO):
        self.tasas = tasas or {"EUR": 1.0, "USD": 0.90, "HKD": 0.11, "GBp": 0.0117}
        self.fuente = fuente

    def get_rate(self, from_currency: str) -> FxRate:
        divisa = (from_currency or "EUR").strip()
        if divisa not in self.tasas:
            raise ValueError(f"sin tipo de cambio para {divisa}")
        return FxRate(
            par=f"{divisa}/EUR",
            tasa=self.tasas[divisa],
            fuente=PriceSource.MERCADO if divisa == "EUR" else self.fuente,
        )

    def to_base(self, amount: float, from_currency: str):
        fx = self.get_rate(from_currency)
        return round(amount * fx.tasa, 6), fx


@pytest.fixture
def vault_tmp(tmp_path: Path) -> VaultManager:
    """Bóveda temporal con la estructura de carpetas creada."""
    return VaultManager(tmp_path)


@pytest.fixture
def cartera_simple() -> Portfolio:
    """Cartera de 3 posiciones con cuentas redondas.

    A 100 EUR, B 100 USD (=90 EUR) y C sin cotización (se valora a coste).
    """
    return Portfolio(
        fecha_actualizacion="2026-08-31",
        efectivo_eur=1000.0,
        posiciones=[
            Position(
                ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA",
                divisa_cotizacion="EUR", clase=AssetClass.ACCION,
                unidades=10.0, coste_unitario_eur=90.0, sector="Tecnologia",
                nota_activo="[[Alfa]]",
            ),
            Position(
                ticker="BBB", nombre="Beta", ticker_cotizacion="BBB",
                divisa_cotizacion="USD", clase=AssetClass.ACCION,
                unidades=10.0, coste_unitario_eur=80.0, sector="Defensa",
            ),
            Position(
                ticker="CCC", nombre="Gamma sin símbolo", ticker_cotizacion=None,
                divisa_cotizacion="EUR", clase=AssetClass.ETF,
                unidades=5.0, coste_unitario_eur=100.0, sector="Defensa",
            ),
        ],
    )


@pytest.fixture
def market_simple() -> FakeMarket:
    return FakeMarket({"AAA": (100.0, "EUR"), "BBB": (100.0, "USD")})


@pytest.fixture
def valuator_simple(market_simple: FakeMarket) -> PortfolioValuator:
    return PortfolioValuator(market=market_simple, fx=FakeFx())


@pytest.fixture
def store_tmp(tmp_path: Path, cartera_simple: Portfolio) -> PortfolioStore:
    store = PortfolioStore(tmp_path)
    store.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    store.save(cartera_simple)
    return store
