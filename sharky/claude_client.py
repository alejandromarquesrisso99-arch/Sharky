"""
Cliente para la API de Claude (Anthropic).

Regla central: cuando no hay API o la llamada falla, el resultado se devuelve
marcado como `simulado=True`. Las notas que lo consumen imprimen un aviso
visible, para que nunca se confunda prosa de plantilla con razonamiento real
sobre los datos del día.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel

from sharky.config import (
    ALLOW_SIMULATED_INTELLIGENCE,
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MAX_TOKENS_INFORME,
    VAULT_PATH,
    has_live_api_key,
)
from sharky.models import (
    HealthStatus,
    MarketSnapshot,
    PortfolioValuation,
    RiskBreach,
)


class IntelligenceResult(BaseModel):
    texto: str
    simulado: bool = False
    modelo: str = ""
    error: Optional[str] = None


class ClaudeBrainClient:
    def __init__(self, api_key: Optional[str] = None, model: str = CLAUDE_MODEL):
        self.api_key = api_key if api_key is not None else ANTHROPIC_API_KEY
        self.model = model
        self.client = None
        self.is_live = False

        if has_live_api_key() or (api_key and api_key.strip()):
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                self.is_live = True
            except ImportError:
                print("[ClaudeBrain] SDK `anthropic` no instalado. Modo simulación.")
            except Exception as exc:
                print(f"[ClaudeBrain] No se pudo instanciar el SDK ({exc}). Modo simulación.")

    # ------------------------------------------------------------------
    def _get_system_prompt(self) -> str:
        prompt_file = VAULT_PATH / "00_Sistema" / "Prompt_Sistema.md"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return (
            "Eres Sharky, Chief Investment Officer de un family office autónomo. "
            "La cartera está denominada en EUR. Tu supervivencia depende de la "
            "preservación del capital y de la asignación estratégica mensual."
        )

    def _invocar(self, user_prompt: str, fallback: str) -> IntelligenceResult:
        """Llama a la API o devuelve el fallback marcado como simulado."""
        if not (self.is_live and self.client):
            if not ALLOW_SIMULATED_INTELLIGENCE:
                raise RuntimeError(
                    "No hay API de Claude disponible y SHARKY_ALLOW_SIMULATED_INTELLIGENCE=false. "
                    "Configura ANTHROPIC_API_KEY en `.env`."
                )
            return IntelligenceResult(texto=fallback, simulado=True)

        try:
            respuesta = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS_INFORME,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": user_prompt}],
            )
            texto = "".join(
                bloque.text for bloque in respuesta.content if getattr(bloque, "type", "") == "text"
            ).strip()
            if not texto:
                # Diagnóstico explícito en vez de un "no contenía texto" a secas:
                # sin esto, una respuesta cortada por max_tokens (frecuente si el
                # modelo gasta el presupuesto en razonamiento antes de llegar al
                # texto) es indistinguible en el log de un fallo real de la API.
                tipos_presentes = [
                    getattr(bloque, "type", "?") for bloque in respuesta.content
                ] or ["(vacío)"]
                pista = (
                    " -- stop_reason='max_tokens': el modelo puede estar agotando "
                    f"MAX_TOKENS_INFORME ({MAX_TOKENS_INFORME}) antes de emitir texto; "
                    "prueba a subirlo."
                    if getattr(respuesta, "stop_reason", None) == "max_tokens"
                    else ""
                )
                raise ValueError(
                    f"la respuesta de la API no contenía texto "
                    f"(stop_reason={getattr(respuesta, 'stop_reason', None)!r}, "
                    f"tipos de bloque: {tipos_presentes}){pista}"
                )
            return IntelligenceResult(texto=texto, simulado=False, modelo=self.model)
        except Exception as exc:
            if not ALLOW_SIMULATED_INTELLIGENCE:
                raise
            print(f"[ClaudeBrain] Error en la llamada a la API: {exc}. Se usa el generador simulado.")
            return IntelligenceResult(texto=fallback, simulado=True, error=str(exc))

    # ------------------------------------------------------------------
    def generate_daily_intelligence(
        self,
        health: HealthStatus,
        market_snapshots: Dict[str, MarketSnapshot],
        macro_snapshots: Dict[str, MarketSnapshot],
        valuation: Optional[PortfolioValuation] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
        active_theses_count: int = 0,
        memoria_reciente: Optional[List[Dict[str, object]]] = None,
    ) -> IntelligenceResult:
        """Informe diario de inteligencia macro, cartera y disciplina.

        `memoria_reciente` es el frontmatter de días anteriores del diario
        (ver `VaultManager.leer_memoria_diario`): sin esto, cada informe se
        redactaba sin ninguna noción de lo que ya se había dicho u
        observado antes -- cada día empezaba de cero.
        """
        incumplimientos = incumplimientos or []

        def bloque_precios(snaps: Dict[str, MarketSnapshot]) -> str:
            return "\n".join(
                f"- {s.ticker}: {s.precio_actual:,.2f} {s.divisa} ({s.cambio_diario_pct:+.2f}%)"
                + ("" if s.es_fiable else "  [DATO NO FIABLE]")
                for s in snaps.values()
            ) or "- Sin datos."

        bloque_cartera = "- Cartera no valorada en esta sesión."
        if valuation:
            filas = "\n".join(
                f"- {p.ticker} ({p.sector}): {p.valor_mercado_eur:,.2f} EUR, "
                f"{p.peso_pct:.2f}% del NAV, PnL {p.pnl_eur:+,.2f} EUR ({p.pnl_pct:+.2f}%)"
                for p in sorted(valuation.posiciones, key=lambda x: -x.valor_mercado_eur)
            )
            sectores = ", ".join(
                f"{s} {w:.1f}%"
                for s, w in sorted(valuation.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1])
            )
            bloque_cartera = (
                f"{filas}\n"
                f"- EFECTIVO: {valuation.efectivo_eur:,.2f} EUR ({valuation.peso_efectivo_pct:.2f}%)\n"
                f"- Exposición sectorial: {sectores}\n"
                f"- Cobertura de datos: {valuation.cobertura_mercado_pct:.1f}%"
            )

        bloque_incumplimientos = "\n".join(
            f"- [{b.severidad}] {b.regla}: {b.mensaje}" for b in incumplimientos
        ) or "- Ninguno: la cartera cumple todos los límites del mandato."

        bloque_memoria = self._formatear_memoria(memoria_reciente or [])

        user_prompt = f"""Es tu jornada diaria de vigilancia. No hay trading intradía.

