"""
Bucle de ejecución y ciclos cognitivos de Sharky.

Orden de dependencias de cada ciclo: libro de posiciones -> valoración a mercado
-> estado vital -> auditoría de riesgo -> inteligencia. Nunca al revés: el
diagnóstico se apoya en cifras ya verificadas, no en supuestos.

Tres niveles de razonamiento, cada uno alimentado por la conclusión del
anterior (ver `claude_client.py`):

  * `run_daily_cycle`       -> control de posiciones y normas.
  * `run_weekly_news_scan`  -> noticias + contexto de los últimos 7 días.
  * `run_monthly_study`     -> estudio completo + reevaluación de posiciones.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime, date

from sharky.claude_client import ClaudeBrainClient
from sharky.config import DIAS_CONTEXTO_MENSUAL, DIAS_CONTEXTO_SEMANAL, NEWS_SCAN_WEEKDAY
from sharky.firm_committee import InvestmentCommittee
from sharky.fx import FxProvider
from sharky import level_watch
from sharky.market_data import CORE_WATCHLIST, MarketDataProvider
from sharky.models import (
    HealthStatus,
    LevelAlert,
    LevelKind,
    OpportunityAlert,
    PortfolioValuation,
    RiskBreach,
)
from sharky.news_scanner import NewsScanner
from sharky.opportunity_detector import OpportunityDetector
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.rebalance_engine import MonthlyRebalanceEngine
from sharky.risk_governor import RiskGovernor
from sharky.vault_manager import VaultManager


class SharkyAgent:
    def __init__(self):
        self.vault = VaultManager()
        # Sin precios de referencia: el NAV, el drawdown y el estado vital
        # reales no se calculan con cotizaciones inventadas cuando el mercado
        # falla (ver DATOS-1). `level_watch` ya descartaba estos casos como
        # NO_VERIFICABLE; ahora la valoración hace lo mismo.
        self.market = MarketDataProvider(allow_reference_prices=False)
        self.fx = FxProvider()
        self.store = PortfolioStore()
        self.valuator = PortfolioValuator(market=self.market, fx=self.fx)
        self.risk = RiskGovernor()
        self.claude = ClaudeBrainClient()
        self.news = NewsScanner()
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
    def run_daily_cycle(self, watchlist: Optional[List[str]] = None) -> Dict[str, Any]:
        """Vigilancia diaria: valoración, stop-loss, radar y control del día.

        Claude sólo razona sobre las posiciones, sus precios, su valor de
        mercado y el cumplimiento de las normas. El rebalanceo del Día 1 ya
        no sale de aquí: es parte de `run_monthly_study`.
        """
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
        # Determinista, no consume la API de Claude.
        universo = list(dict.fromkeys(watchlist + [t.ticker for _, t in tesis if t.ticker]))
        snapshots = self.market.get_batch_snapshots(universo, with_fundamentals=True)

        # Niveles de las tesis: stop-loss (salida obligatoria del mandato) y
        # take-profit (aviso, no orden). Ver `sharky.level_watch`.
        niveles = self.revisar_niveles(tesis, valuation)

        # Radar de oportunidades, sin reemitir lo que ya está vivo.
        nuevas_alertas = self.detector.scan_for_opportunities(
            snapshots,
            existing_positions=tickers_cartera,
            ya_alertado=self.vault.has_active_alert,
        )
        for alerta in nuevas_alertas:
            self.vault.write_opportunity_alert(alerta)

        # Persistencia de estado vital y niveles ANTES de invocar a Claude: si
        # la API falla (con `ALLOW_SIMULATED_INTELLIGENCE=false` propaga la
        # excepción), un stop cruzado ya ha quedado escrito en Estado_Vital.md
        # y en logs/ para el aviso emergente de Windows, en vez de perderse
        # porque falló la prosa (ver CICLO-3). `ciclo_diario=True` es lo único
        # que marca "el ciclo de hoy ya se ejecutó" (ver CICLO-2).
        self.vault.update_health_status(
            health,
            valuation=valuation,
            incumplimientos=incumplimientos,
            alertas_niveles=niveles,
            ciclo_diario=True,
        )
        level_watch.guardar(niveles)

        # Control del día: sólo posiciones y normas. Macro, noticias y
        # memoria quedan para los niveles semanal y mensual.
        variaciones = self._variaciones_desde_ultimo_control(valuation, fecha_str)
        a_vigilar = self._posiciones_a_vigilar(variaciones, niveles, tickers_cartera)
        inteligencia = self.claude.generate_daily_intelligence(
            health=health,
            valuation=valuation,
            incumplimientos=incumplimientos,
            avisos_niveles=[level_watch.texto(a) for a in niveles],
            variaciones=variaciones,
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
            conclusion=inteligencia.conclusion,
            posiciones_a_vigilar=a_vigilar,
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
            "alertas_niveles": [a.model_dump(mode="json") for a in niveles],
            "avisos_niveles": [level_watch.texto(a) for a in niveles],
            "stops_alcanzados": sum(1 for a in niveles if a.tipo is LevelKind.STOP_LOSS),
            "targets_alcanzados": sum(1 for a in niveles if a.tipo is LevelKind.TAKE_PROFIT),
            "diario_guardado": str(ruta_diario),
            "posiciones_a_vigilar": a_vigilar,
            "inteligencia_simulada": inteligencia.simulado,
            "advertencias": valuation.advertencias,
        }

    def _variaciones_desde_ultimo_control(
        self, valuation: PortfolioValuation, fecha_hoy: str
    ) -> Dict[str, float]:
        """% de cambio del precio de cada posición desde el último control.

        Compara con `precios_eur` del diario anterior más reciente (no
        necesariamente ayer: el ordenador puede pasar días apagado). Sólo
        posiciones con precio fiable hoy y precio registrado entonces.
        """
        anteriores = [
            m for m in self.vault.leer_memoria_diario(DIAS_CONTEXTO_SEMANAL)
            if str(m.get("fecha", "")) < fecha_hoy and m.get("precios_eur")
        ]
        if not anteriores:
            return {}
        precios_previos = anteriores[-1]["precios_eur"]
        variaciones: Dict[str, float] = {}
        for p in valuation.posiciones:
            previo = precios_previos.get(p.ticker)
            if not p.fuente_precio.es_fiable or not previo:
                continue
            variaciones[p.ticker] = round((p.precio_unitario_eur / float(previo) - 1.0) * 100.0, 2)
        return variaciones

    @staticmethod
    def _posiciones_a_vigilar(
        variaciones: Dict[str, float],
        niveles: List[LevelAlert],
        tickers_cartera: List[str],
    ) -> List[str]:
        """Posiciones que el escaneo semanal debe investigar primero:
        movimientos fuertes y niveles de tesis alcanzados. Los
        incumplimientos de peso no entran: son un problema de tamaño que
        corrige el Día 1, no algo que expliquen las noticias, y marcarían
        las mismas posiciones todos los días."""
        marcadas: Set[str] = set(ClaudeBrainClient.movimientos_fuertes(variaciones))
        marcadas.update(a.ticker for a in niveles if a.es_accionable)
        return sorted(marcadas & set(tickers_cartera))

    def revisar_niveles(self, tesis, valuation: PortfolioValuation) -> List[LevelAlert]:
        """Stop-loss y take-profit de las tesis con posición abierta.

        Delega en `sharky.level_watch`, que hace la comparación en EUR y
        propone el stop dinámico cuando se alcanza un target. Aquí sólo se
        inyectan las dependencias del agente.
        """
        return level_watch.revisar_niveles(tesis, valuation, self.fx)

    def revisar_niveles_ahora(self) -> Dict[str, Any]:
        """Comprueba los niveles sin escribir el diario ni llamar a Claude.

        Es lo que ejecuta `sharky niveles`, y también lo que `startup` usa
        cuando el ciclo del día ya se completó: encender el ordenador por
        segunda vez no debe costar una llamada a la API, pero tampoco puede
        dejar de avisar de un stop cruzado a media tarde. Refresca el fichero
        de avisos para que el emergente de Windows enseñe lo último.
        """
        valuation, _, _ = self.snapshot_estado()
        tesis = self.vault.list_active_theses()
        niveles = self.revisar_niveles(tesis, valuation)
        level_watch.guardar(niveles)
        return {
            "fecha": date.today().isoformat(),
            "resumen": level_watch.resumen(niveles),
            "alertas_niveles": [a.model_dump(mode="json") for a in niveles],
            "avisos_niveles": [level_watch.texto(a) for a in niveles],
            "stops_alcanzados": sum(1 for a in niveles if a.tipo is LevelKind.STOP_LOSS),
            "targets_alcanzados": sum(1 for a in niveles if a.tipo is LevelKind.TAKE_PROFIT),
            "cobertura_datos_pct": valuation.cobertura_mercado_pct,
            "advertencias": valuation.advertencias,
        }

    @staticmethod
    def _dias_desde_ultimo_ciclo(health: HealthStatus) -> float:
        """Días naturales desde el último `run_daily_cycle`, mínimo 0.

        Usa `ultimo_ciclo_diario`, no `ultima_actualizacion`: este último lo
        pisa cualquier escritura de Estado_Vital.md (p.ej. `TradeRecorder` al
        registrar una operación), lo que hacía que registrar una operación por
        la mañana cancelara el ciclo diario de ese día (ver CICLO-2).
        """
        try:
            ultima = health.ultimo_ciclo_diario.date()
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
    # Noticias semanales
    # ------------------------------------------------------------------
    @staticmethod
    def _toca_noticias_semanales(ultima_fecha: Optional[date], hoy: Optional[date] = None) -> bool:
        """Decide si toca lanzar el escaneo semanal de noticias.

        Dispara el día de la semana configurado (`NEWS_SCAN_WEEKDAY`, domingo
        por defecto) sin repetir si ya corrió hoy. Sharky no es un servicio
        permanente -- se lanza al encender el ordenador, ver `cmd_startup` en
        `cli.py` -- así que si esa semana no tocó encenderlo en domingo, esto
        actúa de red de seguridad: en cuanto pasan 7 días desde el último
        escaneo, lo lanza igual, para que nunca quede huérfano
        indefinidamente. Mismo criterio que `BREACH_ESCALATION_DAYS` usa para
        no dejar pasar un incumplimiento sólo porque nadie volvió a mirar.
        """
        hoy = hoy or date.today()
        if ultima_fecha is None:
            return True
        dias = (hoy - ultima_fecha).days
        if dias <= 0:
            return False
        return hoy.weekday() == NEWS_SCAN_WEEKDAY or dias >= 7

    def noticias_semanales_pendiente(self) -> bool:
        """True si toca lanzar el escaneo semanal de noticias hoy."""
        return self._toca_noticias_semanales(self.vault.leer_ultima_fecha_noticias_semanales())

    def run_weekly_news_scan(self) -> Dict[str, Any]:
        """Busca noticias de cada posición con el contexto de la semana.

        El contexto son las conclusiones de los controles diarios de los
        últimos `DIAS_CONTEXTO_SEMANAL` días; las posiciones que marcaron
        "a vigilar" se investigan primero.
        """
        fecha_str = datetime.now().strftime("%Y-%m-%d")
        portfolio = self.store.load()
        memoria = self.vault.leer_memoria_diario(DIAS_CONTEXTO_SEMANAL)
        prioritarios = sorted({
            str(t) for m in memoria for t in (m.get("posiciones_a_vigilar") or [])
        })
        resultado = self.news.scan(
            portfolio.posiciones,
            contexto_semana=ClaudeBrainClient._formatear_memoria(memoria),
            prioritarios=prioritarios,
        )
        ruta = self.vault.write_weekly_news_report(fecha_str, resultado, portfolio.posiciones)

        return {
            "fecha": fecha_str,
            "disponible": resultado.disponible,
            "modelo": resultado.modelo,
            "busquedas_realizadas": resultado.busquedas_realizadas,
            "num_fuentes": len(resultado.fuentes),
            "error": resultado.error,
            "nota_guardada": str(ruta),
            "activos_analizados": [p.ticker for p in portfolio.posiciones],
            "prioritarios": prioritarios,
            "dias_de_contexto": len(memoria),
        }

    # ------------------------------------------------------------------
    # Comité de inversión
    # ------------------------------------------------------------------
    def run_investment_committee(self) -> Dict[str, Any]:
        valuation, health, incumplimientos = self.snapshot_estado()
        tesis = self.vault.list_active_theses()
        snapshots = self.market.get_batch_snapshots(list(CORE_WATCHLIST), with_fundamentals=True)
        macro = self.market.get_macro_overview()
        noticias_recientes = self.vault.leer_ultimas_noticias_semanales()

        return self.committee.convene_session(
            health=health,
            market_snapshots=snapshots,
            macro_snapshots=macro,
            valuation=valuation,
            incumplimientos=incumplimientos,
            theses_count=len(tesis),
            noticias_recientes=noticias_recientes,
        )

    # ------------------------------------------------------------------
    # Estudio mensual (incluye el rebalanceo del Día 1)
    # ------------------------------------------------------------------
    @staticmethod
    def _mes_actual(hoy: Optional[date] = None) -> str:
        return (hoy or date.today()).strftime("%Y-%m")

    def estudio_mensual_pendiente(self) -> bool:
        """True si este mes todavía no tiene estudio mensual.

        No exige que sea día 1: Sharky sólo corre al encender el ordenador,
        así que el primer arranque del mes lo lanza, sea el día que sea.

        Un estudio que salió sin Claude (la API falló) no cuenta como hecho
        si ahora hay API: se reintenta, como mucho una vez al día, para que
        un fallo puntual no deje el mes entero sin reevaluación.
        """
        mes = self._mes_actual()
        if not self.vault.existe_estudio_mensual(mes):
            return True
        meta = self.vault.leer_meta_estudio_mensual(mes)
        return (
            bool(getattr(self.claude, "is_live", False))
            and bool(meta.get("inteligencia_simulada"))
            and str(meta.get("fecha", "")) < date.today().isoformat()
        )

    def run_monthly_study(self) -> Dict[str, Any]:
        """Estudio completo de la cartera y reevaluación de posiciones.

        1. El motor de rebalanceo genera el plan determinista (respeta los
           límites del mandato) y lo deja en la bóveda.
        2. Claude lo contrasta con el contexto acumulado del mes: controles
           diarios, escaneos semanales y la conclusión del estudio anterior.
        """
        mes = self._mes_actual()
        fecha_str = date.today().isoformat()
        informe, ruta_rebalanceo, valuation, health, incumplimientos, tesis, macro = self._plan_mensual()

        resultado = self.claude.generate_monthly_study(
            mes=mes,
            health=health,
            valuation=valuation,
            incumplimientos=incumplimientos,
            tesis=[t for _, t in tesis],
            plan=informe,
            macro_snapshots=macro,
            memoria_mes=self.vault.leer_memoria_diario(DIAS_CONTEXTO_MENSUAL),
            noticias_mes=self.vault.leer_noticias_semanales(DIAS_CONTEXTO_MENSUAL),
            conclusion_mes_anterior=self.vault.leer_conclusion_estudio_anterior(mes),
        )
        ruta_estudio = self.vault.write_monthly_study(
            mes, fecha_str, resultado, health, ruta_rebalanceo
        )

        res = self._resumen_rebalanceo(informe, ruta_rebalanceo)
        res.update({
            "mes": mes,
            "estudio_guardado": str(ruta_estudio),
            "estudio_simulado": resultado.simulado,
            "estudio_error": resultado.error,
            "modelo": resultado.modelo,
        })
        return res

    def _plan_mensual(self):
        """Plan determinista del motor de rebalanceo, ya escrito en la bóveda."""
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
        return informe, ruta, valuation, health, incumplimientos, tesis, macro

    def generate_monthly_rebalance(self) -> Dict[str, Any]:
        """Sólo el plan determinista, sin estudio de Claude."""
        informe, ruta, *_ = self._plan_mensual()
        return self._resumen_rebalanceo(informe, ruta)

    @staticmethod
    def _resumen_rebalanceo(informe, ruta) -> Dict[str, Any]:
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
