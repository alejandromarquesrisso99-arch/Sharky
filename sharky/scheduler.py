"""
Planificador 24/7 de Sharky.

Cadencia:
  * Cada N minutos: vigilancia ligera (cotizaciones, stop-loss, radar).
  * Al cierre de mercado (22:00 hora local): control diario completo y, si el
    mes todavía no tiene estudio mensual, el estudio (que incluye el
    rebalanceo del Día 1).
  * Un día a la semana (domingo por defecto, `NEWS_SCAN_WEEKDAY`): escaneo de
    noticias de los activos en cartera.

La versión anterior programaba además una tarea de rebalanceo a las 08:00 que
comprobaba `day == 1` además del ciclo diario, y el día 1 se escribían
**dos** informes. Aquí el rebalanceo tiene un único responsable:
`SharkyAgent.run_monthly_study`.

Este servicio es para quien deja un equipo permanentemente encendido (NAS,
servidor, Docker). Quien lanza Sharky sólo al encender el ordenador (el caso
normal, ver `cmd_startup` en `cli.py`) recibe la misma cadencia semanal de
noticias y mensual de estudio por otra vía:
`SharkyAgent.noticias_semanales_pendiente` y `estudio_mensual_pendiente`.
"""

import time
from datetime import datetime

import schedule

from sharky import level_watch
from sharky.agent_loop import SharkyAgent
from sharky.config import NEWS_SCAN_WEEKDAY
from sharky.opportunity_detector import UNIVERSO_CONVICCION

HORA_CIERRE_DIARIO = "22:00"
HORA_NOTICIAS_SEMANALES = "20:00"

# `schedule.every()` expone un atributo por día (`.monday`, `.tuesday`...);
# `NEWS_SCAN_WEEKDAY` sigue la convención de `date.weekday()` (0=lunes).
_DIAS_SCHEDULE = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class SharkyScheduler:
    def __init__(
        self,
        check_interval_minutes: int = 60,
        hora_cierre: str = HORA_CIERRE_DIARIO,
        hora_noticias: str = HORA_NOTICIAS_SEMANALES,
        dia_noticias: int = NEWS_SCAN_WEEKDAY,
    ):
        self.agent = SharkyAgent()
        self.check_interval_minutes = max(1, check_interval_minutes)
        self.hora_cierre = hora_cierre
        self.hora_noticias = hora_noticias
        self.dia_noticias = dia_noticias % 7

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
            niveles = self.agent.revisar_niveles(tesis, valuation)

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

            for alerta in niveles:
                print(f"[{self._sello()}] {level_watch.texto(alerta)}")
            level_watch.guardar(niveles)

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
        """Cierre diario completo y, si toca, el estudio mensual."""
        print(f"\n[{self._sello()}] 📓 Cierre diario de mercado...")
        try:
            res = self.agent.run_daily_cycle()
            print(f"[{self._sello()}] ✅ Diario: {res['diario_guardado']}")
            print(
                f"[{self._sello()}] 🫀 {res['estado_vital']} | NAV {res['nav_eur']:,.2f} € | "
                f"salud {res['salud']:.1f}% | energía {res['energia']:.1f}"
            )
            for aviso in res.get("avisos_niveles", []):
                print(f"[{self._sello()}] {aviso}")
        except FileNotFoundError as exc:
            print(f"[{self._sello()}] ❌ {exc}")
        except Exception as exc:
            print(f"[{self._sello()}] ❌ Error en el ciclo diario: {exc}")

        if self.agent.estudio_mensual_pendiente():
            self.run_monthly_study()

    def run_monthly_study(self) -> None:
        """Estudio mensual: plan de rebalanceo + reevaluación con Claude."""
        print(f"\n[{self._sello()}] 🧠 Estudio mensual...")
        try:
            res = self.agent.run_monthly_study()
            etiqueta = "SIN Claude" if res["estudio_simulado"] else res["modelo"]
            print(f"[{self._sello()}] ✅ Estudio ({etiqueta}): {res['estudio_guardado']}")
            print(f"[{self._sello()}] 📅 Rebalanceo del Día 1: {res['archivo_informe']}")
        except FileNotFoundError as exc:
            print(f"[{self._sello()}] ❌ {exc}")
        except Exception as exc:
            print(f"[{self._sello()}] ❌ Error en el estudio mensual: {exc}")

    def run_weekly_news(self) -> None:
        """Escaneo semanal de noticias de los activos en cartera."""
        print(f"\n[{self._sello()}] 📰 Escaneo semanal de noticias...")
        try:
            res = self.agent.run_weekly_news_scan()
            if not res["disponible"]:
                print(f"[{self._sello()}] ⚠️  Escaneo no disponible: {res['error']}")
                return
            print(f"[{self._sello()}] ✅ Noticias: {res['nota_guardada']}")
        except FileNotFoundError as exc:
            print(f"[{self._sello()}] ❌ {exc}")
        except Exception as exc:
            print(f"[{self._sello()}] ❌ Error en el escaneo de noticias: {exc}")

    # ------------------------------------------------------------------
    def start(self) -> None:
        dia_legible = _DIAS_SCHEDULE[self.dia_noticias].capitalize()
        print(
            f"[Sharky 24/7] 🚀 Servicio iniciado.\n"
            f"  * Vigilancia cada {self.check_interval_minutes} min.\n"
            f"  * Cierre diario a las {self.hora_cierre} (hora local del sistema).\n"
            f"  * Estudio mensual (con el rebalanceo) en el primer cierre de cada mes.\n"
            f"  * Noticias semanales los {dia_legible} a las {self.hora_noticias}."
        )

        schedule.every(self.check_interval_minutes).minutes.do(self.run_surveillance)
        schedule.every().day.at(self.hora_cierre).do(self.run_daily_close)
        getattr(schedule.every(), _DIAS_SCHEDULE[self.dia_noticias]).at(self.hora_noticias).do(
            self.run_weekly_news
        )

        self.run_surveillance()

        try:
            while True:
                schedule.run_pending()
                time.sleep(10)
        except KeyboardInterrupt:
            print("\n[Sharky 24/7] 🛑 Servicio detenido de forma segura.")
