"""
Gobernador de Riesgo y Motor de Supervivencia de Sharky.

Cortafuegos determinista (sin IA) que implementa literalmente los axiomas de
`vault/00_Sistema/Reglas_De_Supervivencia.md`. Ninguna operación entra en el
libro de posiciones sin pasar por `validate_order`.

Dos decisiones de diseño que corrigen errores conceptuales habituales:
  * El **drawdown** se mide contra el máximo histórico del NAV (high-water
    mark), no contra el capital inicial. Un -8% tras un +30% es un drawdown
    del 8%, no del 0%.
  * En estado crítico se bloquean las **compras**, nunca las ventas: el mandato
    exige poder ejecutar la salida de emergencia por stop-loss precisamente
    cuando la cartera está herida.
"""

import math
from typing import List, Optional, Tuple

from sharky.config import (
    DEATH_DRAWDOWN_PCT,
    DRAWDOWN_ALERTA_MAX_PCT,
    DRAWDOWN_OPTIMO_MAX_PCT,
    MAX_CASH_PCT,
    MAX_POSITION_SIZE_ALERTA_PCT,
    MAX_POSITION_SIZE_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
    MIN_RISK_REWARD_RATIO,
)
from sharky.models import (
    HealthStatus,
    OrderType,
    PortfolioValuation,
    RiskBreach,
    TradeOrder,
    VitalState,
)


def _safe(valor: float, defecto: float = 0.0) -> float:
    if valor is None:
        return defecto
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return defecto
    return defecto if math.isnan(f) or math.isinf(f) else f


