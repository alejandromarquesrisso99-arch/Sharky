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

Fuera de esa cadencia y sólo a demanda, `run_market_exploration` sale a buscar
candidatos nuevos en la web con el modelo más capaz disponible. Es el único
ciclo que puede ampliar el universo vigilado; el resto trabaja sobre lo que ya
está declarado.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime, date

from sharky.claude_client import ClaudeBrainClient
from sharky.config import DIAS_CONTEXTO_MENSUAL, DIAS_CONTEXTO_SEMANAL, NEWS_SCAN_WEEKDAY
from sharky.firm_committee import InvestmentCommittee
from sharky.fx import FxProvider
from sharky import level_watch
from sharky.market_data import CORE_WATCHLIST, MarketDataProvider
from sharky.market_explorer import MarketExplorer
from sharky.models import (
    AlertStatus,
    HealthStatus,
    LevelAlert,
    LevelKind,
    OpportunityAlert,
    PortfolioValuation,
    RiskBreach,
)
from sharky.news_scanner import NewsScanner
from sharky.opportunity_detector import (
    UNIVERSO_CONVICCION,
    OpportunityDetector,
    alertas_caducadas,
)
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.rebalance_engine import MonthlyRebalanceEngine
from sharky import thesis_review
from sharky.thesis_review import ThesisReviewer
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
        self.explorer = MarketExplorer()
        self.reviewer = ThesisReviewer()

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

        # Caducidad de alertas ANTES del escaneo: una alerta que caduca hoy
        # libera su ticker para que el radar pueda volver a emitirla en este
        # mismo ciclo, con niveles medidos hoy en vez de los de hace un mes.
        caducadas = self.caducar_alertas()

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
                f"{len(caducadas)} alerta(s) caducada(s), "
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
            "alertas_caducadas": caducadas,
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

    def caducar_alertas(self) -> List[Dict[str, str]]:
        """Cierra las alertas que ya no describen una oportunidad.

        Determinista y sin API. La política vive en
        `opportunity_detector.alertas_caducadas` (edad, stop roto, objetivo
        ya alcanzado) y la escritura en `VaultManager.marcar_alerta`: misma
        separación que entre el filtro cuantitativo y la bóveda.
        """
        activas = [a for _, a in self.vault.list_active_alerts()]
        if not activas:
            return []

        snapshots = self.market.get_batch_snapshots([a.ticker for a in activas])
        cerradas: List[Dict[str, str]] = []
        hoy = date.today().isoformat()
        for alerta, motivo in alertas_caducadas(activas, snapshots):
            ruta = self.vault.marcar_alerta(alerta, AlertStatus.EXPIRADA, hoy, motivo=motivo)
            cerradas.append({
                "ticker": alerta.ticker,
                "id_alerta": alerta.id_alerta,
                "motivo": motivo,
                "nota": str(ruta) if ruta else "",
            })
        return cerradas

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
    # Exploración de mercado (a demanda)
    # ------------------------------------------------------------------
    def run_market_exploration(self) -> Dict[str, Any]:
        """Busca oportunidades nuevas en el mercado y confirma cuáles aguantan.

        Dos fases que no se mezclan:

          1. **Convicción cualitativa.** `MarketExplorer` busca en la web
             candidatos fuera de todo lo que Sharky ya vigila, y redacta la
             tesis de cada uno. No propone ni un solo precio.
          2. **Confirmación cuantitativa.** Cada candidato pasa por el mismo
             filtro que `UNIVERSO_CONVICCION` (`scan_universe`): caída desde
             el máximo anual, tendencia sobre la media de 200 sesiones, stop
             por volatilidad realizada y R:R mínimo. Sólo los que lo superan
             se convierten en alerta.

        Una exploración con candidatos y sin alertas es un resultado válido:
        significa que las ideas son buenas y los precios de hoy no. El informe
        guarda ambas cosas para poder volver sobre ellas.
        """
        fecha_str = date.today().isoformat()
        valuation, health, _ = self.snapshot_estado()
        tesis = self.vault.list_active_theses()
        alertas_vivas = [a for _, a in self.vault.list_active_alerts()]
        tickers_cartera = [p.ticker for p in valuation.posiciones]

        # Todo lo que Sharky ya vigila por alguna vía. Proponer cualquiera de
        # estos sería gastar una búsqueda en algo que ya está cubierto.
        ya_cubierto = sorted({
            *(t.upper() for t in tickers_cartera),
            *(a.ticker.upper() for a in alertas_vivas),
            *(t.ticker.upper() for _, t in tesis if t.ticker),
            *(t.upper() for t in UNIVERSO_CONVICCION),
        })

        resultado = self.explorer.explore(
            ya_cubierto=ya_cubierto,
            sectores=valuation.exposicion_sectorial_pct,
            estado_vital=health.estado_vital.value,
            efectivo_pct=valuation.peso_efectivo_pct,
            contexto_noticias=self._contexto_noticias_exploracion(),
        )

        # Fase 2: los precios deciden. Se cotiza por el símbolo que declaró el
        # explorador, no por el ticker: un candidato europeo puede necesitar
        # sufijo de mercado (`RHM.DE`) que el ticker interno no lleva.
        nuevas_alertas: List[OpportunityAlert] = []
        if resultado.candidatos:
            snapshots = {
                c.ticker: self.market.get_snapshot(c.ticker, symbol=c.simbolo or None)
                for c in resultado.candidatos
            }
            nuevas_alertas = self.detector.scan_universe(
                {c.ticker: c.perfil() for c in resultado.candidatos},
                snapshots,
                existing_positions=tickers_cartera,
                ya_alertado=self.vault.has_active_alert,
                simbolos={c.ticker: c.simbolo for c in resultado.candidatos},
            )
            for alerta in nuevas_alertas:
                self.vault.write_opportunity_alert(alerta)

        diagnostico = list(self.detector.ultimo_diagnostico) if resultado.candidatos else []
        ruta = self.vault.write_market_exploration(
            fecha_str, resultado, diagnostico, nuevas_alertas
        )

        return {
            "fecha": fecha_str,
            "disponible": resultado.disponible,
            "modelo": resultado.modelo,
            "error": resultado.error,
            "aviso_parseo": resultado.aviso_parseo,
            "busquedas_realizadas": resultado.busquedas_realizadas,
            "num_fuentes": len(resultado.fuentes),
            "candidatos": [c.model_dump() for c in resultado.candidatos],
            "alertas_nuevas": [a.model_dump() for a in nuevas_alertas],
            "diagnostico_radar": diagnostico,
            "excluidos": ya_cubierto,
            "informe_guardado": str(ruta),
        }

    def _contexto_noticias_exploracion(self) -> str:
        """Bloque de contexto con el último escaneo semanal, si lo hay.

        Sin esto el explorador buscaría a ciegas cada vez. Con esto arranca
        sabiendo qué se movió en el mercado la última semana, que es
        justamente donde suelen abrirse las asimetrías que busca.
        """
        ultima = self.vault.leer_ultimas_noticias_semanales()
        if not ultima or not ultima.get("disponible") or not ultima.get("resumen"):
            return ""
        return (
            "## Lo último que viste en el mercado\n\n"
            f"Resumen del escaneo de noticias del {ultima['fecha'].isoformat()} "
            "sobre las posiciones en cartera. Úsalo como pista de qué se está "
            "moviendo, no como lista de candidatos:\n\n"
            f"{ultima['resumen']}\n"
        )

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
            # Las tesis enteras, no su recuento: hasta 2026-09 el comité
            # deliberaba sobre la cartera sin ver ni un ticker de la convicción
            # que la sostiene.
            theses=[t for _, t in tesis],
            noticias_recientes=noticias_recientes,
        )

    # ------------------------------------------------------------------
    # Revisión de tesis
    # ------------------------------------------------------------------
    def run_thesis_review(
        self,
        conclusion_estudio: str = "",
        contexto=None,
    ) -> Dict[str, Any]:
        """Revisa las tesis que tienen algo que decir y lo anota en cada nota.

        Dos fases, como en el explorador, y por el mismo motivo:

          1. **Selección determinista** (`thesis_review.seleccionar`, sin API):
             qué tesis se han movido, han tocado un nivel, incumplen algo o
             salen en las noticias del mes -- más la red de seguridad, para
             que ninguna quede olvidada por estar tranquila.
          2. **Juicio cualitativo** (Claude, con el racional COMPLETO de cada
             tesis, no los 300 caracteres que recibe el estudio mensual).

        Lo que se escribe es una sección fechada encima de lo anterior y dos
        campos de frontmatter (`fecha_revision`, `veredicto_revision`).
        Ningún número de la tesis se toca: ver `VaultManager.CAMPOS_INTOCABLES`.

        `contexto` permite reutilizar la valoración que el estudio mensual ya
        hizo, en vez de volver a cotizar toda la cartera.
        """
        mes = self._mes_actual()
        fecha_str = date.today().isoformat()

        valuation, health, incumplimientos = (
            contexto if contexto is not None else self.snapshot_estado()
        )
        tesis = self.vault.list_active_theses()
        niveles = self.revisar_niveles(tesis, valuation)
        memoria = self.vault.leer_memoria_diario(DIAS_CONTEXTO_MENSUAL)
        noticias = self.vault.leer_noticias_semanales(DIAS_CONTEXTO_MENSUAL)

        a_revisar, omitidas = thesis_review.seleccionar(
            tesis,
            memoria=memoria,
            noticias=noticias,
            incumplimientos=incumplimientos,
            niveles=niveles,
            revisadas=self.vault.leer_fechas_revision_tesis(),
        )

        resultado = self.reviewer.review(
            a_revisar,
            mes=mes,
            valuation=valuation,
            conclusion_estudio=conclusion_estudio,
            contexto_noticias=ClaudeBrainClient._formatear_noticias_del_mes(noticias),
            contexto_diario=ClaudeBrainClient._formatear_memoria(memoria),
        )

        # Anotar sólo lo que se pidió revisar y volvió con veredicto. Una tesis
        # sin veredicto no se toca: es preferible que su `fecha_revision` siga
        # vieja -- y que la red de seguridad la vuelva a seleccionar -- a
        # marcarla como revisada cuando nadie la leyó.
        por_ticker = {s.ticker.upper(): s for s in a_revisar}
        anotadas: List[Dict[str, str]] = []
        for veredicto in resultado.veredictos:
            seleccion = por_ticker.get(veredicto.ticker.upper())
            if seleccion is None:
                continue
            ruta = self.vault.anotar_revision_tesis(
                seleccion.ruta, veredicto, fecha_str, motivos=seleccion.motivos
            )
            anotadas.append({
                # El ticker canonico es el de la boveda, no el que devuelve el
                # modelo: `ThesisVerdict` normaliza a mayusculas para poder
                # casar, y `Rare_Earths` volveria como `RARE_EARTHS`.
                "ticker": seleccion.ticker,
                "veredicto": veredicto.veredicto,
                "propuesta_niveles": veredicto.propuesta_niveles,
                "nota": str(ruta),
            })

        return {
            "fecha": fecha_str,
            "mes": mes,
            "disponible": resultado.disponible,
            "modelo": resultado.modelo,
            "error": resultado.error,
            "aviso_parseo": resultado.aviso_parseo,
            "tesis_activas": len(tesis),
            "seleccionadas": [
                {"ticker": s.ticker, "motivos": s.motivos} for s in a_revisar
            ],
            "omitidas": [
                {"ticker": s.ticker, "motivo": s.descarte} for s in omitidas
            ],
            "revisadas": anotadas,
            "sintesis": resultado.texto,
        }

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
        3. La revisión de tesis (`run_thesis_review`) devuelve ese juicio al
           fichero de cada tesis que lo necesite, en vez de dejarlo sólo en
           la nota del estudio.
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

        # La revisión de tesis cierra el mes: el estudio acaba de dictar
        # MANTENER/REDUCIR/CERRAR posición a posición, y esto devuelve ese
        # juicio al fichero de cada tesis en vez de dejarlo morir aquí. Va
        # DESPUÉS de escribir el estudio y envuelta en su propio try: si la
        # revisión falla, el estudio -- que es lo caro y ya está en disco --
        # no se pierde con ella.
        revision: Dict[str, Any] = {"disponible": False, "error": "no ejecutada"}
        try:
            revision = self.run_thesis_review(
                conclusion_estudio=resultado.conclusion,
                contexto=(valuation, health, incumplimientos),
            )
        except Exception as exc:
            revision = {"disponible": False, "error": f"{type(exc).__name__}: {exc}"}
            print(f"[SharkyAgent] La revisión de tesis falló: {exc}")

        res = self._resumen_rebalanceo(informe, ruta_rebalanceo)
        res.update({
            "mes": mes,
            "estudio_guardado": str(ruta_estudio),
            "estudio_simulado": resultado.simulado,
            "estudio_error": resultado.error,
            "modelo": resultado.modelo,
            "revision_tesis": revision,
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
