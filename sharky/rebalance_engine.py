"""
Motor de Rebalanceo Mensual (Día 1).

Construye la lista exacta de qué vender y qué comprar partiendo de la cartera
real valorada a mercado, con un orden de prioridades que refleja el mandato:

  1. Restaurar la liquidez mínima (sin caja no hay supervivencia).
  2. Corregir la sobreconcentración por activo y por sector.
  3. Liquidar posiciones "polvo" que no mueven la aguja y diluyen la gestión.
  4. Sólo entonces, asignar el presupuesto libre a las mejores convicciones.

Todos los importes en EUR. Los stops y targets se expresan en la divisa de
cotización de cada activo, porque es ahí donde se introduce la orden.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime

from sharky.config import (
    MAX_POSITION_SIZE_ALERTA_PCT,
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
)
from sharky.fx import FxProvider
from sharky.market_data import MarketDataProvider
from sharky.models import (
    AllocationProposal,
    HealthStatus,
    InvestmentThesis,
    MarketSnapshot,
    MonthlyRebalanceReport,
    OpportunityAlert,
    PortfolioValuation,
    RebalanceAction,
    RiskBreach,
    VitalState,
)
from sharky.risk_governor import RiskGovernor

# Por debajo de este peso una posición no aporta retorno significativo y sí
# coste de seguimiento. El diagnóstico inicial de la cartera lo señaló como
# problema explícito (5 posiciones por debajo de 55 €).
UMBRAL_POLVO_PCT = 1.0

# Holgura para no emitir órdenes por diferencias irrelevantes de redondeo.
UMBRAL_ACCION_PCT = 0.25

# Peso mínimo que debe tener una posición para participar en un recorte
# proporcional: no se toca lo que ya es pequeño.
PESO_MINIMO_RECORTE_PCT = 2.0


class MonthlyRebalanceEngine:
    def __init__(
        self,
        market: Optional[MarketDataProvider] = None,
        governor: Optional[RiskGovernor] = None,
        fx: Optional[FxProvider] = None,
    ):
        self.market = market or MarketDataProvider()
        self.governor = governor or RiskGovernor()
        self.fx = fx or FxProvider()

    # ------------------------------------------------------------------
    def generate_monthly_plan(
        self,
        health: HealthStatus,
        valuation: PortfolioValuation,
        active_theses: Optional[List[Tuple[object, InvestmentThesis]]] = None,
        alerts: Optional[List[OpportunityAlert]] = None,
        macro_snapshots: Optional[Dict[str, MarketSnapshot]] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
    ) -> MonthlyRebalanceReport:
        ahora = datetime.now()
        nav = valuation.nav_eur
        active_theses = active_theses or []
        alerts = alerts or []
        incumplimientos = incumplimientos or self.governor.audit_portfolio(valuation, health)

        cash_objetivo_pct = self.governor.target_cash_pct(health.estado_vital)
        presupuesto_equity_pct = max(0.0, 100.0 - cash_objetivo_pct)

        tope_trim = self._tope_trim(health.estado_vital)
        tope_compra = self.governor.max_position_pct(health.estado_vital)

        actuales = {p.ticker: p.peso_pct for p in valuation.posiciones}
        sectores = {p.ticker: (p.sector or "Sin Clasificar") for p in valuation.posiciones}
        objetivo = dict(actuales)
        motivos: Dict[str, str] = {}
        # Tickers cuyo objetivo lo impone un límite duro del mandato. Para ellos
        # no se aplica la banda muerta: una posición en incumplimiento no puede
        # quedarse en "MANTENER" porque el exceso sea pequeño.
        forzados: set = set()

        # --- 1. Liquidar posiciones polvo ---------------------------------
        for ticker, peso in actuales.items():
            if 0 < peso < UMBRAL_POLVO_PCT:
                objetivo[ticker] = 0.0
                forzados.add(ticker)
                motivos[ticker] = (
                    f"Liquidación de posición residual ({peso:.2f}% del NAV): no aporta "
                    f"retorno material y consume atención de gestión."
                )

        # --- 2. Tope por activo -------------------------------------------
        for ticker, peso in list(objetivo.items()):
            if peso > tope_trim:
                objetivo[ticker] = tope_trim
                forzados.add(ticker)
                motivos[ticker] = (
                    f"Recorte obligatorio del CRO: {peso:.2f}% supera el tope del "
                    f"{tope_trim:.1f}% por activo."
                )

        # --- 3. Tope por sector -------------------------------------------
        for sector, exceso in self._sectores_excedidos(objetivo, sectores).items():
            miembros = {t: w for t, w in objetivo.items() if sectores.get(t) == sector and w > 0}
            recortes = self._recorte_proporcional(miembros, exceso, peso_minimo=0.0)
            for ticker, recorte in recortes.items():
                objetivo[ticker] = max(0.0, objetivo[ticker] - recorte)
                forzados.add(ticker)
                motivos[ticker] = (
                    f"Reducción por concentración sectorial: {sector} excedía el "
                    f"{MAX_SECTOR_SIZE_PCT:.1f}% del NAV."
                )

        # --- 4. Suelo de liquidez -----------------------------------------
        total_equity = sum(objetivo.values())
        exceso_equity = total_equity - presupuesto_equity_pct
        if exceso_equity > UMBRAL_ACCION_PCT:
            recortes = self._recorte_proporcional(
                {t: w for t, w in objetivo.items() if w > 0},
                exceso_equity,
                peso_minimo=PESO_MINIMO_RECORTE_PCT,
            )
            for ticker, recorte in recortes.items():
                objetivo[ticker] = max(0.0, objetivo[ticker] - recorte)
                forzados.add(ticker)
                motivos.setdefault(
                    ticker,
                    f"Desinversión parcial para restaurar la liquidez objetivo del "
                    f"{cash_objetivo_pct:.1f}%.",
                )

        # --- 5. Asignar presupuesto libre a nuevas convicciones -----------
        candidatos = self._candidatos(active_theses, alerts, objetivo)
        presupuesto_libre = presupuesto_equity_pct - sum(objetivo.values())
        nuevas: Dict[str, AllocationProposal] = {}

        if tope_compra > 0 and presupuesto_libre > UMBRAL_ACCION_PCT:
            for cand in candidatos:
                if presupuesto_libre <= UMBRAL_ACCION_PCT:
                    break
                sector_cand = cand["sector"] or "Sin Clasificar"
                margen_sector = MAX_SECTOR_SIZE_PCT - self._peso_sector(objetivo, sectores, sector_cand, nuevas)
                asignacion = min(cand["peso_max"], tope_compra, presupuesto_libre, margen_sector)
                asignacion = round(asignacion, 2)
                if asignacion < 1.0:  # no merece la pena abrir una posición polvo
                    continue

                presupuesto_libre -= asignacion
                snap = cand["snapshot"]
                capital_eur = round(nav * asignacion / 100.0, 2)
                titulos = self._titulos(capital_eur, snap)

                nuevas[cand["ticker"]] = AllocationProposal(
                    ticker=cand["ticker"],
                    sector=sector_cand,
                    accion=RebalanceAction.COMPRAR,
                    peso_actual_pct=0.0,
                    peso_objetivo_pct=asignacion,
                    capital_objetivo_eur=capital_eur,
                    delta_eur=capital_eur,
                    precio_estimado=snap.precio_actual,
                    divisa_precio=snap.divisa,
                    acciones_estimadas=titulos,
                    stop_loss_sugerido=cand["stop_loss"],
                    target_sugerido=cand["target"],
                    conviccion=cand["conviccion"],
                    motivo=cand["motivo"],
                    fuente_precio=snap.fuente,
                )
                sectores[cand["ticker"]] = sector_cand

        # --- 6. Materializar propuestas -----------------------------------
        propuestas: List[AllocationProposal] = []
        precios = {p.ticker: p for p in valuation.posiciones}

        for ticker in actuales:
            peso_act = actuales[ticker]
            peso_obj = round(objetivo.get(ticker, 0.0), 2)
            delta_pct = peso_obj - peso_act
            pos = precios[ticker]

            # Un objetivo impuesto por un límite del mandato se ejecuta aunque
            # el ajuste sea menor que la banda muerta de ruido.
            es_forzado = ticker in forzados
            if peso_obj <= 0.0:
                accion = RebalanceAction.VENDER
            elif delta_pct < 0 and (es_forzado or delta_pct < -UMBRAL_ACCION_PCT):
                accion = RebalanceAction.REDUCIR
            elif delta_pct > UMBRAL_ACCION_PCT:
                accion = RebalanceAction.INCREMENTAR
            else:
                accion = RebalanceAction.MANTENER
                peso_obj = peso_act

            if accion == RebalanceAction.MANTENER:
                # Sin cambio de posición: el capital objetivo es el valor actual y
                # el delta es exactamente cero, no unos céntimos de redondeo.
                capital_eur = pos.valor_mercado_eur
                delta_eur = 0.0
            else:
                capital_eur = round(nav * peso_obj / 100.0, 2)
                delta_eur = round(capital_eur - pos.valor_mercado_eur, 2)
            titulos = (
                round(capital_eur / pos.precio_unitario_eur, 6)
                if pos.precio_unitario_eur > 0
                else 0.0
            )

            propuestas.append(
                AllocationProposal(
                    ticker=ticker,
                    nota_activo=pos.nota_activo,
                    sector=sectores.get(ticker, ""),
                    accion=accion,
                    peso_actual_pct=round(peso_act, 2),
                    peso_objetivo_pct=peso_obj,
                    capital_objetivo_eur=capital_eur,
                    delta_eur=delta_eur,
                    precio_estimado=pos.precio_cotizacion,
                    divisa_precio=pos.divisa_cotizacion,
                    acciones_estimadas=titulos,
                    stop_loss_sugerido=round(pos.precio_cotizacion * 0.92, 2),
                    target_sugerido=round(pos.precio_cotizacion * 1.25, 2),
                    conviccion=8,
                    motivo=motivos.get(
                        ticker,
                        f"Mantenimiento de posición core en {sectores.get(ticker, 'cartera')}."
                        if accion == RebalanceAction.MANTENER
                        else "Ajuste de ponderación hacia el objetivo estratégico.",
                    ),
                    fuente_precio=pos.fuente_precio,
                )
            )

        propuestas.extend(nuevas.values())
        propuestas.sort(key=lambda p: (-p.peso_objetivo_pct, p.ticker))

        # Liquidez objetivo efectiva: lo que queda tras las asignaciones.
        equity_final_pct = round(sum(p.peso_objetivo_pct for p in propuestas), 2)
        cash_final_pct = round(max(0.0, 100.0 - equity_final_pct), 2)

        advertencias = list(valuation.advertencias)
        if health.estado_vital in (VitalState.CUIDADOS_INTENSIVOS, VitalState.MUERTE):
            advertencias.append(
                f"Estado vital {health.estado_vital.value}: el mandato prohíbe abrir o "
                f"ampliar posiciones. Este plan sólo contiene desinversión defensiva."
            )

        return MonthlyRebalanceReport(
            mes_ano=ahora.strftime("%B %Y").capitalize(),
            fecha=ahora.strftime("%Y-%m-%d"),
            propuestas=propuestas,
            peso_cash_objetivo_pct=cash_final_pct,
            cash_objetivo_eur=round(nav * cash_final_pct / 100.0, 2),
            nav_total_eur=nav,
            incumplimientos=incumplimientos,
            cobertura_datos_pct=valuation.cobertura_mercado_pct,
            advertencias=advertencias,
            regimen_macro=self._resumen_macro(macro_snapshots),
            geopolitica_resumen=self._resumen_geopolitico(valuation),
            sentimiento_resumen=self._resumen_sentimiento(macro_snapshots),
        )

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    @staticmethod
    def _tope_trim(estado: VitalState) -> float:
        """Tope de peso usado para recortar (distinto del tope para comprar)."""
        if estado == VitalState.OPTIMO:
            return MAX_POSITION_SIZE_PCT
        if estado == VitalState.MUERTE:
            return 0.0
        return MAX_POSITION_SIZE_ALERTA_PCT

    @staticmethod
    def _sectores_excedidos(
        objetivo: Dict[str, float], sectores: Dict[str, str]
    ) -> Dict[str, float]:
        acumulado: Dict[str, float] = {}
        for ticker, peso in objetivo.items():
            if peso <= 0:
                continue
            sector = sectores.get(ticker, "Sin Clasificar")
            acumulado[sector] = acumulado.get(sector, 0.0) + peso
        return {
            s: round(w - MAX_SECTOR_SIZE_PCT, 4)
            for s, w in acumulado.items()
            if w > MAX_SECTOR_SIZE_PCT
        }

    @staticmethod
    def _peso_sector(
        objetivo: Dict[str, float],
        sectores: Dict[str, str],
        sector: str,
        nuevas: Dict[str, AllocationProposal],
    ) -> float:
        total = sum(w for t, w in objetivo.items() if sectores.get(t) == sector and w > 0)
        total += sum(p.peso_objetivo_pct for p in nuevas.values() if p.sector == sector)
        return total

    @staticmethod
    def _recorte_proporcional(
        pesos: Dict[str, float], exceso_pct: float, peso_minimo: float
    ) -> Dict[str, float]:
        """Reparte un recorte proporcionalmente al peso de cada posición."""
        elegibles = {t: w for t, w in pesos.items() if w > peso_minimo}
        base = sum(elegibles.values())
        if base <= 0 or exceso_pct <= 0:
            return {}
        return {t: round(exceso_pct * w / base, 4) for t, w in elegibles.items()}

    def _candidatos(
        self,
        active_theses: List[Tuple[object, InvestmentThesis]],
        alerts: List[OpportunityAlert],
        objetivo: Dict[str, float],
    ) -> List[dict]:
        """Candidatos de compra: tesis activas y alertas sin posición abierta."""
        vistos = {t.upper() for t, w in objetivo.items() if w > 0}
        candidatos: List[dict] = []

        for _, tesis in active_theses:
            if not tesis.ticker or tesis.ticker.upper() in vistos:
                continue
            vistos.add(tesis.ticker.upper())
            snap = self.market.get_snapshot(tesis.ticker)
            if snap.precio_actual <= 0:
                continue
            candidatos.append({
                "ticker": tesis.ticker,
                "sector": self._sector_limpio(tesis.sectores),
                "conviccion": tesis.conviccion,
                "peso_max": 8.0,
                "snapshot": snap,
                "stop_loss": tesis.stop_loss or round(snap.precio_actual * 0.92, 2),
                "target": tesis.target_precio or round(snap.precio_actual * 1.25, 2),
                "motivo": f"Apertura según tesis activa [[Tesis_{tesis.ticker}]] "
                          f"(convicción {tesis.conviccion}/10).",
            })

        for alerta in alerts:
            if not alerta.ticker or alerta.ticker.upper() in vistos:
                continue
            vistos.add(alerta.ticker.upper())
            snap = self.market.get_snapshot(alerta.ticker)
            if snap.precio_actual <= 0:
                continue
            candidatos.append({
                "ticker": alerta.ticker,
                "sector": "Sin Clasificar",
                "conviccion": alerta.conviccion,
                "peso_max": alerta.pct_max_cartera,
                "snapshot": snap,
                "stop_loss": alerta.stop_loss,
                "target": alerta.target_precio,
                "motivo": f"Oportunidad asimétrica detectada (R:R {alerta.ratio_rr:.2f}:1, "
                          f"convicción {alerta.conviccion}/10).",
            })

        candidatos.sort(key=lambda c: -c["conviccion"])
        return candidatos

    @staticmethod
    def _sector_limpio(sectores: str) -> str:
        primero = (sectores or "").split(",")[0]
        return primero.replace("[[", "").replace("]]", "").strip() or "Sin Clasificar"

    def _titulos(self, capital_eur: float, snap: MarketSnapshot) -> float:
        """Títulos estimados para un importe en EUR.

        El precio viene en `snap.divisa`, así que hay que llevarlo a EUR antes de
        dividir: hacerlo directamente sería un error de unidades del tamaño del
        tipo de cambio.
        """
        if snap.precio_actual <= 0:
            return 0.0
        try:
            tasa = self.fx.get_rate(snap.divisa).tasa
        except ValueError:
            return 0.0
        precio_eur = snap.precio_actual * tasa
        return round(capital_eur / precio_eur, 6) if precio_eur > 0 else 0.0

    # ------------------------------------------------------------------
    # Diagnósticos derivados de datos, no de plantilla
    # ------------------------------------------------------------------
    @staticmethod
    def _resumen_macro(macro: Optional[Dict[str, MarketSnapshot]]) -> str:
        if not macro:
            return "Sin datos macro disponibles en esta sesión."
        etiquetas = {
            "SPY": "Renta variable USA",
            "QQQ": "Tecnología / crecimiento",
            "TLT": "Tipos de interés (bono largo)",
            "GLD": "Oro / refugio",
            "USO": "Petróleo / inflación",
        }
        lineas = []
        for t, s in macro.items():
            marca = "" if s.es_fiable else " *(dato no fiable)*"
            lineas.append(
                f"* **{etiquetas.get(t, t)} ({t}):** {s.precio_actual:,.2f} {s.divisa} "
                f"({s.cambio_diario_pct:+.2f}%){marca}"
            )
        return "\n".join(lineas)

    @staticmethod
    def _resumen_geopolitico(valuation: PortfolioValuation) -> str:
        top = sorted(valuation.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1])[:3]
        detalle = ", ".join(f"**{s}** ({w:.1f}%)" for s, w in top)
        return (
            f"La cartera concentra su exposición temática en {detalle}. "
            f"Estos sectores dependen de decisiones presupuestarias públicas y de "
            f"cadenas de suministro sujetas a control de exportaciones, por lo que su "
            f"riesgo dominante es político antes que operativo."
        )

    @staticmethod
    def _resumen_sentimiento(macro: Optional[Dict[str, MarketSnapshot]]) -> str:
        if not macro:
            return "Sin datos de mercado para evaluar el sentimiento."
        qqq = macro.get("QQQ")
        gld = macro.get("GLD")
        tlt = macro.get("TLT")
        piezas = []
        if qqq:
            piezas.append(
                f"la tecnología ({qqq.cambio_diario_pct:+.2f}%) marca el tono del apetito por riesgo"
            )
        if gld:
            piezas.append(f"el oro ({gld.cambio_diario_pct:+.2f}%) mide la demanda de cobertura")
        if tlt:
            piezas.append(f"el bono largo ({tlt.cambio_diario_pct:+.2f}%) refleja las expectativas de tipos")
        return (
            "Lectura del día: " + "; ".join(piezas) + ". "
            "El sesgo a vigilar sigue siendo el de confirmación sobre las temáticas ya "
            "sobreponderadas en cartera."
        )
