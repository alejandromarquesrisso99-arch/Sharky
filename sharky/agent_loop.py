"""
Bucle de ejecución y ciclos cognitivos del agente Sharky.
Orquesta la lectura de la bóveda de Obsidian, el análisis de mercado,
la validación de riesgo y la actualización del estado vital.
"""

from typing import Dict, Any, List
from datetime import datetime

from sharky.config import DEFAULT_WATCHLIST
from sharky.vault_manager import VaultManager
from sharky.market_data import MarketDataProvider
from sharky.risk_governor import RiskGovernor
from sharky.claude_client import ClaudeBrainClient
from sharky.models import HealthStatus, VitalState, MarketSnapshot


class SharkyAgent:
    def __init__(self):
        self.vault = VaultManager()
        self.market = MarketDataProvider()
        self.risk = RiskGovernor()
        self.claude = ClaudeBrainClient()

    def run_daily_cycle(self, watchlist: List[str] = DEFAULT_WATCHLIST) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo diario de Sharky:
        1. Lee el estado actual de la bóveda de Obsidian.
        2. Obtiene cotizaciones actualizadas de los activos.
        3. Evalúa las tesis activas (cálculo de PnL no realizado).
        4. Calcula la nueva salud y energía mediante el RiskGovernor.
        5. Pide a Claude la reflexión del día.
        6. Guarda el diario y actualiza Estado_Vital.md en Obsidian.
        """
        # 1. Leer estado actual
        current_health = self.vault.read_health_status()

        # 2. Datos de mercado
        snapshots = self.market.get_batch_snapshots(watchlist)

        # 3. Evaluar tesis activas
        theses = self.vault.list_active_theses()
        total_pnl_usd = 0.0
        evaluation_notes = []

        for path, thesis in theses:
            snap = snapshots.get(thesis.ticker)
            if not snap:
                snap = self.market.get_snapshot(thesis.ticker)
            
            # Calcular PnL de la tesis
            cantidad = thesis.capital_asignado / thesis.precio_entrada if thesis.precio_entrada > 0 else 0
            pnl_tesis = (snap.precio_actual - thesis.precio_entrada) * cantidad
            total_pnl_usd += pnl_tesis
            evaluation_notes.append(
                f"- **{thesis.ticker}:** Entrada: ${thesis.precio_entrada:,.2f} | Actual: ${snap.precio_actual:,.2f} | PnL: {pnl_tesis:+,.2f} USD"
            )

        # 4. Calcular nueva salud y supervivencia
        new_health = self.risk.calculate_health(current_health, total_pnl_usd)

        # 5. Generar reflexión (Claude o Simulación)
        date_str = datetime.now().strftime("%Y-%m-%d")
        reflection_text = self.claude.generate_daily_reflection(
            health=new_health,
            market_snapshots=snapshots,
            active_theses_count=len(theses),
        )

        # 6. Escribir en Obsidian
        summary_extra = "\n\n### 🎯 Rendimiento de Tesis Activas\n" + "\n".join(evaluation_notes)
        self.vault.update_health_status(new_health, extra_summary=summary_extra)
        journal_path = self.vault.write_daily_journal(
            date_str=date_str,
            summary=reflection_text,
            health=new_health,
            events=f"Ciclo ejecutado con {len(theses)} tesis activa(s) y {len(watchlist)} tickers monitoreados.",
        )

        return {
            "fecha": date_str,
            "estado_vital": new_health.estado_vital.value,
            "salud": new_health.salud_porcentaje,
            "energia": new_health.energia_actual,
            "capital_actual": new_health.capital_actual,
            "pnl_total_usd": new_health.pnl_total_usd,
            "diario_guardado": str(journal_path),
            "tesis_activas": len(theses),
        }

    def get_status_summary(self) -> HealthStatus:
        """Devuelve el estado vital actual del agente."""
        return self.vault.read_health_status()
