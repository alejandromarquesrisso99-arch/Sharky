"""
Planificador 24/7 de Sharky.

Cadencia:
  * Cada N minutos: vigilancia ligera (cotizaciones, stop-loss, radar).
  * Al cierre de mercado (22:00 hora local): ciclo diario completo. Si es día 1,
    el propio ciclo emite el rebalanceo mensual.

La versión anterior programaba además una tarea de rebalanceo a las 08:00 que
comprobaba `day == 1`; como `run_daily_cycle` ya lo genera, el día 1 se
escribían **dos** informes. Aquí el rebalanceo tiene un único responsable.
"""

import time
from datetime import datetime

import schedule

from sharky.agent_loop import SharkyAgent
from sharky.opportunity_detector import UNIVERSO_CONVICCION

HORA_CIERRE_DIARIO = "22:00"


class SharkyScheduler:
    def __init__(self, check_interval_minutes: int = 60, hora_cierre: str = HORA_CIERRE_DIARIO):
        self.agent = SharkyAgent()
        self.check_interval_minutes = max(1, check_interval_minutes)
        self.hora_cierre = hora_cierre

    @staticmethod
    def _sello() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------
    def run_surveillance(self) -> None:
        """Vigilancia ligera: no escribe el diario ni consume la API de Claude."""
        print(f"[{self._sello()}] 🛰️  Escaneo de vigilancia...")
        try:
            valuation, health, incumplimientos = self.agent.snapshot_estado()
            tesis = self.agent.vault.list_active_theses()
            avisos = self.agent._revisar_stop_loss(tesis, valuation)

            tickers = [p.ticker for p in valuation.posiciones]
            snapshots = self.agent.market.get_batch_snapshots(
                tickers + list(UNIVERSO_CONVICCION)
            )
            nuevas = self.agent.detector.scan_for_opportunities(
                snapshots,
                existing_positions=tickers,
                ya_alertado=self.agent.vault.has_active_alert,
            )
            for alerta in nuevas:
                self.agent.vault.write_opportunity_alert(alerta)
                print(f"[{self._sello()}] ⭐ Nueva alerta: {alerta.ticker} (R:R {alerta.ratio_rr:.2f}:1)")

            for aviso in avisos:
                print(f"[{self._sello()}] {aviso}")

            print(
                f"[{self._sello()}] ✅ NAV {valuation.nav_eur:,.2f} € | "
                f"{health.estado_vital.value} | drawdown {health.drawdown_actual_pct:.2f}% | "
                f"{len(incumplimientos)} incumplimiento(s) | {len(nuevas)} alerta(s) nueva(s)"
            )
        except FileNotFoundError as exc:
            print(f"[{self._sello()}] ❌ {exc}")
        except Exception as exc:
            print(f"[{self._sello()}] ❌ Error en la vigilancia: {exc}")

    def run_daily_close(self) -> None:
        """Cierre diario completo. El día 1 emite también el rebalanceo."""
        print(f"\n[{self._sello()}] 📓 Cierre diario de mercado...")
        try:
            res = self.agent.run_daily_cycle()
            print(f"[{self._sello()}] ✅ Diario: {res['diario_guardado']}")
            print(
                f"[{self._sello()}] 🫀 {res['estado_vital']} | NAV {res['nav_eur']:,.2f} € | "
                f"salud {res['salud']:.1f}% | energía {res['energia']:.1f}"
            )
            if res.get("rebalanceo_generado"):
                print(f"[{self._sello()}] 📅 Rebalanceo del Día 1: {res['rebalanceo_generado']}")
            for aviso in res.get("alertas_stop_loss", []):
                print(f"[{self._sello()}] {aviso}")
        except FileNotFoundError as exc:
            print(f"[{self._sello()}] ❌ {exc}")
        except Exception as exc:
            print(f"[{self._sello()}] ❌ Error en el ciclo diario: {exc}")

    # ------------------------------------------------------------------
    def start(self) -> None:
        print(
            f"[Sharky 24/7] 🚀 Servicio iniciado.\n"
            f"  * Vigilancia cada {self.check_interval_minutes} min.\n"
            f"  * Cierre diario a las {self.hora_cierre} (hora local del sistema).\n"
            f"  * El rebalanceo mensual lo emite el cierre del día 1."
        )

        schedule.every(self.check_interval_minutes).minutes.do(self.run_surveillance)
        schedule.every().day.at(self.hora_cierre).do(self.run_daily_close)

        self.run_surveillance()

        try:
            while True:
                schedule.run_pending()
                time.sleep(10)
        except KeyboardInterrupt:
            print("\n[Sharky 24/7] 🛑 Servicio detenido de forma segura.")
