"""
Estructura departamental de Sharky Capital Management.

Cada mesa produce un `DepartmentReport` derivado de datos medidos. Si un dato
falta, el informe lo dice: la versión anterior sustituía las cotizaciones
ausentes por constantes (`tlt.precio_actual if tlt else 95.0`), lo que convertía
un fallo de datos en un diagnóstico inventado.
"""

from typing import Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field

from sharky.config import (
    DEATH_DRAWDOWN_PCT,
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
)
from sharky.models import (
    HealthStatus,
    MarketSnapshot,
    PortfolioValuation,
    RiskBreach,
)


class DepartmentReport(BaseModel):
    departamento: str
    responsable: str
    fecha: str
    diagnostico: str
    puntos_clave: List[str] = Field(default_factory=list)
    alertas_o_riesgos: List[str] = Field(default_factory=list)
    recomendacion_tactica: str
    # Datos que la mesa no pudo obtener. Se publica junto al informe.
    datos_ausentes: List[str] = Field(default_factory=list)


def _hoy() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _fmt(snap: Optional[MarketSnapshot]) -> Optional[str]:
    """Cotización formateada, o None si no hay dato utilizable."""
    if snap is None or snap.precio_actual <= 0:
        return None
    marca = "" if snap.es_fiable else " *(dato no fiable)*"
    return f"{snap.precio_actual:,.2f} {snap.divisa} ({snap.cambio_diario_pct:+.2f}%){marca}"


class MacroDesk:
    """Macroeconomía, geopolítica y cadenas de suministro."""

    ETIQUETAS = {
        "TLT": ("Bono largo USA (TLT)", "expectativas de tipos y coste del dinero"),
        "GLD": ("Oro (GLD)", "demanda de refugio y desdolarización"),
        "USO": ("Petróleo WTI (USO)", "presión inflacionaria por energía y logística"),
        "SPY": ("Renta variable USA (SPY)", "apetito por riesgo agregado"),
        "QQQ": ("Tecnología (QQQ)", "prima de crecimiento y duración de flujos"),
    }

    def generate_report(self, macro_snapshots: Dict[str, MarketSnapshot]) -> DepartmentReport:
        puntos: List[str] = []
        ausentes: List[str] = []

        for ticker, (nombre, lectura) in self.ETIQUETAS.items():
            texto = _fmt(macro_snapshots.get(ticker))
            if texto is None:
                ausentes.append(f"{nombre}: sin cotización disponible")
                continue
            puntos.append(f"**{nombre}:** {texto} — {lectura}.")

        spy = macro_snapshots.get("SPY")
        qqq = macro_snapshots.get("QQQ")
        if spy and qqq and spy.precio_actual > 0 and qqq.precio_actual > 0:
            spread = qqq.cambio_diario_pct - spy.cambio_diario_pct
            sesgo = "a favor del crecimiento" if spread > 0 else "a favor del valor y la defensiva"
            puntos.append(
                f"**Rotación intradía:** la tecnología se comporta {spread:+.2f} puntos "
                f"respecto al índice general, un sesgo {sesgo}."
            )
            diagnostico = (
                f"Sesión con apetito por riesgo {'positivo' if spy.cambio_diario_pct >= 0 else 'negativo'} "
                f"({spy.cambio_diario_pct:+.2f}% en el índice general) y liderazgo "
                f"{'tecnológico' if spread > 0 else 'no tecnológico'}."
            )
        else:
            diagnostico = (
                "Diagnóstico limitado: faltan las referencias de renta variable "
                "necesarias para caracterizar el régimen de mercado."
            )

        riesgos = [
            "Controles de exportación sobre semiconductores que alteran el mercado direccionable.",
            "Persistencia inflacionaria en servicios que retrase la relajación monetaria.",
            "Dependencia de rutas marítimas y de suministro de metales estratégicos.",
        ]
        if ausentes:
            riesgos.append(
                f"Cobertura de datos macro incompleta ({len(ausentes)} referencias ausentes): "
                f"el diagnóstico es parcial."
            )

        return DepartmentReport(
            departamento="Macroeconomía Global & Geopolítica",
            responsable="Chief Macro Strategist",
            fecha=_hoy(),
            diagnostico=diagnostico,
            puntos_clave=puntos or ["Sin datos macro disponibles en esta sesión."],
            alertas_o_riesgos=riesgos,
            recomendacion_tactica=(
                "Priorizar negocios con poder real de fijación de precios y mantener "
                "cobertura en activos reales frente al riesgo político."
            ),
            datos_ausentes=ausentes,
        )


