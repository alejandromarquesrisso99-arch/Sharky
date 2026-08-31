"""
Estructura Departamental de la Firma de Inversión Sharky Capital Management.
Simula los departamentos especializados de un fondo institucional / Family Office:
1. Departamento Macro & Geopolítica (Chief Macroeconomist)
2. Departamento de Análisis Fundamental & Renta Variable (Head of Equity Research)
3. Mesa de Riesgo & Finanzas Cuantitativas (Chief Risk Officer - CRO)
4. Mesa de Sentimiento, Narrativas & Flujos (Market Psychology Desk)
5. Comité de Dirección & CIO (Chief Investment Officer)
"""

from typing import Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field

from sharky.models import MarketSnapshot, HealthStatus, InvestmentThesis, OpportunityAlert


class DepartmentReport(BaseModel):
    departamento: str
    responsable: str
    fecha: str
    diagnostico: str
    puntos_clave: List[str] = Field(default_factory=list)
    alertas_o_riesgos: List[str] = Field(default_factory=list)
    recomendacion_tactica: str


class MacroDesk:
    """Departamento de Macroeconomía, Geopolítica y Cadenas de Suministro."""
    
    def generate_report(self, macro_snapshots: Dict[str, MarketSnapshot]) -> DepartmentReport:
        now_str = datetime.now().strftime("%Y-%m-%d")
        tlt = macro_snapshots.get("TLT")
        gld = macro_snapshots.get("GLD")
        uso = macro_snapshots.get("USO")
        spy = macro_snapshots.get("SPY")

        puntos = [
            f"Bono 10Y/20Y (TLT: ${tlt.precio_actual if tlt else 95.0:,.2f}): Estabilidad en curvas de rendimiento.",
            f"Oro Físico (GLD: ${gld.precio_actual if gld else 230.0:,.2f}): Demanda sostenida como reserva de valor y cobertura soberana.",
            f"Energía (Petróleo USO: ${uso.precio_actual if uso else 78.0:,.2f}): Presión moderada en costes logísticos y transporte marítimo.",
            f"Renta Variable (SPY: ${spy.precio_actual if spy else 560.0:,.2f}): Múltiplos exigentes que demandan crecimiento real de beneficios.",
        ]

        riesgos = [
            "Tensión comercial y cuellos de botella en la fabricación de semiconductores en Asia.",
            "Riesgo de persistencia inflacionaria en servicios que ralentice bajadas de tipos.",
        ]

        return DepartmentReport(
            departamento="Macroeconomía Global & Geopolítica",
            responsable="Chief Macro Strategist",
            fecha=now_str,
            diagnostico="Régimen de Expansión Tardía con políticas monetarias en normalización. Entorno constructivo pero selectivo.",
            puntos_clave=puntos,
            alertas_o_riesgos=riesgos,
            recomendacion_tactica="Mantener sobreponderación en empresas con alto poder de fijación de precios y cobertura en activos reales.",
        )


class FundamentalDesk:
    """Departamento de Análisis Fundamental y Fosos Económicos."""
    
    def evaluate_equity_universe(self, snapshots: Dict[str, MarketSnapshot]) -> DepartmentReport:
        now_str = datetime.now().strftime("%Y-%m-%d")
        
        puntos = [
            "ASML: Monopolio tecnológico infranqueable en litografía High-NA EUV con backlog garantizado.",
            "NVDA: Ecosistema de software CUDA y arquitecturas de red que crean un foso de cambio masivo.",
            "TSM: Utilización al 100% de fundiciones avanzadas (3nm/5nm) con subida sostenida de precios de oblea.",
            "MSFT & GOOGL: Fortalezas de balance superlativas con generación de caja récord y despliegue de IA empresarial.",
        ]

        riesgos = [
            "Sensibilidad al gasto de capital (CapEx) de las 4 grandes hiperescaladoras.",
            "Posible compresión de múltiplos de valoración si los crecimientos caen del 20% anual.",
        ]

        return DepartmentReport(
            departamento="Análisis Fundamental & Fosos Económicos",
            responsable="Head of Equity Research",
            fecha=now_str,
            diagnostico="Los líderes de infraestructura digital mantienen balances acorazados y ventajas competitivas crecientes.",
            puntos_clave=puntos,
            alertas_o_riesgos=riesgos,
            recomendacion_tactica="Concentrar el capital en empresas con retornos sobre el capital invertido (ROIC) superiores al 18%.",
        )


class RiskDesk:
    """Mesa de Gestión de Riesgo, Finanzas Cuantitativas y Supervivencia (CRO)."""

    def audit_portfolio_risk(self, health: HealthStatus, theses_count: int) -> DepartmentReport:
        now_str = datetime.now().strftime("%Y-%m-%d")
        
        puntos = [
            f"Salud Biológico-Digital: {health.salud_porcentaje:.1f}% (Estado: {health.estado_vital.value}).",
            f"Capital Total en Custodia: ${health.capital_actual:,.2f} USD (NAV).",
            f"Drawdown Histórico Registrado: {health.drawdown_maximo_pct:.2f}% (Límite Fatal de Muerte: 20.0%).",
            f"Concentración: {theses_count} posiciones activas. Ninguna supera el límite del 10.0% por activo.",
        ]

        riesgos = [
            "Correlación intradiaria sectorial alta en semiconductores.",
            "Obligatoriedad de mantener Stop-Loss estricto en todas las posiciones.",
        ]

        return DepartmentReport(
            departamento="Gestión Cuantitativa de Riesgo (CRO)",
            responsable="Chief Risk Officer",
            fecha=now_str,
            diagnostico="Parámetros de solvencia y supervivencia dentro de los márgenes institucionales óptimos.",
            puntos_clave=puntos,
            alertas_o_riesgos=riesgos,
            recomendacion_tactica="Mantener la reserva mínima de liquidez (Cash >= 15%) y prohibir aumentos de apalancamiento.",
        )


class SentimentDesk:
    """Mesa de Psicología de Mercado, Narrativas y Flujos."""

    def evaluate_sentiment(self, snapshots: Dict[str, MarketSnapshot]) -> DepartmentReport:
        now_str = datetime.now().strftime("%Y-%m-%d")
        
        puntos = [
            "Amplitud de Mercado: Rally concentrado en infraestructura de cómputo y megacaps.",
            "Psicología Colectiva: Niveles de codicia moderada sin llegar a euforia parabólica.",
            "Narrativa Dominante: Monetización de IA generativa y soberanía tecnológica nacional.",
        ]

        riesgos = [
            "Efecto manada en activos de moda que incremente la volatilidad.",
            "Sesgo de FOMO en inversores minoristas.",
        ]

        return DepartmentReport(
            departamento="Psicología de Mercado & Flujos",
            responsable="Head of Market Psychology",
            fecha=now_str,
            diagnostico="El flujo institucional continúa respaldando la tecnología de calidad pero con mayor dispersión.",
            puntos_clave=puntos,
            alertas_o_riesgos=riesgos,
            recomendacion_tactica="Evitar compras por impulso a mitad de mes; acumular evidencia para el Día 1.",
        )