DIVISA BASE DE LA CARTERA: EUR. Todo importe en euros.

ESTADO DE SUPERVIVENCIA:
- Estado vital: {health.estado_vital.value} (salud {health.salud_porcentaje:.1f}%)
- NAV: {health.nav_actual_eur:,.2f} EUR (máximo histórico {health.nav_maximo_historico_eur:,.2f} EUR)
- Drawdown actual: {health.drawdown_actual_pct:.2f}% | máximo: {health.drawdown_maximo_pct:.2f}%
- PnL sobre referencia: {health.pnl_total_eur:+,.2f} EUR ({health.pnl_total_pct:+.2f}%)
- Tesis activas: {active_theses_count}

MEMORIA RECIENTE (tu propio diario, no repitas lo ya dicho salvo que haya
cambiado; usa esto para notar tendencias, contradecir tu propia lectura de
hace unos días si los datos ya no la sostienen, o confirmar que una tesis se
sigue cumpliendo):
{bloque_memoria}

INDICADORES MACRO DE HOY:
{bloque_precios(macro_snapshots)}

ACTIVOS EN RADAR:
{bloque_precios(market_snapshots)}

CARTERA REAL VALORADA A MERCADO:
{bloque_cartera}

INCUMPLIMIENTOS DEL MANDATO DETECTADOS POR EL RISKGOVERNOR:
{bloque_incumplimientos}

Redacta tu informe de inteligencia para el diario, en Markdown y en español:
1. Diagnóstico del régimen de mercado y de las inercias (tecnología, energía, bonos, oro).
2. Riesgos geopolíticos relevantes para ESTA cartera concreta y sesgos que debes evitar.
3. Lectura de las posiciones: qué confirma la tesis y qué la está cuestionando.
4. Qué implican los incumplimientos anteriores para el rebalanceo del Día 1.
5. Continuidad: qué cambió respecto a la memoria reciente de arriba -- una
   tendencia que se confirma, una lectura tuya de hace días que los datos de
   hoy ya no sostienen, o una racha de incumplimientos que no se corrige.

