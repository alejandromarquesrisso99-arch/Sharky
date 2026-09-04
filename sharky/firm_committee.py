"""
Comité de Inversión y CIO.

Recoge los informes de las cuatro mesas y los eleva al CIO (Claude) para una
resolución ejecutiva. El veredicto declara si fue razonado por el modelo o
generado de forma determinista.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from sharky.claude_client import ClaudeBrainClient
from sharky.firm_departments import (
    DepartmentReport,
    FundamentalDesk,
    MacroDesk,
    RiskDesk,
    SentimentDesk,
)
from sharky.models import (
    HealthStatus,
    MarketSnapshot,
    PortfolioValuation,
    RiskBreach,
)


class InvestmentCommittee:
    def __init__(self, claude: Optional[ClaudeBrainClient] = None):
        self.macro_desk = MacroDesk()
        self.fundamental_desk = FundamentalDesk()
        self.risk_desk = RiskDesk()
        self.sentiment_desk = SentimentDesk()
        self.claude = claude or ClaudeBrainClient()

    def convene_session(
        self,
        health: HealthStatus,
        market_snapshots: Dict[str, MarketSnapshot],
        macro_snapshots: Dict[str, MarketSnapshot],
        valuation: Optional[PortfolioValuation] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
        theses_count: int = 0,
    ) -> Dict[str, Any]:
        informes = [
            self.macro_desk.generate_report(macro_snapshots),
            self.fundamental_desk.evaluate_equity_universe(market_snapshots),
            self.risk_desk.audit_portfolio_risk(health, valuation, incumplimientos),
            self.sentiment_desk.evaluate_sentiment(market_snapshots, macro_snapshots),
        ]

        dossier = self._construir_dossier(informes)
        fallback = self._veredicto_determinista(health, informes, incumplimientos or [])
        veredicto = self.claude.synthesize_cio_verdict(health, dossier, fallback)

        return {
            "fecha": datetime.now().strftime("%Y-%m-%d"),
            "departamentos": [r.model_dump() for r in informes],
            "veredicto_cio": veredicto.texto,
            "veredicto_simulado": veredicto.simulado,
            "modelo": veredicto.modelo,
            "tesis_activas": theses_count,
        }

    @staticmethod
    def _construir_dossier(informes: List[DepartmentReport]) -> str:
        bloques = []
        for r in informes:
            puntos = "\n".join(f"  * {p}" for p in r.puntos_clave)
            riesgos = "\n".join(f"  ! {x}" for x in r.alertas_o_riesgos)
            ausentes = (
                "\n  ? Datos no disponibles: " + "; ".join(r.datos_ausentes)
                if r.datos_ausentes
                else ""
            )
            bloques.append(
                f"### {r.departamento} ({r.responsable})\n"
                f"- Diagnóstico: {r.diagnostico}\n"
                f"- Puntos clave:\n{puntos}\n"
                f"- Riesgos:\n{riesgos}{ausentes}\n"
                f"- Recomendación táctica: {r.recomendacion_tactica}\n"
            )
        return "\n".join(bloques)

    @staticmethod
    def _veredicto_determinista(
        health: HealthStatus,
        informes: List[DepartmentReport],
        incumplimientos: List[RiskBreach],
    ) -> str:
        """Resolución construida a partir de los informes, sin razonamiento."""
        graves = [b for b in incumplimientos if b.severidad == "ALTA"]
        lineas = [
            "### 👔 Resolución Ejecutiva del CIO (generada sin Claude)",
            "",
            f"Estado de la firma: `{health.estado_vital.value}`, NAV "
            f"{health.nav_actual_eur:,.2f} €, drawdown {health.drawdown_actual_pct:.2f}%.",
            "",
            "**Síntesis de las mesas:**",
        ]
        lineas.extend(f"* **{r.departamento}:** {r.diagnostico}" for r in informes)
        lineas.append("")

        if graves:
            lineas.append(f"**Directivas obligatorias ({len(graves)} incumplimientos graves):**")
            lineas.extend(f"{i+1}. {b.accion_correctiva}" for i, b in enumerate(graves))
        else:
            lineas.append("**Directivas:** la cartera cumple el mandato; mantener disciplina intrames.")

        lineas += [
            "",
            "**Día 1:** ejecutar el plan de [[08_Rebalanceos_Mensuales]] respetando los "
            "límites del mandato.",
            "",
            "> Esta resolución encadena los diagnósticos de las mesas mediante reglas fijas.",
            "> No es deliberación: configura `ANTHROPIC_API_KEY` para que el CIO razone.",
        ]
        return "\n".join(lineas)
