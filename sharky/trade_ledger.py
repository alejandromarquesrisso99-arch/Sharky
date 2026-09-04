"""
Registro de operaciones sobre el libro de posiciones.

Sharky no envía órdenes a ningún broker: tú ejecutas en Trade Republic y
registras aquí lo ejecutado. Este módulo es el único camino por el que una
operación entra en `Cartera_Real.md`, y obliga a pasar por el `RiskGovernor`
antes de escribir nada.

Método de coste: **coste medio ponderado**. Una ampliación promedia el coste
unitario; una venta parcial no altera el coste medio de lo que queda.
"""

from typing import Optional
from datetime import datetime
import uuid

from pydantic import BaseModel

from sharky.config import EXECUTION_MODE
from sharky.fx import FxProvider
from sharky.market_data import MarketDataProvider
from sharky.models import (
    AssetClass,
    ExecutionMode,
    OrderStatus,
    OrderType,
    Position,
    TradeOrder,
)
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.risk_governor import RiskGovernor
from sharky.vault_manager import VaultManager

TOLERANCIA_UNIDADES = 1e-8


class TradeResult(BaseModel):
    aprobada: bool
    motivo: str
    orden: Optional[TradeOrder] = None
    pnl_realizado_eur: Optional[float] = None
    nota_operacion: Optional[str] = None
    nav_posterior_eur: Optional[float] = None
    efectivo_posterior_eur: Optional[float] = None


