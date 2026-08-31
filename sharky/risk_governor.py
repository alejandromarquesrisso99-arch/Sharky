"""
Gobernador de Riesgo y Motor de Supervivencia de Sharky.
Actúa como un cortafuegos estricto determinista (no-IA) para validar operaciones
y computar la salud biológico-digital del agente.
"""

from typing import Tuple, Optional
from sharky.config import (
    MAX_POSITION_SIZE_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MIN_RISK_REWARD_RATIO,
    DEATH_DRAWDOWN_PCT,
)
from sharky.models import HealthStatus, VitalState, TradeOrder, InvestmentThesis


class RiskGovernor:
    def __init__(self):
        pass

    def validate_order(self, order: TradeOrder, health: HealthStatus) -> Tuple[bool, str]:
        """
        Valida rigurosamente si una orden cumple todas las leyes inmutables de supervivencia.
        Devuelve (es_valida, motivo_rechazo).
        """
        # 1. Verificar si el cerebro está vivo
        if health.estado_vital == VitalState.MUERTE:
            return False, "RECHAZADA: El cerebro está en estado MUERTE. Operaciones bloqueadas."

        if health.estado_vital == VitalState.CUIDADOS_INTENSIVOS:
            return False, "RECHAZADA: Estado CUIDADOS INTENSIVOS. Prohibido abrir nuevas posiciones."

        # 2. Verificar stop-loss obligatorio
        if order.stop_loss <= 0:
            return False, "RECHAZADA: Toda orden debe incluir un stop_loss positivo obligatorio."

        if order.precio_ejecutado <= 0:
            return False, "RECHAZADA: Precio de ejecución inválido."

        # 3. Validar ratio Riesgo/Beneficio
        riesgo_por_accion = abs(order.precio_ejecutado - order.stop_loss)
        beneficio_por_accion = abs(order.target_precio - order.precio_ejecutado)

        if riesgo_por_accion <= 0:
            return False, "RECHAZADA: El stop_loss no puede ser igual al precio de entrada."

        ratio_rr = beneficio_por_accion / riesgo_por_accion
        if ratio_rr < MIN_RISK_REWARD_RATIO:
            return False, f"RECHAZADA: Ratio R:R ({ratio_rr:.2f}) inferior al mínimo ({MIN_RISK_REWARD_RATIO:.2f})."

        # 4. Validar tamaño máximo de posición (% del capital total)
        max_pos_usd = health.capital_actual * (MAX_POSITION_SIZE_PCT / 100.0)
        if order.total_invertido_usd > max_pos_usd:
            return False, f"RECHAZADA: Inversión (${order.total_invertido_usd:,.2f}) excede el {MAX_POSITION_SIZE_PCT}% del capital (${max_pos_usd:,.2f})."

        # 5. Validar riesgo máximo por operación (% del capital total)
        riesgo_total_usd = riesgo_por_accion * order.cantidad_acciones
        max_riesgo_usd = health.capital_actual * (MAX_RISK_PER_TRADE_PCT / 100.0)
        if riesgo_total_usd > max_riesgo_usd:
            return False, f"RECHAZADA: Riesgo monetario (${riesgo_total_usd:,.2f}) supera el {MAX_RISK_PER_TRADE_PCT}% máximo permitido (${max_riesgo_usd:,.2f})."

        return True, "APROBADA: Cumple con todos los parámetros de gestión de riesgo."

    def calculate_health(self, health: HealthStatus, current_pnl_usd: float) -> HealthStatus:
        """Calcula el estado vital, porcentaje de salud y energía metabólica."""
        capital_actual = health.capital_inicial + current_pnl_usd
        pnl_pct = (current_pnl_usd / health.capital_inicial) * 100.0

        # Drawdown frente al capital inicial
        drawdown_pct = max(0.0, ((health.capital_inicial - capital_actual) / health.capital_inicial) * 100.0)
        max_dd = max(health.drawdown_maximo_pct, drawdown_pct)

        # Función de salud (de 100% a 0% cuando drawdown llega al límite de muerte)
        if drawdown_pct >= DEATH_DRAWDOWN_PCT:
            salud_pct = 0.0
            vital_state = VitalState.MUERTE
        else:
            salud_pct = max(0.0, 100.0 * (1.0 - (drawdown_pct / DEATH_DRAWDOWN_PCT)))
            if salud_pct >= 75.0:
                vital_state = VitalState.OPTIMO
            elif salud_pct >= 40.0:
                vital_state = VitalState.ALERTA
            else:
                vital_state = VitalState.CUIDADOS_INTENSIVOS

        # Consumo de energía metabólica diario
        # El cerebro consume energía con el tiempo y la regenera con ganancias
        nueva_energia = max(5.0, min(100.0, health.energia_actual - 2.0 + (pnl_pct * 1.5)))

        total_ops = health.operaciones_ganadoras + health.operaciones_perdedoras
        win_rate = (health.operaciones_ganadoras / total_ops * 100.0) if total_ops > 0 else 0.0

        return HealthStatus(
            estado_vital=vital_state,
            salud_porcentaje=round(salud_pct, 2),
            energia_actual=round(nueva_energia, 2),
            capital_inicial=health.capital_inicial,
            capital_actual=round(capital_actual, 2),
            pnl_total_usd=round(current_pnl_usd, 2),
            pnl_total_pct=round(pnl_pct, 2),
            drawdown_maximo_pct=round(max_dd, 2),
            operaciones_ganadoras=health.operaciones_ganadoras,
            operaciones_perdedoras=health.operaciones_perdedoras,
            win_rate_pct=round(win_rate, 2),
        )