Usa enlaces `[[Ticker]]` y `[[Sector]]`. Sé concreto y cuantitativo. No inventes
datos que no aparezcan arriba: si algo falta, dilo.
"""

        fallback = self._fallback_diario(health, valuation, incumplimientos)
        return self._invocar(user_prompt, fallback)

    @staticmethod
    def _formatear_memoria(entradas: List[Dict[str, object]]) -> str:
        """Una línea por día de diario anterior, de más antiguo a más reciente."""
        if not entradas:
            return "- Sin memoria previa disponible (primer ciclo o diario vacío)."
        lineas = []
        for meta in entradas:
            aviso_sim = " [simulado -- sin razonamiento real ese día]" if meta.get(
                "inteligencia_simulada"
            ) else ""
            lineas.append(
                f"- {meta.get('fecha', '?')}: {meta.get('estado_vital', '?')} "
                f"(salud {meta.get('salud_al_cierre', '?')}%) | "
                f"NAV {meta.get('nav_eur', '?')} EUR | "
                f"drawdown {meta.get('drawdown_actual_pct', '?')}% | "
                f"{meta.get('eventos_clave', '')}{aviso_sim}"
            )
        return "\n".join(lineas)

    @staticmethod
    def _fallback_diario(
        health: HealthStatus,
        valuation: Optional[PortfolioValuation],
        incumplimientos: List[RiskBreach],
    ) -> str:
        """Resumen determinista de los datos reales, sin análisis inventado.

        No pretende razonar: sólo expone lo que se ha medido, para que la nota
        siga siendo útil sin fingir una capacidad que no está disponible.
        """
        lineas = [
            "### 📊 Resumen determinista del día (sin análisis de Claude)",
            "",
            f"* **Estado vital:** `{health.estado_vital.value}` — salud {health.salud_porcentaje:.1f}%, "
            f"energía {health.energia_actual:.1f}/100.",
            f"* **NAV:** {health.nav_actual_eur:,.2f} € | máximo histórico {health.nav_maximo_historico_eur:,.2f} € "
            f"| drawdown {health.drawdown_actual_pct:.2f}%.",
            f"* **PnL sobre referencia:** {health.pnl_total_eur:+,.2f} € ({health.pnl_total_pct:+.2f}%).",
        ]

        if valuation:
            mejores = sorted(valuation.posiciones, key=lambda p: -p.pnl_pct)[:3]
            peores = sorted(valuation.posiciones, key=lambda p: p.pnl_pct)[:3]
            lineas.append(
                "* **Mejor comportamiento:** "
                + ", ".join(f"[[{p.ticker}]] ({p.pnl_pct:+.2f}%)" for p in mejores)
                + "."
            )
            lineas.append(
                "* **Peor comportamiento:** "
                + ", ".join(f"[[{p.ticker}]] ({p.pnl_pct:+.2f}%)" for p in peores)
                + "."
            )
            lineas.append(
                f"* **Liquidez:** {valuation.efectivo_eur:,.2f} € "
                f"({valuation.peso_efectivo_pct:.2f}% del NAV)."
            )

        if incumplimientos:
            lineas.append(f"* **Incumplimientos del mandato:** {len(incumplimientos)} activos:")
            lineas.extend(f"    * {b.mensaje}" for b in incumplimientos)
        else:
            lineas.append("* **Incumplimientos del mandato:** ninguno.")

        lineas += [
            "",
            "> Estas cifras son reales y medidas. Lo que falta aquí es la",
            "> interpretación: configura `ANTHROPIC_API_KEY` en `.env` para que el CIO",
            "> razone sobre ellas.",
        ]
        return "\n".join(lineas)

    # ------------------------------------------------------------------
    def synthesize_cio_verdict(self, health: HealthStatus, dossier: str, fallback: str) -> IntelligenceResult:
        """Resolución ejecutiva del CIO a partir del dossier departamental."""
        user_prompt = f"""Actúas como Chief Investment Officer de Sharky Capital Management.

La cartera está denominada en EUR.

ESTADO DE SUPERVIVENCIA DE LA FIRMA:
- Estado vital: {health.estado_vital.value} (salud {health.salud_porcentaje:.1f}%)
- NAV: {health.nav_actual_eur:,.2f} EUR (máximo histórico {health.nav_maximo_historico_eur:,.2f} EUR)
- Drawdown actual: {health.drawdown_actual_pct:.2f}%
- Cobertura de datos: {health.cobertura_datos_pct:.1f}%

DOSSIER DE LOS DEPARTAMENTOS:
{dossier}

Emite tu Resolución Ejecutiva en Markdown y en español:
1. Evaluación holística: dónde convergen y dónde se contradicen los departamentos.
2. Directivas innegociables, cada una con su justificación cuantitativa.
3. Posicionamiento concreto para el Rebalanceo del Día 1.

No inventes datos que no estén en el dossier.
"""
        return self._invocar(user_prompt, fallback)
