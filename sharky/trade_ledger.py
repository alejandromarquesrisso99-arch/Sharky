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

from sharky import level_watch
from sharky.file_lock import exclusive_lock
from sharky.fx import FxProvider
from sharky.market_data import MarketDataProvider
from sharky.models import (
    AlertStatus,
    AssetClass,
    LevelKind,
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
    # Consecuencias de la operación sobre el ciclo de vida de la convicción:
    # una compra desde una alerta abre tesis y consume la alerta; una venta
    # que deja la posición a cero la cierra. Ver `_ciclo_de_vida_tesis`.
    tesis_abierta: Optional[str] = None
    tesis_cerrada: Optional[str] = None
    alerta_actualizada: Optional[str] = None


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
        # Sin precios de referencia: el libro de posiciones real no se valora
        # con cotizaciones inventadas cuando el mercado falla (ver DATOS-1).
        self.market = market or MarketDataProvider(allow_reference_prices=False)
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
        divisa_niveles: Optional[str] = None,
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
        # El lock protege el libro de posiciones frente a otro proceso
        # escribiendo a la vez (servicio 24/7 + `trade` manual, ver INFRA-4).
        with exclusive_lock(self.store.ledger_path):
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

            # Divisa: la de la posición existente manda; si no, la indicada, o el
            # registro sólo si conoce el ticker -- nunca se asume USD para un
            # instrumento que nunca se declaró (ver FX-1).
            if divisa:
                divisa_op = divisa
            elif existente:
                divisa_op = existente.divisa_cotizacion
            elif self.market.is_known(ticker):
                divisa_op = self.market.resolve(ticker)[1]
            else:
                return TradeResult(
                    aprobada=False,
                    motivo=(
                        f"RECHAZADA: {ticker} no está en el registro de instrumentos y no "
                        "hay posición previa que fije su divisa. Indica --divisa explícita."
                    ),
                )

            try:
                fx = self.fx.get_rate(divisa_op)
            except ValueError as exc:
                return TradeResult(aprobada=False, motivo=f"RECHAZADA: {exc}")

            precio_eur = precio * fx.tasa
            bruto_eur = round(unidades * precio_eur, 2)
            sector_efectivo = sector or (existente.sector if existente else "")

            # Stop y target deben vivir en la divisa de ejecución: es contra lo
            # que `validate_order` compara `precio_ejecutado` directamente. Si la
            # tesis los declaró en otra divisa, se convierten cruzando por EUR
            # antes de construir la orden (ver FX-2).
            stop_loss_op = stop_loss
            target_precio_op = target_precio
            if divisa_niveles and divisa_niveles.upper() != divisa_op.upper():
                try:
                    fx_niveles = self.fx.get_rate(divisa_niveles)
                except ValueError as exc:
                    return TradeResult(aprobada=False, motivo=f"RECHAZADA: {exc}")
                if fx.tasa > 0:
                    factor = fx_niveles.tasa / fx.tasa
                    if stop_loss > 0:
                        stop_loss_op = round(stop_loss * factor, 6)
                    if target_precio > 0:
                        target_precio_op = round(target_precio * factor, 6)

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
                ticker=existente.ticker if existente else ticker,
                tipo_orden=tipo_orden,
                cantidad_acciones=unidades,
                precio_ejecutado=precio,
                divisa_ejecucion=divisa_op,
                tipo_cambio_a_eur=round(fx.tasa, 8),
                total_invertido_eur=bruto_eur,
                comision_eur=round(comision_eur, 2),
                stop_loss=stop_loss_op,
                target_precio=target_precio_op,
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
        # Fuera del lock: sólo protege el libro de posiciones (ver INFRA-4).
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

        # El asiento ya es real y está guardado: un fallo de aquí en adelante no
        # debe deshacerlo (no se puede "revertir" una compra/venta que ya
        # ocurrió en el broker), sólo avisar de qué escritura posterior falló en
        # vez de dejarlo desincronizado en silencio (ver INFRA-3).
        avisos_post_asiento = ""
        niveles_hoy = []
        try:
            # Recarga los niveles que el ciclo diario ya dejó hoy en disco: sin
            # esto, registrar esta operación borraría del cuadro de mandos el
            # aviso de un stop u otro nivel alcanzado esta misma jornada (ver
            # CICLO-1).
            niveles_hoy = level_watch.cargar()
            self.vault.update_health_status(
                health_posterior,
                valuation=nueva_valoracion,
                incumplimientos=incumplimientos,
                alertas_niveles=niveles_hoy,
            )
        except Exception as exc:
            avisos_post_asiento += (
                f"\n\n⚠️ La operación quedó asentada en el libro, pero no se pudo "
                f"actualizar Estado_Vital.md: {exc}"
            )

        nota = None
        try:
            nota = self.vault.write_trade_note(
                orden, motivo + avisos_post_asiento, pnl_realizado_eur=pnl_realizado
            )
        except Exception as exc:
            avisos_post_asiento += f"\n\n⚠️ Tampoco se pudo escribir la nota de la operación: {exc}"

        # Igual que las dos escrituras anteriores: el asiento ya es real y no
        # se deshace porque falle lo que viene después, sólo se avisa.
        tesis_abierta = tesis_cerrada = alerta_actualizada = None
        try:
            tesis_abierta, tesis_cerrada, alerta_actualizada = self._ciclo_de_vida_tesis(
                orden, sector_efectivo, pnl_realizado, niveles_hoy
            )
        except Exception as exc:
            avisos_post_asiento += (
                f"\n\n⚠️ La operación quedó asentada, pero no se pudo actualizar el "
                f"ciclo de vida de la tesis o la alerta: {exc}"
            )

        return TradeResult(
            aprobada=True,
            motivo=motivo + avisos_post_asiento,
            orden=orden,
            pnl_realizado_eur=pnl_realizado,
            nota_operacion=str(nota) if nota else None,
            nav_posterior_eur=nueva_valoracion.nav_eur,
            efectivo_posterior_eur=nueva_valoracion.efectivo_eur,
            tesis_abierta=tesis_abierta,
            tesis_cerrada=tesis_cerrada,
            alerta_actualizada=alerta_actualizada,
        )

    # ------------------------------------------------------------------
    def _ciclo_de_vida_tesis(self, orden, sector, pnl_realizado, niveles_hoy):
        """Abre o cierra la tesis y consume la alerta que originó la compra.

        Hasta 2026-09 este método no existía y las dos puntas del ciclo
        quedaban sueltas:

          * **Al comprar**, la alerta seguía ACTIVA para siempre (vetando el
            ticker en `has_active_alert`) y la posición recién abierta no
            tenía tesis, así que `level_watch` no vigilaba ningún stop --
            aunque la alerta ya traía uno calculado con precios reales.
          * **Al vender**, la tesis se quedaba en `01_Tesis_Activas` sin
            posición, que es justo la condición que la convierte en candidata
            de COMPRA para `MonthlyRebalanceEngine._candidatos`: vender por
            stop dejaba al motor proponiendo recomprarlo el Día 1 siguiente.

        Devuelve `(tesis_abierta, tesis_cerrada, alerta_actualizada)`.
        """
        fecha = orden.fecha_ejecucion.strftime("%Y-%m-%d")
        ticker = orden.ticker
        tesis_abierta = tesis_cerrada = alerta_actualizada = None

        if orden.tipo_orden == OrderType.COMPRA:
            alerta = next(
                (a for _, a in self.vault.list_active_alerts()
                 if a.ticker.upper() == ticker.upper()),
                None,
            )
            if alerta is None:
                return None, None, None

            # Una tesis ya escrita a mano manda sobre la de la alerta: es
            # convicción propia y no se sobrescribe.
            if self.vault.buscar_tesis(ticker) is None:
                ruta = self.vault.crear_tesis_desde_alerta(
                    alerta,
                    fecha_str=fecha,
                    precio_entrada=orden.precio_ejecutado,
                    divisa_entrada=orden.divisa_ejecucion,
                    stop_loss=orden.stop_loss,
                    target_precio=orden.target_precio,
                    sector=sector,
                    id_operacion=orden.id_operacion,
                )
                tesis_abierta = str(ruta)

            ruta_alerta = self.vault.marcar_alerta(
                alerta, AlertStatus.EJECUTADA, fecha,
                motivo=f"Comprada en la operación `{orden.id_operacion}`.",
            )
            alerta_actualizada = str(ruta_alerta) if ruta_alerta else None
            return tesis_abierta, None, alerta_actualizada

        # VENTA: sólo cierra la tesis si la posición queda a cero. Una venta
        # parcial reduce tamaño, no invalida la convicción.
        if orden.estado != OrderStatus.CERRADA:
            return None, None, None

        motivo = "Venta registrada: la posición queda cerrada."
        if any(
            n.tipo is LevelKind.STOP_LOSS and n.ticker.upper() == ticker.upper()
            for n in (niveles_hoy or [])
        ):
            motivo = (
                "Stop-loss alcanzado: salida obligatoria del mandato "
                "([[Reglas_De_Supervivencia]])."
            )
        elif pnl_realizado is not None and pnl_realizado > 0:
            motivo = "Venta con beneficio realizado: toma de beneficios o rotación."

        ruta = self.vault.cerrar_tesis(
            ticker,
            fecha_str=fecha,
            pnl_realizado_eur=pnl_realizado,
            motivo=motivo,
            precio_salida=orden.precio_ejecutado,
            divisa=orden.divisa_ejecucion,
        )
        tesis_cerrada = str(ruta) if ruta else None
        return None, tesis_cerrada, None