class RiskGovernor:
    # ------------------------------------------------------------------
    # Políticas dependientes del estado vital
    # ------------------------------------------------------------------
    def max_position_pct(self, estado: VitalState) -> float:
        """Tope por activo. En ALERTA el mandato lo reduce al 5%."""
        if estado == VitalState.OPTIMO:
            return MAX_POSITION_SIZE_PCT
        if estado == VitalState.ALERTA:
            return MAX_POSITION_SIZE_ALERTA_PCT
        return 0.0  # Crítico o muerto: prohibido abrir o ampliar

    def target_cash_pct(self, estado: VitalState) -> float:
        """Reserva de liquidez objetivo según el estado vital."""
        if estado == VitalState.OPTIMO:
            return MIN_CASH_PCT + 5.0        # 20%: dentro de la banda 15-30%
        if estado == VitalState.ALERTA:
            return MAX_CASH_PCT              # 30% obligatorio
        return 60.0                          # Desinversión defensiva

    @staticmethod
    def clasificar_estado(drawdown_pct: float) -> VitalState:
        """Traduce un drawdown a estado vital según Reglas_De_Supervivencia §3."""
        dd = _safe(drawdown_pct)
        if dd > DEATH_DRAWDOWN_PCT:
            return VitalState.MUERTE
        if dd >= DRAWDOWN_ALERTA_MAX_PCT:
            # Cubre 8-15% y también la franja 15-20%, que el mandato no nombra
            # explícitamente: se resuelve del lado conservador.
            return VitalState.CUIDADOS_INTENSIVOS
        if dd >= DRAWDOWN_OPTIMO_MAX_PCT:
            return VitalState.ALERTA
        return VitalState.OPTIMO

    # ------------------------------------------------------------------
    # Cálculo del estado vital
    # ------------------------------------------------------------------
    def calculate_health(
        self,
        previous: HealthStatus,
        valuation: PortfolioValuation,
        dias_transcurridos: float = 1.0,
        actualizar_energia: bool = True,
    ) -> HealthStatus:
        """Recalcula la salud a partir de una valoración real de la cartera.

        `actualizar_energia=False` revalora la cartera sin consumir energía
        metabólica: lo usan las operaciones puntuales, que no son un ciclo diario.
        """
        nav = _safe(valuation.nav_eur)

        capital_inicial = _safe(previous.capital_inicial_eur)
        if capital_inicial <= 0:
            # Primera ejecución: el NAV de hoy fija la referencia.
            capital_inicial = nav

        # High-water mark persistido: base correcta del drawdown.
        hwm = max(_safe(previous.nav_maximo_historico_eur), capital_inicial, nav)

        drawdown_actual = ((hwm - nav) / hwm * 100.0) if hwm > 0 else 0.0
        drawdown_actual = max(0.0, round(drawdown_actual, 2))
        drawdown_maximo = max(_safe(previous.drawdown_maximo_pct), drawdown_actual)

        estado = self.clasificar_estado(drawdown_actual)

        # Salud: 100% sin drawdown, 0% al alcanzar el umbral de muerte.
        if drawdown_actual >= DEATH_DRAWDOWN_PCT:
            salud = 0.0
        else:
            salud = max(0.0, 100.0 * (1.0 - drawdown_actual / DEATH_DRAWDOWN_PCT))

        pnl_eur = round(nav - capital_inicial, 2)
        pnl_pct = round((pnl_eur / capital_inicial * 100.0), 2) if capital_inicial > 0 else 0.0

        energia = (
            self._calcular_energia(previous, pnl_pct, dias_transcurridos)
            if actualizar_energia
            else _safe(previous.energia_actual, 100.0)
        )

        total_ops = previous.operaciones_ganadoras + previous.operaciones_perdedoras
        win_rate = round(previous.operaciones_ganadoras / total_ops * 100.0, 2) if total_ops else 0.0

        return HealthStatus(
            estado_vital=estado,
            salud_porcentaje=round(salud, 2),
            energia_actual=round(energia, 2),
            capital_inicial_eur=round(capital_inicial, 2),
            nav_actual_eur=round(nav, 2),
            nav_maximo_historico_eur=round(hwm, 2),
            pnl_total_eur=pnl_eur,
            pnl_total_pct=pnl_pct,
            drawdown_actual_pct=drawdown_actual,
            drawdown_maximo_pct=round(drawdown_maximo, 2),
            operaciones_ganadoras=previous.operaciones_ganadoras,
            operaciones_perdedoras=previous.operaciones_perdedoras,
            win_rate_pct=win_rate,
            alertas_activas_count=previous.alertas_activas_count,
            cobertura_datos_pct=round(_safe(valuation.cobertura_mercado_pct, 100.0), 2),
        )

    @staticmethod
    def _calcular_energia(previous: HealthStatus, pnl_pct: float, dias: float) -> float:
        """Energía metabólica: se consume con el tiempo, se repone con retorno.

        El desgaste es proporcional a los **días** transcurridos, no al número de
        veces que se invoca la CLI: si no, ejecutar `daily` diez veces en una hora
        agotaría al agente sin que pasara nada en el mercado.
        """
        dias_efectivos = max(0.0, min(_safe(dias, 1.0), 30.0))
        desgaste = 2.0 * dias_efectivos
        reposicion = _safe(pnl_pct) * 1.5
        return max(0.0, min(100.0, _safe(previous.energia_actual, 100.0) - desgaste + reposicion))

    # ------------------------------------------------------------------
    # Auditoría de la cartera frente a los axiomas
    # ------------------------------------------------------------------
    def audit_portfolio(
        self, valuation: PortfolioValuation, health: HealthStatus
    ) -> List[RiskBreach]:
        """Enumera todos los incumplimientos vigentes del mandato."""
        incumplimientos: List[RiskBreach] = []
        tope_activo = MAX_POSITION_SIZE_PCT
        if health.estado_vital == VitalState.ALERTA:
            tope_activo = MAX_POSITION_SIZE_ALERTA_PCT

        # 1. Concentración por activo
        for pos in valuation.posiciones:
            if pos.peso_pct > tope_activo:
                incumplimientos.append(
                    RiskBreach(
                        regla="Máximo por activo individual",
                        severidad="ALTA",
                        sujeto=pos.ticker,
                        valor_actual_pct=pos.peso_pct,
                        limite_pct=tope_activo,
                        mensaje=(
                            f"{pos.ticker} pesa {pos.peso_pct:.2f}% del NAV, "
                            f"por encima del límite del {tope_activo:.1f}%."
                        ),
                        accion_correctiva=(
                            f"Reducir {pos.ticker} hasta el {tope_activo:.1f}% "
                            f"({pos.valor_mercado_eur - valuation.nav_eur * tope_activo / 100.0:,.2f} € a liberar)."
                        ),
                    )
                )

        # 2. Concentración sectorial
        for sector, peso in valuation.exposicion_sectorial_pct.items():
            if peso > MAX_SECTOR_SIZE_PCT:
                incumplimientos.append(
                    RiskBreach(
                        regla="Máximo por sector industrial",
                        severidad="ALTA",
                        sujeto=sector,
                        valor_actual_pct=peso,
                        limite_pct=MAX_SECTOR_SIZE_PCT,
                        mensaje=(
                            f"El sector {sector} concentra el {peso:.2f}% del NAV, "
                            f"por encima del límite del {MAX_SECTOR_SIZE_PCT:.1f}%."
                        ),
                        accion_correctiva=(
                            f"Recortar exposición a {sector} en "
                            f"{valuation.nav_eur * (peso - MAX_SECTOR_SIZE_PCT) / 100.0:,.2f} €."
                        ),
                    )
                )

        # 3. Reserva de liquidez
        cash_pct = _safe(valuation.peso_efectivo_pct)
        if cash_pct < MIN_CASH_PCT:
            incumplimientos.append(
                RiskBreach(
                    regla="Reserva de supervivencia (Cash)",
                    severidad="ALTA",
                    sujeto="Efectivo",
                    valor_actual_pct=cash_pct,
                    limite_pct=MIN_CASH_PCT,
                    mensaje=(
                        f"La liquidez es del {cash_pct:.2f}%, por debajo del mínimo "
                        f"del {MIN_CASH_PCT:.1f}%. Sin pólvora seca ante una corrección."
                    ),
                    accion_correctiva=(
                        f"Liberar {valuation.nav_eur * (MIN_CASH_PCT - cash_pct) / 100.0:,.2f} € "
                        f"mediante desinversión."
                    ),
                )
            )
        elif cash_pct > MAX_CASH_PCT:
            incumplimientos.append(
                RiskBreach(
                    regla="Reserva de supervivencia (Cash)",
                    severidad="MEDIA",
                    sujeto="Efectivo",
                    valor_actual_pct=cash_pct,
                    limite_pct=MAX_CASH_PCT,
                    mensaje=(
                        f"La liquidez es del {cash_pct:.2f}%, por encima del máximo "
                        f"del {MAX_CASH_PCT:.1f}%: capital ocioso."
                    ),
                    accion_correctiva="Asignar el exceso de caja en el rebalanceo del Día 1.",
                )
            )

        # 4. Fiabilidad de los datos que sustentan todo lo anterior
        cobertura = _safe(valuation.cobertura_mercado_pct, 100.0)
        if cobertura < 100.0:
            incumplimientos.append(
                RiskBreach(
                    regla="Integridad de los datos de valoración",
                    severidad="MEDIA",
                    sujeto="Cartera",
                    valor_actual_pct=cobertura,
                    limite_pct=100.0,
                    mensaje=(
                        f"Sólo el {cobertura:.1f}% del NAV está respaldado por cotizaciones "
                        f"fiables; el resto se valora a coste."
                    ),
                    accion_correctiva=(
                        "Completar `ticker_cotizacion` en [[Cartera_Real]] para las "
                        "posiciones afectadas."
                    ),
                )
            )

        return incumplimientos

    # ------------------------------------------------------------------
    # Validación de órdenes
    # ------------------------------------------------------------------
    def validate_order(
        self,
        order: TradeOrder,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation] = None,
        sector: str = "",
    ) -> Tuple[bool, str]:
        """Valida una orden contra las leyes de supervivencia.

        Devuelve `(aprobada, motivo)`. Las ventas se evalúan con criterios
        deliberadamente laxos: desinvertir es siempre una vía de escape legítima.
        """
        es_venta = order.tipo_orden == OrderType.VENTA

        # 1. Estado vital
        if health.estado_vital == VitalState.MUERTE and not es_venta:
            return False, "RECHAZADA: estado MUERTE. Sólo se permite desinversión."
        if health.estado_vital == VitalState.CUIDADOS_INTENSIVOS and not es_venta:
            return (
                False,
                "RECHAZADA: estado CUIDADOS INTENSIVOS. Prohibido abrir o ampliar "
                "posiciones; sólo desinversión defensiva.",
            )

        # 2. Sanidad de los importes
        if order.precio_ejecutado <= 0 or math.isnan(order.precio_ejecutado):
            return False, "RECHAZADA: precio de ejecución inválido."
        if order.cantidad_acciones <= 0 or math.isnan(order.cantidad_acciones):
            return False, "RECHAZADA: cantidad de títulos inválida."
        if order.total_invertido_eur <= 0 or math.isnan(order.total_invertido_eur):
            return False, "RECHAZADA: importe total en EUR inválido."

        if es_venta:
            return True, "APROBADA: desinversión permitida en cualquier estado vital."

        # --- A partir de aquí, sólo compras ---

        # 3. Stop-loss obligatorio
        if order.stop_loss <= 0 or math.isnan(order.stop_loss):
            return False, "RECHAZADA: toda compra debe declarar un stop_loss positivo."
        if order.stop_loss >= order.precio_ejecutado:
            return False, (
                f"RECHAZADA: el stop_loss ({order.stop_loss:,.2f}) debe estar por debajo "
                f"del precio de entrada ({order.precio_ejecutado:,.2f})."
            )

        # 4. Ratio riesgo/beneficio
        riesgo_titulo = order.precio_ejecutado - order.stop_loss
        beneficio_titulo = order.target_precio - order.precio_ejecutado
        if beneficio_titulo <= 0:
            return False, (
                f"RECHAZADA: el target ({order.target_precio:,.2f}) debe superar el "
                f"precio de entrada ({order.precio_ejecutado:,.2f})."
            )
        ratio_rr = beneficio_titulo / riesgo_titulo
        if ratio_rr < MIN_RISK_REWARD_RATIO:
            return False, (
                f"RECHAZADA: ratio R:R ({ratio_rr:.2f}) inferior al mínimo "
                f"({MIN_RISK_REWARD_RATIO:.2f})."
            )

        nav = _safe(health.nav_actual_eur)
        if nav <= 0:
            return False, "RECHAZADA: NAV no disponible; imposible dimensionar el riesgo."

        # 5. Tope por activo, contando la posición que ya se tenga
        tope_pct = self.max_position_pct(health.estado_vital)
        if tope_pct <= 0:
            return False, "RECHAZADA: el estado vital actual no admite nuevas compras."

        exposicion_previa_eur = 0.0
        if valuation is not None:
            for pos in valuation.posiciones:
                if pos.ticker.upper() == order.ticker.upper():
                    exposicion_previa_eur = pos.valor_mercado_eur
                    if not sector:
                        sector = pos.sector
                    break

        exposicion_final_eur = exposicion_previa_eur + order.total_invertido_eur
        exposicion_final_pct = exposicion_final_eur / nav * 100.0
        if exposicion_final_pct > tope_pct:
            return False, (
                f"RECHAZADA: {order.ticker} quedaría al {exposicion_final_pct:.2f}% del NAV "
                f"(límite {tope_pct:.1f}%). Máximo invertible ahora: "
                f"{max(0.0, nav * tope_pct / 100.0 - exposicion_previa_eur):,.2f} €."
            )

        # 6. Riesgo monetario máximo por operación
        riesgo_total_eur = riesgo_titulo * order.cantidad_acciones * _safe(order.tipo_cambio_a_eur, 1.0)
        max_riesgo_eur = nav * MAX_RISK_PER_TRADE_PCT / 100.0
        if riesgo_total_eur > max_riesgo_eur:
            return False, (
                f"RECHAZADA: riesgo de {riesgo_total_eur:,.2f} € (hasta el stop) supera el "
                f"{MAX_RISK_PER_TRADE_PCT}% del NAV ({max_riesgo_eur:,.2f} €)."
            )

        if valuation is not None:
            # 7. Tope sectorial tras la compra
            if sector:
                peso_sector = _safe(valuation.exposicion_sectorial_pct.get(sector, 0.0))
                peso_sector_final = peso_sector + order.total_invertido_eur / nav * 100.0
                if peso_sector_final > MAX_SECTOR_SIZE_PCT:
                    return False, (
                        f"RECHAZADA: el sector {sector} quedaría al {peso_sector_final:.2f}% "
                        f"(límite {MAX_SECTOR_SIZE_PCT:.1f}%)."
                    )

            # 8. Suelo de liquidez tras la compra
            efectivo_final = valuation.efectivo_eur - order.total_invertido_eur - order.comision_eur
            if efectivo_final < 0:
                return False, (
                    f"RECHAZADA: liquidez insuficiente. Disponible "
                    f"{valuation.efectivo_eur:,.2f} €, requerido "
                    f"{order.total_invertido_eur + order.comision_eur:,.2f} €."
                )
            cash_final_pct = efectivo_final / nav * 100.0
            if cash_final_pct < MIN_CASH_PCT:
                return False, (
                    f"RECHAZADA: la liquidez caería al {cash_final_pct:.2f}%, por debajo del "
                    f"mínimo del {MIN_CASH_PCT:.1f}% exigido por el mandato."
                )

        return True, (
            f"APROBADA: R:R {ratio_rr:.2f}, peso final {exposicion_final_pct:.2f}% del NAV, "
            f"riesgo {riesgo_total_eur:,.2f} € ({riesgo_total_eur / nav * 100.0:.2f}% del NAV)."
        )