class FundamentalDesk:
    """Análisis fundamental y fosos económicos."""

    def evaluate_equity_universe(self, snapshots: Dict[str, MarketSnapshot]) -> DepartmentReport:
        puntos: List[str] = []
        ausentes: List[str] = []
        con_multiplo: List[MarketSnapshot] = []

        for snap in sorted(snapshots.values(), key=lambda s: s.ticker):
            if snap.precio_actual <= 0:
                ausentes.append(f"{snap.ticker}: sin cotización")
                continue
            if snap.pe_ratio is None:
                ausentes.append(f"{snap.ticker}: sin múltiplo P/E disponible")
                continue
            con_multiplo.append(snap)
            cap = (
                f", capitalización {snap.market_cap / 1e9:,.0f} MM {snap.divisa}"
                if snap.market_cap
                else ""
            )
            puntos.append(
                f"**[[{snap.ticker}]]:** {snap.precio_actual:,.2f} {snap.divisa}, "
                f"P/E `{snap.pe_ratio:.1f}`{cap}."
            )

        if con_multiplo:
            multiplos = sorted(con_multiplo, key=lambda s: s.pe_ratio or 0.0)
            mediana = multiplos[len(multiplos) // 2].pe_ratio
            barato, caro = multiplos[0], multiplos[-1]
            diagnostico = (
                f"P/E mediano del universo cubierto: `{mediana:.1f}` sobre "
                f"{len(con_multiplo)} activos con múltiplo disponible. "
                f"El extremo barato es [[{barato.ticker}]] (`{barato.pe_ratio:.1f}`) y el "
                f"más exigente [[{caro.ticker}]] (`{caro.pe_ratio:.1f}`)."
            )
            recomendacion = (
                f"Concentrar capital nuevo en el cuartil de valoración más bajo del universo "
                f"cubierto, exigiendo evidencia de foso; tratar todo P/E por encima de "
                f"`{caro.pe_ratio:.0f}` como una apuesta sobre ejecución perfecta."
            )
            riesgos = [
                "Compresión de múltiplos si el crecimiento de beneficios se desacelera.",
                "Dependencia del CapEx de un número reducido de hiperescaladores.",
                "El P/E de Yahoo no está normalizado por partidas extraordinarias.",
            ]
        else:
            diagnostico = (
                "No se ha podido obtener ningún múltiplo de valoración en esta sesión: "
                "el análisis fundamental cuantitativo no está disponible."
            )
            recomendacion = (
                "No emitir juicio de valoración hasta recuperar los datos fundamentales."
            )
            riesgos = ["Ausencia total de múltiplos: cualquier conclusión sería especulativa."]

        return DepartmentReport(
            departamento="Análisis Fundamental & Fosos Económicos",
            responsable="Head of Equity Research",
            fecha=_hoy(),
            diagnostico=diagnostico,
            puntos_clave=puntos or ["Sin múltiplos disponibles en esta sesión."],
            alertas_o_riesgos=riesgos,
            recomendacion_tactica=recomendacion,
            datos_ausentes=ausentes,
        )


class RiskDesk:
    """Mesa de riesgo cuantitativo y supervivencia (CRO)."""

    def audit_portfolio_risk(
        self,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
    ) -> DepartmentReport:
        incumplimientos = incumplimientos or []
        puntos = [
            f"**Estado vital:** `{health.estado_vital.value}` (salud {health.salud_porcentaje:.1f}%).",
            f"**NAV:** {health.nav_actual_eur:,.2f} € frente a un máximo histórico de "
            f"{health.nav_maximo_historico_eur:,.2f} €.",
            f"**Drawdown:** actual {health.drawdown_actual_pct:.2f}%, máximo registrado "
            f"{health.drawdown_maximo_pct:.2f}% (umbral fatal {DEATH_DRAWDOWN_PCT:.1f}%).",
        ]

        if valuation:
            mayor = max(valuation.posiciones, key=lambda p: p.peso_pct, default=None)
            puntos.append(
                f"**Concentración:** {len(valuation.posiciones)} posiciones; la mayor es "
                f"[[{mayor.ticker}]] con {mayor.peso_pct:.2f}% del NAV (tope "
                f"{MAX_POSITION_SIZE_PCT:.1f}%)."
                if mayor
                else "**Concentración:** cartera sin posiciones abiertas."
            )
            sectores = sorted(valuation.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1])
            if sectores:
                s, w = sectores[0]
                puntos.append(
                    f"**Sector dominante:** {s} con {w:.2f}% del NAV (tope "
                    f"{MAX_SECTOR_SIZE_PCT:.1f}%)."
                )
            puntos.append(
                f"**Liquidez:** {valuation.efectivo_eur:,.2f} € "
                f"({valuation.peso_efectivo_pct:.2f}% del NAV, mínimo exigido "
                f"{MIN_CASH_PCT:.1f}%)."
            )
            puntos.append(
                f"**Cobertura de datos:** {valuation.cobertura_mercado_pct:.1f}% del NAV "
                f"valorado con cotizaciones fiables."
            )

        riesgos = [b.mensaje for b in incumplimientos] or [
            "Sin incumplimientos activos. Mantener la obligatoriedad del stop-loss."
        ]

        graves = [b for b in incumplimientos if b.severidad == "ALTA"]
        if graves:
            diagnostico = (
                f"**{len(graves)} incumplimiento(s) grave(s) del mandato.** La cartera opera "
                f"fuera de los límites fijados en [[Reglas_De_Supervivencia]] y requiere "
                f"corrección en el próximo Día 1."
            )
            recomendacion = (
                "Ejecutar las acciones correctivas del rebalanceo antes de asignar "
                "capital nuevo. Prioridad: restaurar liquidez, después desconcentrar."
            )
        else:
            diagnostico = (
                "Parámetros de solvencia y concentración dentro de los márgenes del mandato."
            )
            recomendacion = (
                f"Mantener la reserva de liquidez por encima del {MIN_CASH_PCT:.0f}% y el "
                f"stop-loss obligatorio en toda posición."
            )

        return DepartmentReport(
            departamento="Gestión Cuantitativa de Riesgo (CRO)",
            responsable="Chief Risk Officer",
            fecha=_hoy(),
            diagnostico=diagnostico,
            puntos_clave=puntos,
            alertas_o_riesgos=riesgos,
            recomendacion_tactica=recomendacion,
        )


