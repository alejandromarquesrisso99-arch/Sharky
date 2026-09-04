"""
Bucle de ejecución y ciclos cognitivos de Sharky.

Orden de dependencias de cada ciclo: libro de posiciones -> valoración a mercado
-> estado vital -> auditoría de riesgo -> inteligencia. Nunca al revés: el
diagnóstico se apoya en cifras ya verificadas, no en supuestos.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date

from sharky.claude_client import ClaudeBrainClient
from sharky.config import DIAS_CONTEXTO_DIARIO, DIAS_CONTEXTO_MENSUAL
from sharky.firm_committee import InvestmentCommittee
from sharky.fx import FxProvider
from sharky.market_data import CORE_WATCHLIST, MarketDataProvider
from sharky.models import (
    HealthStatus,
    OpportunityAlert,
    PortfolioValuation,
    RiskBreach,
)
from sharky.opportunity_detector import OpportunityDetector
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.rebalance_engine import MonthlyRebalanceEngine
from sharky.risk_governor import RiskGovernor
from sharky.vault_manager import VaultManager


class SharkyAgent:
    def __init__(self):
        self.vault = VaultManager()
        self.market = MarketDataProvider()
        self.fx = FxProvider()
        self.store = PortfolioStore()
        self.valuator = PortfolioValuator(market=self.market, fx=self.fx)
        self.risk = RiskGovernor()
        self.claude = ClaudeBrainClient()
        self.rebalancer = MonthlyRebalanceEngine(market=self.market, governor=self.risk, fx=self.fx)
        self.detector = OpportunityDetector(market=self.market)
        self.committee = InvestmentCommittee(claude=self.claude)

    # ------------------------------------------------------------------
    # Fotografía del estado actual
    # ------------------------------------------------------------------
    def snapshot_estado(
        self, dias_transcurridos: float = 0.0, actualizar_energia: bool = False
    ) -> Tuple[PortfolioValuation, HealthStatus, List[RiskBreach]]:
        """Valora la cartera y deriva estado vital e incumplimientos.

        No escribe nada en la bóveda: es la base de lectura común de todos los
        comandos.
        """
        portfolio = self.store.load()
        valuation = self.valuator.value(portfolio)
        health = self.risk.calculate_health(
            self.vault.read_health_status(),
            valuation,
            dias_transcurridos=dias_transcurridos,
            actualizar_energia=actualizar_energia,
        )
        incumplimientos = self.risk.audit_portfolio(valuation, health)
        return valuation, health, incumplimientos

    # ------------------------------------------------------------------
    # Ciclo diario
    # ------------------------------------------------------------------
    def run_daily_cycle(
        self,
        watchlist: Optional[List[str]] = None,
        generar_rebalanceo_si_dia_1: bool = True,
    ) -> Dict[str, Any]:
        """Vigilancia diaria: valoración, stop-loss, radar y diario."""
        ahora = datetime.now()
        fecha_str = ahora.strftime("%Y-%m-%d")
        watchlist = watchlist or list(CORE_WATCHLIST)

        health_previa = self.vault.read_health_status()
        dias = self._dias_desde_ultimo_ciclo(health_previa)

        portfolio = self.store.load()
        valuation = self.valuator.value(portfolio)
        health = self.risk.calculate_health(
            health_previa, valuation, dias_transcurridos=dias, actualizar_energia=True
        )
        incumplimientos = self.risk.audit_portfolio(valuation, health)

        tesis = self.vault.list_active_theses()
        tickers_cartera = [p.ticker for p in valuation.posiciones]

        # Radar: universo de vigilancia más los activos con tesis abierta.
        universo = list(dict.fromkeys(watchlist + [t.ticker for _, t in tesis if t.ticker]))
        snapshots = self.market.get_batch_snapshots(universo, with_fundamentals=True)
        macro = self.market.get_macro_overview()

        # Stop-loss: única excepción operativa intrames del mandato.
        avisos_stop = self._revisar_stop_loss(tesis, valuation)

        # Radar de oportunidades, sin reemitir lo que ya está vivo.
        nuevas_alertas = self.detector.scan_for_opportunities(
            snapshots,
            existing_positions=tickers_cartera,
            ya_alertado=self.vault.has_active_alert,
        )
        for alerta in nuevas_alertas:
            self.vault.write_opportunity_alert(alerta)

        # Inteligencia del día. El día 1 arrastra el mes completo de diario
        # (cierra el ciclo mensual y da el tono del siguiente); el resto de
        # días, sólo la semana reciente -- ver DIAS_CONTEXTO_* en config.py.
        dias_memoria = DIAS_CONTEXTO_MENSUAL if ahora.day == 1 else DIAS_CONTEXTO_DIARIO
        memoria_reciente = self.vault.leer_memoria_diario(dias_memoria)
        inteligencia = self.claude.generate_daily_intelligence(
            health=health,
            market_snapshots=snapshots,
            macro_snapshots=macro,
            valuation=valuation,
            incumplimientos=incumplimientos,
            active_theses_count=len(tesis),
            memoria_reciente=memoria_reciente,
        )

        # Rebalanceo del Día 1. Sólo aquí, para no duplicarlo con el scheduler.
        ruta_rebalanceo = None
        if generar_rebalanceo_si_dia_1 and ahora.day == 1:
            informe = self.rebalancer.generate_monthly_plan(
                health=health,
                valuation=valuation,
                active_theses=tesis,
                alerts=[a for _, a in self.vault.list_active_alerts()],
                macro_snapshots=macro,
                incumplimientos=incumplimientos,
            )
            ruta_rebalanceo = self.vault.write_monthly_rebalance_report(informe)

        # Persistencia.
        resumen_extra = ""
        if avisos_stop:
            resumen_extra = "## 🛑 Alertas de Stop-Loss\n\n" + "\n".join(f"* {a}" for a in avisos_stop)

        self.vault.update_health_status(
            health,
            valuation=valuation,
            incumplimientos=incumplimientos,
            extra_summary=resumen_extra,
        )
        ruta_diario = self.vault.write_daily_journal(
            date_str=fecha_str,
            summary=inteligencia.texto,
            health=health,
            valuation=valuation,
            events=(
                f"Vigilancia diaria completada. {len(valuation.posiciones)} posición(es), "
                f"{len(tesis)} tesis activa(s), {len(nuevas_alertas)} alerta(s) nueva(s), "
                f"{len(incumplimientos)} incumplimiento(s)."
            ),
            inteligencia_simulada=inteligencia.simulado,
        )

        return {
            "fecha": fecha_str,
            "estado_vital": health.estado_vital.value,
            "salud": health.salud_porcentaje,
            "energia": health.energia_actual,
            "nav_eur": health.nav_actual_eur,
            "pnl_total_eur": health.pnl_total_eur,
            "pnl_total_pct": health.pnl_total_pct,
            "drawdown_actual_pct": health.drawdown_actual_pct,
            "cobertura_datos_pct": health.cobertura_datos_pct,
            "posiciones": len(valuation.posiciones),
            "tesis_activas": len(tesis),
            "incumplimientos": [b.model_dump() for b in incumplimientos],
            "alertas_nuevas": [a.model_dump() for a in nuevas_alertas],
            "diagnostico_radar": list(self.detector.ultimo_diagnostico),
            "alertas_stop_loss": avisos_stop,
            "diario_guardado": str(ruta_diario),
            "rebalanceo_generado": str(ruta_rebalanceo) if ruta_rebalanceo else None,
            "inteligencia_simulada": inteligencia.simulado,
            "advertencias": valuation.advertencias,
        }

    def _revisar_stop_loss(self, tesis, valuation: PortfolioValuation) -> List[str]:
        """Comprueba si alguna posición ha cruzado el stop de su tesis.

        La comparación se hace **en EUR**. Una tesis declara su stop en la divisa
        que indique su frontmatter (`divisa`), que no tiene por qué ser la de
        cotización: el stop de MSFT vino del extracto en euros mientras la acción
        cotiza en dólares. Comparar ambos números sin convertirlos es el mismo
        error de unidades que fabricaba el PnL de la versión anterior.
        """
        avisos: List[str] = []
        por_ticker = {p.ticker.upper(): p for p in valuation.posiciones}

        for _, t in tesis:
            if not t.ticker or t.stop_loss <= 0:
                continue  # Tesis en radar: no hay stop que vigilar todavía.
            pos = por_ticker.get(t.ticker.upper())
            if pos is None:
                continue  # Tesis sin posición abierta.

            enlace = self.vault.enlace(t.ticker, pos.nota_activo)

            if not pos.fuente_precio.es_fiable:
                avisos.append(
                    f"⚠️ **{enlace}**: no se puede verificar el stop-loss porque no hay "
                    f"cotización fiable."
                )
                continue

            try:
                stop_eur = t.stop_loss * self.fx.get_rate(t.divisa).tasa
            except ValueError as exc:
                avisos.append(f"⚠️ **{enlace}**: stop-loss no verificable ({exc}).")
                continue

            if pos.precio_unitario_eur <= stop_eur:
                avisos.append(
                    f"🛑 **STOP-LOSS ALCANZADO en {enlace}**: cotiza a "
                    f"{pos.precio_unitario_eur:,.2f} € por título "
                    f"({pos.precio_cotizacion:,.2f} {pos.divisa_cotizacion}) frente a un stop de "
                    f"{t.stop_loss:,.2f} {t.divisa} ({stop_eur:,.2f} €). El mandato exige "
                    f"liquidar de inmediato: {pos.valor_mercado_eur:,.2f} € en riesgo."
                )
        return avisos

    @staticmethod
    def _dias_desde_ultimo_ciclo(health: HealthStatus) -> float:
        """Días naturales desde la última actualización, mínimo 0."""
        try:
            ultima = health.ultima_actualizacion.date()
        except AttributeError:
            return 1.0
        return max(0.0, (date.today() - ultima).days)

    def ya_completo_ciclo_hoy(self) -> bool:
        """True si `run_daily_cycle` ya se ejecutó hoy con éxito.

        La usa `sharky.cli startup`: el ordenador puede encenderse varias veces
        el mismo día, pero la API de Claude sólo debe invocarse una vez. Una
        bóveda nueva (sin `Estado_Vital.md` todavía) nunca cuenta como "ya
        ejecutado hoy", para no bloquear el primer ciclo.
        """
        if not self.vault.health_path.exists():
            return False
        health = self.vault.read_health_status()
        return self._dias_desde_ultimo_ciclo(health) <= 0

    # ------------------------------------------------------------------
    # Comité de inversión
    # ------------------------------------------------------------------
    def run_investment_committee(self) -> Dict[str, Any]:
        valuation, health, incumplimientos = self.snapshot_estado()
        tesis = self.vault.list_active_theses()
        snapshots = self.market.get_batch_snapshots(list(CORE_WATCHLIST), with_fundamentals=True)
        macro = self.market.get_macro_overview()

        return self.committee.convene_session(
            health=health,
            market_snapshots=snapshots,
            macro_snapshots=macro,
            valuation=valuation,
            incumplimientos=incumplimientos,
            theses_count=len(tesis),
        )

    # ------------------------------------------------------------------
    # Rebalanceo mensual
    # ------------------------------------------------------------------
    def generate_monthly_rebalance(self) -> Dict[str, Any]:
        valuation, health, incumplimientos = self.snapshot_estado()
        tesis = self.vault.list_active_theses()
        macro = self.market.get_macro_overview()

        informe = self.rebalancer.generate_monthly_plan(
            health=health,
            valuation=valuation,
            active_theses=tesis,
            alerts=[a for _, a in self.vault.list_active_alerts()],
            macro_snapshots=macro,
            incumplimientos=incumplimientos,
        )
        ruta = self.vault.write_monthly_rebalance_report(informe)

        return {
            "mes_ano": informe.mes_ano,
            "archivo_informe": str(ruta),
            "nav_total_eur": informe.nav_total_eur,
            "cash_objetivo_pct": informe.peso_cash_objetivo_pct,
            "cash_objetivo_eur": informe.cash_objetivo_eur,
            "cobertura_datos_pct": informe.cobertura_datos_pct,
            "num_propuestas": len(informe.propuestas),
            "propuestas": [p.model_dump() for p in informe.propuestas],
            "incumplimientos": [b.model_dump() for b in informe.incumplimientos],
            "advertencias": informe.advertencias,
        }

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def get_active_alerts(self) -> List[OpportunityAlert]:
        return [alerta for _, alerta in self.vault.list_active_alerts()]

    def get_status_summary(self) -> Tuple[PortfolioValuation, HealthStatus, List[RiskBreach]]:
        return self.snapshot_estado()
