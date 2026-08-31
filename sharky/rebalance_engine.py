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

        # 2. Asignación Estratégica Combinada (Tesis Activas de Bóveda + Oportunidades Modelo)
        proposals: List[AllocationProposal] = []
        active_tickers = {t.ticker: t for _, t in active_theses}
        
        # Universo de activos estratégicos candidatos
        model_candidates = [
            ("NVDA", "Semiconductores", 9.0, 9, "Líder en aceleración IA y ecosistema CUDA."),
            ("ASML", "Semiconductores", 8.0, 9, "Monopolio en litografía EUV esencial para nodos avanzados."),
            ("MSFT", "Software_Cloud", 9.0, 9, "Flujos de caja masivos y monetización de Copilot en Azure."),
            ("TSM", "Semiconductores", 8.0, 8, "Mayor fundición del mundo; beneficiaria de la demanda global."),
            ("GOOGL", "Publicidad_IA", 7.0, 8, "Bajo múltiplo de valoración relativo y ventaja en TPU/modelos."),
            ("GLD", "Cobertura_Oro", 10.0, 8, "Cobertura ante riesgos geopolíticos y desdolarización."),
        ]

        # 3. Procesar primero las tesis activas de la cartera
        assigned_equity_pct = 0.0
        processed_tickers = set()

        for _, thesis in active_theses:
            ticker = thesis.ticker
            processed_tickers.add(ticker)
            snap = market_snapshots.get(ticker)
            price = snap.precio_actual if snap else thesis.precio_entrada
            
            cantidad_acc = (thesis.capital_asignado / thesis.precio_entrada) if thesis.precio_entrada > 0 else 0.0
            curr_pos_usd = round(cantidad_acc * price, 2) if price > 0 else thesis.capital_asignado
            current_weight_pct = round((curr_pos_usd / capital_total) * 100.0, 1) if capital_total > 0 else 0.0

            # Aplicar directiva del CRO: tope máximo del 10.0% por activo
            if current_weight_pct > MAX_POSITION_SIZE_PCT:
                target_weight_pct = MAX_POSITION_SIZE_PCT
                action = RebalanceAction.REDUCIR
                motivo = f"Trimming obligatorio por CRO: Reducir del {current_weight_pct:.1f}% al límite prudencial del {MAX_POSITION_SIZE_PCT:.1f}%."
            else:
                target_weight_pct = min(current_weight_pct, MAX_POSITION_SIZE_PCT)
                if target_weight_pct == 0.0:
                    target_weight_pct = min(8.0, MAX_POSITION_SIZE_PCT)
                    action = RebalanceAction.COMPRAR
                    motivo = f"Apertura táctica según tesis activa [[Tesis_{thesis.ticker}]]."
                else:
                    action = RebalanceAction.MANTENER
                    motivo = f"Mantenimiento de posición core en {thesis.sectores}."

            target_usd = round(capital_total * (target_weight_pct / 100.0), 2)
            shares = round(target_usd / price, 2) if price > 0 else 0.0

            proposal = AllocationProposal(
                ticker=ticker,
                sector=thesis.sectores.replace("[[", "").replace("]]", ""),
                accion=action,
                peso_actual_pct=current_weight_pct,
                peso_objetivo_pct=target_weight_pct,
                capital_asignado_usd=target_usd,
                precio_estimado=price,
                acciones_estimadas=shares,
                stop_loss_sugerido=thesis.stop_loss,
                target_sugerido=thesis.target_precio,
                conviccion=thesis.conviccion,
                motivo=motivo,
            )
            proposals.append(proposal)
            assigned_equity_pct += target_weight_pct

        # 4. Integrar candidatos modelo no presentes aún en cartera hasta completar el presupuesto de Renta Variable
        equity_budget_remaining = max(0.0, (100.0 - cash_pct) - assigned_equity_pct)

        for ticker, sector, base_weight, conv, rationale in model_candidates:
            if ticker not in processed_tickers and equity_budget_remaining > 2.0:
                alloc_pct = min(base_weight, equity_budget_remaining, MAX_POSITION_SIZE_PCT)
                alloc_pct = round(alloc_pct, 1)
                if alloc_pct <= 0:
                    continue

                equity_budget_remaining -= alloc_pct
                target_usd = round(capital_total * (alloc_pct / 100.0), 2)
                snap = market_snapshots.get(ticker)
                price = snap.precio_actual if snap else 100.0
                shares = round(target_usd / price, 2) if price > 0 else 0.0
                stop_loss = round(price * 0.92, 2)  # -8% Stop loss
                target_price = round(price * 1.25, 2)  # +25% Target

                proposal = AllocationProposal(
                    ticker=ticker,
                    sector=sector,
                    accion=RebalanceAction.COMPRAR,
                    peso_actual_pct=0.0,
                    peso_objetivo_pct=alloc_pct,
                    capital_asignado_usd=target_usd,
                    precio_estimado=price,
                    acciones_estimadas=shares,
                    stop_loss_sugerido=stop_loss,
                    target_sugerido=target_price,
                    conviccion=conv,
                    motivo=rationale,
                )
                proposals.append(proposal)
                processed_tickers.add(ticker)

        # Ajustar el peso cash efectivo final
        total_equity_pct = sum(p.peso_objetivo_pct for p in proposals)
        effective_cash_pct = round(100.0 - total_equity_pct, 1)
        effective_cash_usd = round(capital_total * (effective_cash_pct / 100.0), 2)

        return MonthlyRebalanceReport(
            mes_ano=mes_ano_str,
            fecha=fecha_str,
            propuestas=proposals,
            peso_cash_pct=effective_cash_pct,
            cash_usd=effective_cash_usd,
            capital_total_usd=round(capital_total, 2),
            regimen_macro="Fase de Expansión Tardía. Curva de tipos normalizándose y política monetaria vigilante.",
            geopolitica_resumen="Seguimiento de semiconductores en Asia oriental y rutas de comercio marítimo.",
            sentimiento_resumen="Sentimiento constructivo con rotación progresiva hacia empresas con ventajas de foso comprobables.",
        )