class TradeRecorder:
    def __init__(
        self,
        store: Optional[PortfolioStore] = None,
        valuator: Optional[PortfolioValuator] = None,
        governor: Optional[RiskGovernor] = None,
        vault: Optional[VaultManager] = None,
        fx: Optional[FxProvider] = None,
        market: Optional[MarketDataProvider] = None,
    ):
        self.store = store or PortfolioStore()
        self.market = market or MarketDataProvider()
        self.fx = fx or FxProvider()
        self.valuator = valuator or PortfolioValuator(market=self.market, fx=self.fx)
        self.governor = governor or RiskGovernor()
        self.vault = vault or VaultManager()

    def record(
        self,
        ticker: str,
        tipo_orden: OrderType,
        unidades: float,
        precio: float,
        divisa: Optional[str] = None,
        comision_eur: float = 0.0,
        stop_loss: float = 0.0,
        target_precio: float = 0.0,
        tesis_referencia: str = "",
        justificacion: str = "",
        nombre: Optional[str] = None,
        isin: Optional[str] = None,
        ticker_cotizacion: Optional[str] = None,
        clase: AssetClass = AssetClass.ACCION,
        sector: str = "",
        modo: Optional[ExecutionMode] = None,
        forzar: bool = False,
    ) -> TradeResult:
        """Valida y, si procede, asienta una operación en el libro.

        `forzar=True` registra la operación aunque incumpla el mandato de
        `Reglas_De_Supervivencia.md` (tope por activo, sector, suelo de
        liquidez, stop-loss obligatorio, ratio R:R, estado vital). Decisión
        explícita del usuario (2026-09): el mandato es una guía de Sharky
        hacia él, no una autorización que Sharky le exige a él -- las
        órdenes son suyas y se registran, con aviso, aunque las salte.

        Lo que `forzar` NO se salta -- porque no son límites del mandato
        sino imposibilidades de hecho -- son las comprobaciones de arriba
        (precio/unidades positivos, venta sin posición o por más unidades
        de las que hay): esas ya han cortado la ejecución antes de llegar
        aquí, así que cuando `validate_order` rechaza en este punto, el
        motivo es siempre de mandato, nunca de dato imposible.
        """
        portfolio = self.store.load()
        valuation = self.valuator.value(portfolio)
        health_previa = self.vault.read_health_status()
        # Estado vital recalculado con el NAV de ahora, sin gastar energía.
        health = self.governor.calculate_health(
            health_previa, valuation, dias_transcurridos=0.0, actualizar_energia=False
        )

        existente = portfolio.get(ticker)
        if unidades <= 0:
            return TradeResult(aprobada=False, motivo="RECHAZADA: las unidades deben ser positivas.")
        if precio <= 0:
            return TradeResult(aprobada=False, motivo="RECHAZADA: el precio debe ser positivo.")

        # Divisa: la de la posición existente manda; si no, la indicada o la del registro.
        if divisa:
            divisa_op = divisa
        elif existente:
            divisa_op = existente.divisa_cotizacion
        else:
            divisa_op = self.market.resolve(ticker)[1]

        try:
            fx = self.fx.get_rate(divisa_op)
        except ValueError as exc:
            return TradeResult(aprobada=False, motivo=f"RECHAZADA: {exc}")

        precio_eur = precio * fx.tasa
        bruto_eur = round(unidades * precio_eur, 2)
        sector_efectivo = sector or (existente.sector if existente else "")

        if tipo_orden == OrderType.VENTA:
            if existente is None:
                return TradeResult(
                    aprobada=False,
                    motivo=f"RECHAZADA: no hay posición abierta en {ticker}.",
                )
            if unidades > existente.unidades + TOLERANCIA_UNIDADES:
                return TradeResult(
                    aprobada=False,
                    motivo=(
                        f"RECHAZADA: intentas vender {unidades:,.6f} títulos de {ticker} "
                        f"pero sólo posees {existente.unidades:,.6f}."
                    ),
                )

        orden = TradeOrder(
            id_operacion=f"OP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
            modo=modo or (ExecutionMode.REAL if EXECUTION_MODE == "REAL" else ExecutionMode.PAPER_TRADING),
            ticker=existente.ticker if existente else ticker,
            tipo_orden=tipo_orden,
            cantidad_acciones=unidades,
            precio_ejecutado=precio,
            divisa_ejecucion=divisa_op,
            tipo_cambio_a_eur=round(fx.tasa, 8),
            total_invertido_eur=bruto_eur,
            comision_eur=round(comision_eur, 2),
            stop_loss=stop_loss,
            target_precio=target_precio,
            estado=OrderStatus.ABIERTA,
            tesis_referencia=tesis_referencia,
            justificacion=justificacion,
        )

        aprobada, motivo = self.governor.validate_order(
            orden, health, valuation=valuation, sector=sector_efectivo
        )
        if not aprobada:
            if not forzar:
                return TradeResult(aprobada=False, motivo=motivo, orden=orden)
            motivo = (
                "⚠️ MANDATO INCUMPLIDO -- registrada por decisión explícita del "
                f"usuario (--forzar). Aviso del RiskGovernor: {motivo}"
            )

        # ---------------- Asiento contable ----------------
        pnl_realizado: Optional[float] = None

        if tipo_orden == OrderType.COMPRA:
            if existente is None:
                portfolio.posiciones.append(
                    Position(
                        ticker=ticker,
                        nombre=nombre or ticker,
                        isin=isin,
                        ticker_cotizacion=ticker_cotizacion or self.market.resolve(ticker)[0],
                        divisa_cotizacion=divisa_op,
                        clase=clase,
                        unidades=unidades,
                        # La comisión se capitaliza en el coste de adquisición.
                        coste_unitario_eur=round((bruto_eur + orden.comision_eur) / unidades, 6),
                        sector=sector_efectivo,
                        nota_activo=f"[[{ticker}]]",
                    )
                )
            else:
                coste_anterior = existente.unidades * existente.coste_unitario_eur
                unidades_nuevas = existente.unidades + unidades
                existente.coste_unitario_eur = round(
                    (coste_anterior + bruto_eur + orden.comision_eur) / unidades_nuevas, 6
                )
                existente.unidades = unidades_nuevas
            portfolio.efectivo_eur = round(
                portfolio.efectivo_eur - bruto_eur - orden.comision_eur, 2
            )
        else:  # VENTA
            # Invariante ya garantizado más arriba: una VENTA sin `existente` se
            # rechaza antes de llegar aquí (ver el bloque `if existente is None`
            # de la validación). El assert lo deja explícito para el lector y
            # para el analizador de tipos, en vez de confiar en el orden del
            # código para descartar el `Optional`.
            assert existente is not None  # nosec B101 -- invariante interno, no control de acceso
            coste_liberado = round(unidades * existente.coste_unitario_eur, 2)
            pnl_realizado = round(bruto_eur - coste_liberado - orden.comision_eur, 2)
            restantes = existente.unidades - unidades
            if restantes <= TOLERANCIA_UNIDADES:
                portfolio.posiciones = [
                    p for p in portfolio.posiciones if p.ticker != existente.ticker
                ]
                orden.estado = OrderStatus.CERRADA
            else:
                existente.unidades = restantes
            portfolio.efectivo_eur = round(
                portfolio.efectivo_eur + bruto_eur - orden.comision_eur, 2
            )

        self.store.save(portfolio)

        # ---------------- Estado vital tras la operación ----------------
        nueva_valoracion = self.valuator.value(portfolio)
        if pnl_realizado is not None:
            if pnl_realizado > 0:
                health_previa.operaciones_ganadoras += 1
            elif pnl_realizado < 0:
                health_previa.operaciones_perdedoras += 1

        health_posterior = self.governor.calculate_health(
            health_previa, nueva_valoracion, dias_transcurridos=0.0, actualizar_energia=False
        )
        incumplimientos = self.governor.audit_portfolio(nueva_valoracion, health_posterior)
        self.vault.update_health_status(
            health_posterior, valuation=nueva_valoracion, incumplimientos=incumplimientos
        )

        nota = self.vault.write_trade_note(orden, motivo, pnl_realizado_eur=pnl_realizado)

        return TradeResult(
            aprobada=True,
            motivo=motivo,
            orden=orden,
            pnl_realizado_eur=pnl_realizado,
            nota_operacion=str(nota),
            nav_posterior_eur=nueva_valoracion.nav_eur,
            efectivo_posterior_eur=nueva_valoracion.efectivo_eur,
        )
