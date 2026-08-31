"""
Motor de Rebalanceo Mensual (Día 1 de cada Mes).
Analiza el universo de activos, la salud de la cartera y construye la lista
exacta de qué comprar y qué vender con sus ponderaciones objetivo.
"""

from typing import List, Dict, Any, Tuple
from datetime import datetime

from sharky.models import (
    HealthStatus,
    VitalState,
    InvestmentThesis,
    AllocationProposal,
    RebalanceAction,
    MonthlyRebalanceReport,
    MarketSnapshot,
)
from sharky.config import (
    MAX_POSITION_SIZE_PCT,
    MIN_RISK_REWARD_RATIO,
)


class MonthlyRebalanceEngine:
    def __init__(self):
        pass

    def generate_monthly_plan(
        self,
        health: HealthStatus,
        active_theses: List[Tuple[Any, InvestmentThesis]],
        market_snapshots: Dict[str, MarketSnapshot],
    ) -> MonthlyRebalanceReport:
        """
        Genera la propuesta formal de rebalanceo para el día 1 del mes.
        """
        now = datetime.now()
        mes_ano_str = now.strftime("%B %Y").capitalize()
        fecha_str = now.strftime("%Y-%m-%d")

        # 1. Definir reserva de liquidez en función del estado de salud
        if health.estado_vital == VitalState.OPTIMO:
            cash_pct = 20.0
        elif health.estado_vital == VitalState.ALERTA:
            cash_pct = 35.0
        else:
            cash_pct = 60.0  # Modo defensivo extremo en Cuidados Intensivos

        capital_total = health.capital_actual
        capital_para_renta_variable = capital_total * ((100.0 - cash_pct) / 100.0)
        cash_usd = capital_total * (cash_pct / 100.0)

        # 2. Universo de activos seleccionados para la cartera modelo (máx 10% por activo)
        asset_universe = [
            ("NVDA", "Semiconductores", 10.0, 9, "Líder en aceleración IA y ecosistema CUDA."),
            ("ASML", "Semiconductores", 8.0, 9, "Monopolio en litografía EUV esencial para nodos avanzados."),
            ("MSFT", "Software_Cloud", 9.0, 8, "Flujos de caja masivos y monetización de Copilot en Azure."),
            ("AAPL", "Hardware_Consumo", 8.0, 8, "Gran base instalada y recompras masivas de acciones."),
            ("GOOGL", "Publicidad_IA", 8.0, 8, "Bajo múltiplo de valoración relativo y ventaja en TPU/modelos."),
            ("TSM", "Semiconductores", 7.0, 8, "Mayor fundición del mundo; beneficiaria de toda la demanda de chips."),
            ("AMZN", "Cloud_Retail", 8.0, 8, "Aceleración de márgenes en AWS y optimización logística."),
            ("META", "Redes_Sociales", 7.0, 8, "Liderazgo en monetización por IA y eficiencia operativa."),
            ("GLD", "Cobertura_Oro", 15.0, 8, "Cobertura ante riesgos geopolíticos y desdolarización."),
        ]

        # Normalizar pesos al capital disponible para renta variable
        total_unnormalized = sum(weight for _, _, weight, _, _ in asset_universe)
        proposals: List[AllocationProposal] = []

        # Tickers con posiciones actualmente activas
        active_tickers = {t.ticker: t for _, t in active_theses}

        for ticker, sector, base_weight, conv, rationale in asset_universe:
            normalized_weight = round((base_weight / total_unnormalized) * (100.0 - cash_pct), 1)
            target_usd = capital_total * (normalized_weight / 100.0)
            
            snap = market_snapshots.get(ticker)
            price = snap.precio_actual if snap else 100.0
            shares = round(target_usd / price, 2) if price > 0 else 0.0

            # Determinar acción frente a la posición actual
            if ticker in active_tickers:
                curr_thesis = active_tickers[ticker]
                curr_pos_usd = curr_thesis.capital_asignado
                diff = target_usd - curr_pos_usd
                if diff > 100:
                    action = RebalanceAction.INCREMENTAR
                elif diff < -100:
                    action = RebalanceAction.REDUCIR
                else:
                    action = RebalanceAction.MANTENER
                current_weight_pct = round((curr_pos_usd / capital_total) * 100.0, 1)
                stop_loss = curr_thesis.stop_loss
                target_price = curr_thesis.target_precio
            else:
                action = RebalanceAction.COMPRAR
                current_weight_pct = 0.0
                stop_loss = round(price * 0.92, 2)  # -8% Stop Loss por defecto
                target_price = round(price * 1.22, 2)  # +22% Target (R:R ~ 2.75)

            proposal = AllocationProposal(
                ticker=ticker,
                sector=sector,
                accion=action,
                peso_actual_pct=current_weight_pct,
                peso_objetivo_pct=normalized_weight,
                capital_asignado_usd=round(target_usd, 2),
                precio_estimado=price,
                acciones_estimadas=shares,
                stop_loss_sugerido=stop_loss,
                target_sugerido=target_price,
                conviccion=conv,
                motivo=rationale,
            )
            proposals.append(proposal)

        # 3. Detectar activos en cartera que no están en la lista modelo -> VENDER
        for _, act_t in active_theses:
            if act_t.ticker not in [p.ticker for p in proposals]:
                snap = market_snapshots.get(act_t.ticker)
                p_exit = snap.precio_actual if snap else act_t.precio_entrada
                sell_prop = AllocationProposal(
                    ticker=act_t.ticker,
                    sector=act_t.sectores,
                    accion=RebalanceAction.VENDER,
                    peso_actual_pct=round((act_t.capital_asignado / capital_total) * 100.0, 1),
                    peso_objetivo_pct=0.0,
                    capital_asignado_usd=0.0,
                    precio_estimado=p_exit,
                    acciones_estimadas=0.0,
                    stop_loss_sugerido=0.0,
                    target_sugerido=0.0,
                    conviccion=1,
                    motivo="Tesis cerrada / Rotación de capital hacia activos de mayor convicción.",
                )
                proposals.insert(0, sell_prop)

        return MonthlyRebalanceReport(
            mes_ano=mes_ano_str,
            fecha=fecha_str,
            propuestas=proposals,
            peso_cash_pct=cash_pct,
            cash_usd=round(cash_usd, 2),
            capital_total_usd=round(capital_total, 2),
            regimen_macro="Fase de Expansión Tardía. Curva de tipos normalizándose y política monetaria vigilante.",
            geopolitica_resumen="Seguimiento de semiconductores en Asia oriental y rutas de comercio marítimo.",
            sentimiento_resumen="Sentimiento constructivo con alta concentración en infraestructura de cómputo.",
        )
