"""
Comité de Inversión Institucional (Investment Committee & CIO) de Sharky.
Orquesta las deliberaciones entre departamentos y toma las decisiones estratégicas de cartera.
"""

from typing import Dict, Any, List
from datetime import datetime

from sharky.firm_departments import (
    MacroDesk,
    FundamentalDesk,
    RiskDesk,
    SentimentDesk,
    DepartmentReport,
)
from sharky.models import HealthStatus, MarketSnapshot
from sharky.claude_client import ClaudeBrainClient


class InvestmentCommittee:
    def __init__(self):
        self.macro_desk = MacroDesk()
        self.fundamental_desk = FundamentalDesk()
        self.risk_desk = RiskDesk()
        self.sentiment_desk = SentimentDesk()
        self.claude = ClaudeBrainClient()

    def convene_session(
        self,
        health: HealthStatus,
        market_snapshots: Dict[str, MarketSnapshot],
        macro_snapshots: Dict[str, MarketSnapshot],
        theses_count: int,
    ) -> Dict[str, Any]:
        """Convoca una sesión plenaria del comité con los 4 departamentos informando al CIO."""
        now_str = datetime.now().strftime("%Y-%m-%d")

        # 1. Recoger informes de cada departamento
        rep_macro = self.macro_desk.generate_report(macro_snapshots)
        rep_fund = self.fundamental_desk.evaluate_equity_universe(market_snapshots)
        rep_risk = self.risk_desk.audit_portfolio_risk(health, theses_count)
        rep_sent = self.sentiment_desk.evaluate_sentiment(market_snapshots)

        departmental_reports = [rep_macro, rep_fund, rep_risk, rep_sent]

        # 2. Síntesis y Veredicto del CIO (Claude)
        cio_verdict = self._synthesize_cio_verdict(health, departmental_reports)

        return {
            "fecha": now_str,
            "departamentos": [r.dict() for r in departmental_reports],
            "veredicto_cio": cio_verdict,
        }

    def _synthesize_cio_verdict(self, health: HealthStatus, reports: List[DepartmentReport]) -> str:
        """El CIO sintetiza los informes y dicta las directivas maestras."""
        if self.claude.is_live and self.claude.client:
            try:
                dept_texts = []
                for r in reports:
                    puntos = "\n".join([f"  * {p}" for p in r.puntos_clave])
                    riesgos = "\n".join([f"  ! {x}" for x in r.alertas_o_riesgos])
                    dept_texts.append(
                        f"### {r.departamento} ({r.responsable})\n"
                        f"- Diagnóstico: {r.diagnostico}\n"
                        f"- Puntos Clave:\n{puntos}\n"
                        f"- Riesgos Identificados:\n{riesgos}\n"
                        f"- Recomendación Táctica: {r.recomendacion_tactica}\n"
                    )
                full_dossier = "\n".join(dept_texts)

                cio_prompt = f"""
Actúas como el Chief Investment Officer (CIO) y Director General de la firma de inversión Sharky.
Has recibido los informes de tus 4 departamentos clave:

ESTADO DE SUPERVIVENCIA DE LA FIRMA:
- Salud Institucional: {health.salud_porcentaje:.1f}%
- Capital en Custodia: ${health.capital_actual:,.2f} USD
- Estado Vital: {health.estado_vital.value}

DOSSIER DE LOS DEPARTAMENTOS:
{full_dossier}

Emite tu Resolución Ejecutiva y Directiva Estratégica:
1. Evaluación holística de la situación (confluencia entre macro, fundamentales, riesgo y psicología).
2. Directivas innegociables para el equipo.
3. Posicionamiento ante el próximo Rebalanceo del Día 1.
"""
                resp = self.claude.client.messages.create(
                    model=self.claude.model,
                    max_tokens=1500,
                    system=self.claude._get_system_prompt(),
                    messages=[{"role": "user", "content": cio_prompt}],
                )
                return resp.content[0].text
            except Exception as e:
                pass

        # Modo Simulación Local Institucional
        return f"""### 👔 Resolución Ejecutiva del CIO (Sharky Capital)

Tras revisar las ponencias de Macroeconomía, Análisis Fundamental, Riesgo (CRO) y Psicología de Mercado:

1. **Alineación Estratégica:** Confirmamos la tesis de que la infraestructura de cómputo ([[Semiconductores]], [[Inteligencia_Artificial]]) lidera la economía real con flujos de caja sólidos.
2. **Mandato de Riesgo:** Se ratifica el dictamen del CRO: ninguna posición superará el 10% y mantenemos reserva de liquidez (`Cash >= 15%`).
3. **Horizonte Mensual:** Se ordena a todos los analistas mantener la disciplina intrames y concentrar las propuestas de entrada/salida para el **Día 1 del próximo mes**.
"""
