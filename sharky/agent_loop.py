"""
Bucle de ejecución y ciclos cognitivos de Sharky.
Orquesta la inteligencia diaria (macro, noticias, inercias) y el rebalanceo mensual (Día 1).
"""

from typing import Dict, Any, List
from datetime import datetime

from sharky.config import DEFAULT_WATCHLIST
from sharky.vault_manager import VaultManager
from sharky.market_data import MarketDataProvider, CORE_WATCHLIST
from sharky.risk_governor import RiskGovernor
from sharky.claude_client import ClaudeBrainClient
from sharky.rebalance_engine import MonthlyRebalanceEngine
from sharky.models import HealthStatus, VitalState, MarketSnapshot


class SharkyAgent:
    def __init__(self):
        self.vault = VaultManager()
        self.market = MarketDataProvider()
        self.risk = RiskGovernor()
        self.claude = ClaudeBrainClient()
        self.rebalancer = MonthlyRebalanceEngine()

    def run_daily_cycle(self, watchlist: List[str] = CORE_WATCHLIST) -> Dict[str, Any]:
        """
        Ejecuta el ciclo diario de Sharky:
        - Obtiene precios de mercado y variables macroeconómicas.
        - Monitorea tesis activas para asegurar que ninguna viole su Stop Loss de emergencia.
        - Si hoy es Día 1 de mes, genera automáticamente el informe de Rebalanceo Mensual.
        - Redacta el diario de reflexión macro e inteligencia en Obsidian.
        - Actualiza el cuadro de mandos Estado_Vital.md.
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        # 1. Leer estado vital actual
        current_health = self.vault.read_health_status()

        # 2. Obtener datos de mercado y macro
        snapshots = self.market.get_batch_snapshots(watchlist)
        macro_snapshots = self.market.get_macro_overview()

        # 3. Evaluar tesis activas (Supervisión de Stop-Loss intrames)
        theses = self.vault.list_active_theses()
        total_pnl_usd = 0.0
        evaluation_notes = []
        stop_loss_warnings = []

        for path, thesis in theses:
            snap = snapshots.get(thesis.ticker)
            if not snap:
                snap = self.market.get_snapshot(thesis.ticker)

            cantidad = thesis.capital_asignado / thesis.precio_entrada if thesis.precio_entrada > 0 else 0
            pnl_tesis = (snap.precio_actual - thesis.precio_entrada) * cantidad
            total_pnl_usd += pnl_tesis

            # Verificar si se activó el Stop Loss de emergencia
            if snap.precio_actual <= thesis.stop_loss and thesis.stop_loss > 0:
                stop_loss_warnings.append(
                    f"⚠️ **ALERTA CRÍTICA STOP LOSS:** {thesis.ticker} cayó a ${snap.precio_actual:,.2f} (Stop: ${thesis.stop_loss:,.2f}). Salida de emergencia requerida."
                )

            evaluation_notes.append(
                f"- **{thesis.ticker}:** Entrada: ${thesis.precio_entrada:,.2f} | Actual: ${snap.precio_actual:,.2f} | PnL: {pnl_tesis:+,.2f} USD"
            )

        # 4. Calcular nueva salud y energía metabólica
        new_health = self.risk.calculate_health(current_health, total_pnl_usd)

        # 5. Si hoy es el Día 1 del mes, generar el Rebalanceo Mensual
        monthly_report_path = None
        if now.day == 1:
            report = self.rebalancer.generate_monthly_plan(new_health, theses, snapshots)
            monthly_report_path = self.vault.write_monthly_rebalance_report(report)

        # 6. Generar reflexión diaria de inteligencia con Claude
        intelligence_text = self.claude.generate_daily_intelligence(
            health=new_health,
            market_snapshots=snapshots,
            macro_snapshots=macro_snapshots,
            active_theses_count=len(theses),
        )

        # 7. Actualizar Obsidian
        extra_summary = "\n\n### 🎯 Rendimiento de Tesis en Cartera\n" + "\n".join(evaluation_notes)
        if stop_loss_warnings:
            extra_summary += "\n\n" + "\n".join(stop_loss_warnings)

        self.vault.update_health_status(new_health, extra_summary=extra_summary)
        journal_path = self.vault.write_daily_journal(
            date_str=date_str,
            summary=intelligence_text,
            health=new_health,
            events=f"Vigilancia diaria completada. {len(theses)} posición(es) en cartera.",
        )

        return {
            "fecha": date_str,
            "estado_vital": new_health.estado_vital.value,
            "salud": new_health.salud_porcentaje,
            "energia": new_health.energia_actual,
            "capital_actual": new_health.capital_actual,
            "pnl_total_usd": new_health.pnl_total_usd,
            "diario_guardado": str(journal_path),
            "rebalanceo_generado": str(monthly_report_path) if monthly_report_path else None,
            "tesis_activas": len(theses),
            "alertas_stop_loss": stop_loss_warnings,
        }

    def generate_monthly_rebalance(self) -> Dict[str, Any]:
        """Fuerza la generación de la propuesta de rebalanceo mensual de cartera (Día 1)."""
        current_health = self.vault.read_health_status()
        theses = self.vault.list_active_theses()
        snapshots = self.market.get_batch_snapshots(CORE_WATCHLIST)

        report = self.rebalancer.generate_monthly_plan(current_health, theses, snapshots)
        report_path = self.vault.write_monthly_rebalance_report(report)

        return {
            "mes_ano": report.mes_ano,
            "archivo_informe": str(report_path),
            "capital_total": report.capital_total_usd,
            "reserva_cash_pct": report.peso_cash_pct,
            "reserva_cash_usd": report.cash_usd,
            "num_propuestas": len(report.propuestas),
            "propuestas": [p.dict() for p in report.propuestas],
        }

    def get_status_summary(self) -> HealthStatus:
        """Devuelve el estado vital actual del agente."""
        return self.vault.read_health_status()