class SentimentDesk:
    """Psicología de mercado, narrativas y flujos."""

    def evaluate_sentiment(
        self,
        snapshots: Dict[str, MarketSnapshot],
        macro_snapshots: Optional[Dict[str, MarketSnapshot]] = None,
    ) -> DepartmentReport:
        macro_snapshots = macro_snapshots or {}
        puntos: List[str] = []
        ausentes: List[str] = []

        validos = [s for s in snapshots.values() if s.precio_actual > 0]
        if validos:
            avanzan = sum(1 for s in validos if s.cambio_diario_pct > 0)
            amplitud = avanzan / len(validos) * 100.0
            puntos.append(
                f"**Amplitud del radar:** {avanzan} de {len(validos)} activos en positivo "
                f"({amplitud:.0f}%)."
            )
            dispersion = max(s.cambio_diario_pct for s in validos) - min(
                s.cambio_diario_pct for s in validos
            )
            puntos.append(
                f"**Dispersión:** {dispersion:.2f} puntos entre el mejor y el peor activo del "
                f"radar; a mayor dispersión, menos movimiento de manada."
            )
        else:
            ausentes.append("Radar de activos sin cotizaciones válidas")
            amplitud = None

        gld = macro_snapshots.get("GLD")
        tlt = macro_snapshots.get("TLT")
        if gld and gld.precio_actual > 0:
            puntos.append(
                f"**Demanda de refugio:** el oro se mueve {gld.cambio_diario_pct:+.2f}%, "
                f"{'señal de búsqueda de cobertura' if gld.cambio_diario_pct > 0 else 'sin tensión defensiva'}."
            )
        else:
            ausentes.append("Oro (GLD): sin cotización")
        if tlt and tlt.precio_actual > 0:
            puntos.append(
                f"**Bonos:** {tlt.cambio_diario_pct:+.2f}%, "
                f"{'relajación' if tlt.cambio_diario_pct > 0 else 'tensión'} en las expectativas de tipos."
            )
        else:
            ausentes.append("Bono largo (TLT): sin cotización")

        if amplitud is None:
            diagnostico = "Sin datos suficientes para caracterizar el sentimiento."
        elif amplitud >= 70:
            diagnostico = f"Participación amplia ({amplitud:.0f}% en positivo): avance saludable, vigilar complacencia."
        elif amplitud >= 40:
            diagnostico = f"Participación mixta ({amplitud:.0f}% en positivo): mercado selectivo, sin manada clara."
        else:
            diagnostico = f"Participación estrecha ({amplitud:.0f}% en positivo): presión vendedora generalizada."

        return DepartmentReport(
            departamento="Psicología de Mercado & Flujos",
            responsable="Head of Market Psychology",
            fecha=_hoy(),
            diagnostico=diagnostico,
            puntos_clave=puntos or ["Sin datos de sentimiento en esta sesión."],
            alertas_o_riesgos=[
                "Sesgo de confirmación sobre las temáticas ya sobreponderadas en cartera.",
                "FOMO en activos con narrativa fuerte y amplitud estrecha.",
                "Aversión a materializar pérdidas en posiciones que han roto su tesis.",
            ],
            recomendacion_tactica=(
                "Prohibido comprar por impulso intrames. Acumular evidencia y decidir el Día 1."
            ),
            datos_ausentes=ausentes,
        )
