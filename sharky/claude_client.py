"""
Cliente para la API de Claude (Anthropic).

Regla central: cuando no hay API o la llamada falla, el resultado se devuelve
marcado como `simulado=True`. Las notas que lo consumen imprimen un aviso
visible, para que nunca se confunda prosa de plantilla con razonamiento real
sobre los datos del día.

Cadencia de razonamiento (ver los perfiles en `config.py`):

  * Diario  (`generate_daily_intelligence`): sólo posiciones, precios, valor
    de mercado y cumplimiento de las normas.
  * Semanal (`sharky.news_scanner.NewsScanner`): noticias de la cartera con
    el contexto de los últimos 7 controles diarios.
  * Mensual (`generate_monthly_study`): estudio completo y reevaluación de
    posiciones con todo el contexto del mes.

Fuera de esa cadencia, y sólo a demanda, el explorador de mercado
(`sharky.market_explorer`) busca candidatos nuevos con el modelo más capaz
disponible. No vive aquí porque no razona sobre la cartera: la usa como
contexto para no volver a proponer lo que ya tienes.

Cada informe termina con una sección de conclusión (`## Conclusión del día`,
`de la semana`, `del mes`) que se guarda en el frontmatter de su nota y es
lo único que el nivel siguiente relee: así el contexto de cada llamada queda
acotado en vez de crecer con cada nota nueva.
"""

import re
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from sharky.config import (
    ALLOW_SIMULATED_INTELLIGENCE,
    ANTHROPIC_API_KEY,
    API_KEY_PLACEHOLDERS,
    CLAUDE_MODEL,
    EFFORT_DIARIO,
    EFFORT_MENSUAL,
    MAX_TOKENS_COMITE,
    MAX_TOKENS_DIARIO,
    MAX_TOKENS_MENSUAL,
    UMBRAL_MOVIMIENTO_VIGILANCIA_PCT,
    VAULT_PATH,
    has_live_api_key,
)
from sharky.models import (
    HealthStatus,
    InvestmentThesis,
    MarketSnapshot,
    MonthlyRebalanceReport,
    PortfolioValuation,
    RiskBreach,
)

# Por encima de este `max_tokens` el SDK rechaza peticiones sin streaming
# (estima que tardarían más de 10 minutos). Margen por debajo del umbral real.
MAX_TOKENS_SIN_STREAMING = 20000

CONCLUSION_DIA = "Conclusión del día"
CONCLUSION_SEMANA = "Conclusión de la semana"
CONCLUSION_MES = "Conclusión del mes"
# El explorador de mercado (`sharky.market_explorer`) no pertenece a la
# cadencia diaria/semanal/mensual -- se lanza a demanda -- pero cierra su
# informe igual que los demás, para que la app pueda enseñar su conclusión
# en la misma tarjeta que el resto.
CONCLUSION_EXPLORACION = "Conclusión de la exploración"


def extraer_conclusion(texto: str, titulo: str) -> str:
    """Cuerpo de la última sección `## {titulo}` del texto, o "" si no está.

    Tolera variaciones menores del modelo (nivel de encabezado, mayúsculas,
    tilde, dos puntos finales). Se toma la última aparición: la conclusión
    va siempre al final del informe.
    """
    patron_titulo = re.escape(titulo).replace("ó", "[oó]").replace("í", "[ií]")
    patron = re.compile(rf"^#{{1,6}}\s*{patron_titulo}\s*:?\s*$", re.IGNORECASE | re.MULTILINE)
    coincidencias = list(patron.finditer(texto or ""))
    if not coincidencias:
        return ""
    resto = texto[coincidencias[-1].end():]
    siguiente = re.search(r"^#{1,6}\s", resto, re.MULTILINE)
    return (resto[: siguiente.start()] if siguiente else resto).strip()


class IntelligenceResult(BaseModel):
    texto: str
    simulado: bool = False
    modelo: str = ""
    error: Optional[str] = None
    # Resumen que relee el nivel siguiente (semanal o mensual). Nunca vacío
    # en los informes diario y mensual: si el modelo no lo da, se construye
    # uno determinista con los datos medidos.
    conclusion: str = ""


class ClaudeBrainClient:
    def __init__(self, api_key: Optional[str] = None, model: str = CLAUDE_MODEL):
        self.api_key = api_key if api_key is not None else ANTHROPIC_API_KEY
        self.model = model
        self.client = None
        self.is_live = False

        # Una clave explícita (aunque sea vacía) manda sobre la del `.env`:
        # `ClaudeBrainClient(api_key="")` no debe acabar llamando a la API
        # real con la clave del entorno (lo hacían los tests).
        if api_key is None:
            tiene_clave = has_live_api_key()
        else:
            tiene_clave = api_key.strip() not in API_KEY_PLACEHOLDERS

        if tiene_clave:
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

    def _invocar(
        self,
        user_prompt: str,
        fallback: str,
        max_tokens: int = MAX_TOKENS_DIARIO,
        effort: str = EFFORT_DIARIO,
        variable_presupuesto: str = "SHARKY_MAX_TOKENS_DIARIO",
    ) -> IntelligenceResult:
        """Llama a la API o devuelve el fallback marcado como simulado.

        `variable_presupuesto` es la variable de `.env` que hay que subir si
        la respuesta se corta por `max_tokens`: cada perfil tiene la suya.
        """
        if not (self.is_live and self.client):
            if not ALLOW_SIMULATED_INTELLIGENCE:
                raise RuntimeError(
                    "No hay API de Claude disponible y SHARKY_ALLOW_SIMULATED_INTELLIGENCE=false. "
                    "Configura ANTHROPIC_API_KEY en `.env`."
                )
            return IntelligenceResult(texto=fallback, simulado=True)

        parametros: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": self._get_system_prompt(),
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if effort:
            parametros["output_config"] = {"effort": effort}

        try:
            if max_tokens > MAX_TOKENS_SIN_STREAMING:
                with self.client.messages.stream(**parametros) as stream:
                    respuesta = stream.get_final_message()
            else:
                respuesta = self.client.messages.create(**parametros)
            # `getattr` y no `bloque.text`: el contenido es una unión de tipos
            # de bloque y sólo los de texto tienen `.text`.
            texto = "".join(
                str(getattr(bloque, "text", ""))
                for bloque in respuesta.content
                if getattr(bloque, "type", "") == "text"
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
                    f"{variable_presupuesto} ({max_tokens}) antes de emitir texto; "
                    "prueba a subirlo o a bajar el effort."
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
    # Bloques de datos compartidos por los prompts
    # ------------------------------------------------------------------
    @staticmethod
    def _bloque_cartera(
        valuation: Optional[PortfolioValuation],
        variaciones: Optional[Dict[str, float]] = None,
    ) -> str:
        """Una línea por posición: precio, valor, peso, PnL y variación."""
        if not valuation:
            return "- Cartera no valorada en esta sesión."
        variaciones = variaciones or {}
        filas = []
        for p in sorted(valuation.posiciones, key=lambda x: -x.valor_mercado_eur):
            variacion = variaciones.get(p.ticker)
            txt_variacion = (
                f", {variacion:+.2f}% desde el último control" if variacion is not None else ""
            )
            fiable = "" if p.fuente_precio.es_fiable else "  [PRECIO NO FIABLE]"
            filas.append(
                f"- {p.ticker} ({p.sector or 'sin sector'}): {p.precio_cotizacion:,.2f} "
                f"{p.divisa_cotizacion} | valor {p.valor_mercado_eur:,.2f} EUR | "
                f"{p.peso_pct:.2f}% del NAV | PnL {p.pnl_eur:+,.2f} EUR ({p.pnl_pct:+.2f}%)"
                f"{txt_variacion}{fiable}"
            )
        sectores = ", ".join(
            f"{s} {w:.1f}%"
            for s, w in sorted(valuation.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1])
        )
        filas += [
            f"- EFECTIVO: {valuation.efectivo_eur:,.2f} EUR ({valuation.peso_efectivo_pct:.2f}%)",
            f"- Exposición sectorial: {sectores or 'sin datos'}",
            f"- Cobertura de datos: {valuation.cobertura_mercado_pct:.1f}%",
        ]
        return "\n".join(filas)

    @staticmethod
    def _bloque_incumplimientos(incumplimientos: List[RiskBreach]) -> str:
        return "\n".join(
            f"- [{b.severidad}] {b.regla}: {b.mensaje}"
            + (f" -> {b.accion_correctiva}" if b.accion_correctiva else "")
            for b in incumplimientos
        ) or "- Ninguno: la cartera cumple todos los límites del mandato."

    @staticmethod
    def _bloque_estado(health: HealthStatus) -> str:
        return (
            f"- Estado vital: {health.estado_vital.value} (salud {health.salud_porcentaje:.1f}%)\n"
            f"- NAV: {health.nav_actual_eur:,.2f} EUR (máximo histórico {health.nav_maximo_historico_eur:,.2f} EUR)\n"
            f"- Drawdown actual: {health.drawdown_actual_pct:.2f}% | máximo: {health.drawdown_maximo_pct:.2f}%\n"
            f"- PnL sobre referencia: {health.pnl_total_eur:+,.2f} EUR ({health.pnl_total_pct:+.2f}%)"
        )

    @staticmethod
    def movimientos_fuertes(variaciones: Dict[str, float]) -> List[str]:
        """Tickers cuya variación desde el último control supera el umbral."""
        return sorted(
            t for t, v in variaciones.items() if abs(v) >= UMBRAL_MOVIMIENTO_VIGILANCIA_PCT
        )

    # ------------------------------------------------------------------
    # Nivel diario
    # ------------------------------------------------------------------
    def generate_daily_intelligence(
        self,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
        avisos_niveles: Optional[List[str]] = None,
        variaciones: Optional[Dict[str, float]] = None,
    ) -> IntelligenceResult:
        """Control diario: posiciones, precios, valor de mercado y normas.

        Deliberadamente estrecho. Macro, geopolítica y noticias no entran
        aquí: el escaneo semanal y el estudio mensual se encargan de eso con
        un contexto mejor. Lo que este informe deja para ellos es su sección
        `## Conclusión del día`.

        `variaciones` es el % de cambio del precio de cada posición desde el
        último control diario (ver `SharkyAgent._variaciones_desde_ultimo_control`).
        """
        incumplimientos = incumplimientos or []
        avisos_niveles = avisos_niveles or []
        variaciones = variaciones or {}

        fuertes = self.movimientos_fuertes(variaciones)
        bloque_fuertes = (
            "\n".join(f"- {t}: {variaciones[t]:+.2f}%" for t in fuertes)
            or f"- Ninguna posición se ha movido más de ±{UMBRAL_MOVIMIENTO_VIGILANCIA_PCT:g}%."
        )
        bloque_niveles = "\n".join(f"- {a}" for a in avisos_niveles) or "- Ningún nivel alcanzado."

        user_prompt = f"""Es tu control diario de la cartera. Hoy NO toca análisis macro,
geopolítico ni de noticias: eso lo cubren el escaneo semanal y el estudio
mensual. Céntrate sólo en las posiciones abiertas y en el mandato.

DIVISA BASE DE LA CARTERA: EUR.

ESTADO DE SUPERVIVENCIA:
{self._bloque_estado(health)}

POSICIONES VALORADAS A MERCADO:
{self._bloque_cartera(valuation, variaciones)}

MOVIMIENTOS FUERTES DESDE EL ÚLTIMO CONTROL (umbral ±{UMBRAL_MOVIMIENTO_VIGILANCIA_PCT:g}%):
{bloque_fuertes}

NIVELES DE LAS TESIS (stop-loss / take-profit):
{bloque_niveles}

INCUMPLIMIENTOS DEL MANDATO DETECTADOS POR EL RISKGOVERNOR:
{self._bloque_incumplimientos(incumplimientos)}

Redacta el control del día en Markdown y en español, breve (unas 300
palabras como mucho):
1. Posiciones: qué se ha movido y cuánto. Sólo lo relevante, sin repasar
   una a una las que no cambian nada.
2. Cumplimiento del mandato: qué norma se incumple, por cuánto y qué exige
   (salida obligatoria por stop-loss hoy, o corrección en el Rebalanceo del
   Día 1). Si todo cumple, dilo en una línea.
3. Termina SIEMPRE con una sección `## {CONCLUSION_DIA}` de 1 a 3 viñetas: lo
   que el escaneo semanal de noticias y el estudio mensual deben saber de
   hoy (qué vigilar y por qué).

Usa enlaces `[[Ticker]]`. Sé concreto y cuantitativo. No inventes datos que
no aparezcan arriba: si algo falta o un precio no es fiable, dilo.
"""

        fallback = self._fallback_diario(health, valuation, incumplimientos)
        resultado = self._invocar(user_prompt, fallback)
        resultado.conclusion = extraer_conclusion(resultado.texto, CONCLUSION_DIA) or (
            self._conclusion_diaria_determinista(
                health, incumplimientos, avisos_niveles, variaciones
            )
        )
        return resultado

    @classmethod
    def _conclusion_diaria_determinista(
        cls,
        health: HealthStatus,
        incumplimientos: List[RiskBreach],
        avisos_niveles: List[str],
        variaciones: Dict[str, float],
    ) -> str:
        """Conclusión medida, para cuando Claude no la da (o no hay API)."""
        lineas = [
            f"- NAV {health.nav_actual_eur:,.2f} EUR, drawdown {health.drawdown_actual_pct:.2f}%."
        ]
        if incumplimientos:
            lineas.append(
                f"- {len(incumplimientos)} incumplimiento(s): "
                + "; ".join(f"{b.regla} ({b.sujeto})" if b.sujeto else b.regla for b in incumplimientos)
                + "."
            )
        fuertes = cls.movimientos_fuertes(variaciones)
        if fuertes:
            lineas.append(
                "- Movimientos fuertes: "
                + ", ".join(f"{t} {variaciones[t]:+.2f}%" for t in fuertes)
                + "."
            )
        if avisos_niveles:
            lineas.append(f"- {len(avisos_niveles)} nivel(es) de tesis alcanzado(s).")
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
    # Contexto acumulado (lo que releen los niveles semanal y mensual)
    # ------------------------------------------------------------------
    @staticmethod
    def _formatear_memoria(entradas: List[Dict[str, object]]) -> str:
        """Un bloque por control diario anterior, de más antiguo a más reciente.

        Cifras del día más su conclusión (`conclusion_ia` del frontmatter).
        Los diarios anteriores a 2026-09-18 no tienen conclusión: se usa
        `eventos_clave` en su lugar.
        """
        if not entradas:
            return "- Sin controles diarios disponibles en este periodo."
        bloques = []
        for meta in entradas:
            aviso_sim = " [simulado -- sin razonamiento real ese día]" if meta.get(
                "inteligencia_simulada"
            ) else ""
            vigilar = meta.get("posiciones_a_vigilar")
            txt_vigilar = (
                f" | a vigilar: {', '.join(map(str, vigilar))}"
                if isinstance(vigilar, list) and vigilar
                else ""
            )
            cabecera = (
                f"- {meta.get('fecha', '?')}: {meta.get('estado_vital', '?')} "
                f"(salud {meta.get('salud_al_cierre', '?')}%) | "
                f"NAV {meta.get('nav_eur', '?')} EUR | "
                f"drawdown {meta.get('drawdown_actual_pct', '?')}%{txt_vigilar}{aviso_sim}"
            )
            conclusion = str(meta.get("conclusion_ia") or meta.get("eventos_clave") or "").strip()
            if conclusion:
                cabecera += "\n" + "\n".join(
                    f"    {linea}" for linea in conclusion.splitlines() if linea.strip()
                )
            bloques.append(cabecera)
        return "\n".join(bloques)

    @staticmethod
    def _formatear_noticias(noticias: Optional[Dict[str, Any]]) -> str:
        """Resumen del último escaneo semanal, con aviso si está desactualizado.

        `noticias` es el dict que devuelve
        `VaultManager.leer_ultimas_noticias_semanales`. Lo usa el Comité de
        Inversión; el estudio mensual usa `_formatear_noticias_del_mes`.
        """
        if not noticias:
            return "- Sin escaneo de noticias todavía (ejecuta `sharky noticias`)."
        if not noticias.get("disponible", True):
            return (
                f"- Último intento ({noticias['fecha']}) no disponible: sin API de "
                "Claude en vivo esa semana, no se buscó nada."
            )
        antiguedad = (date.today() - noticias["fecha"]).days
        aviso = f" [⚠️ tiene {antiguedad} días: puede estar desactualizado]" if antiguedad > 10 else ""
        return f"(Escaneo del {noticias['fecha']}{aviso})\n{noticias['resumen']}"

    @staticmethod
    def _formatear_noticias_del_mes(escaneos: List[Dict[str, Any]]) -> str:
        """Todos los escaneos semanales del periodo, de más antiguo a más reciente."""
        if not escaneos:
            return "- Sin escaneos de noticias este mes."
        bloques = []
        for e in escaneos:
            if not e.get("disponible", True):
                bloques.append(f"#### Semana del {e['fecha']}\n- Escaneo no disponible esa semana.")
                continue
            bloques.append(f"#### Semana del {e['fecha']}\n{e['resumen']}")
        return "\n\n".join(bloques)

    # ------------------------------------------------------------------
    # Nivel mensual
    # ------------------------------------------------------------------
    def generate_monthly_study(
        self,
        mes: str,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation],
        incumplimientos: List[RiskBreach],
        tesis: List[InvestmentThesis],
        plan: MonthlyRebalanceReport,
        macro_snapshots: Dict[str, MarketSnapshot],
        memoria_mes: List[Dict[str, object]],
        noticias_mes: List[Dict[str, Any]],
        conclusion_mes_anterior: str = "",
    ) -> IntelligenceResult:
        """Estudio completo de la cartera y reevaluación de posiciones.

        Es el único momento del mes en que se reevalúan posiciones: el
        mandato prohíbe operar por impulso intrames. Recibe el plan del
        motor de rebalanceo (determinista, respeta los límites) para que
        Claude lo contraste en vez de proponer en el vacío.
        """
        bloque_tesis = "\n".join(
            f"- {t.ticker} ({t.empresa}): entrada {t.precio_entrada:,.2f} {t.divisa}, "
            f"stop {t.stop_loss:,.2f}, target {t.target_precio:,.2f}, convicción {t.conviccion}/10"
            + (f". Racional: {t.racional.strip()[:300]}" if t.racional else "")
            for t in tesis
        ) or "- Sin tesis activas."

        bloque_plan = "\n".join(
            f"- {p.ticker}: {p.accion.value} | peso {p.peso_actual_pct:.2f}% -> "
            f"{p.peso_objetivo_pct:.2f}% | delta {p.delta_eur:+,.2f} EUR | {p.motivo}"
            for p in plan.propuestas
        ) or "- El motor no propone cambios."

        bloque_macro = "\n".join(
            f"- {s.ticker}: {s.precio_actual:,.2f} {s.divisa} ({s.cambio_diario_pct:+.2f}% hoy)"
            + ("" if s.es_fiable else "  [DATO NO FIABLE]")
            for s in macro_snapshots.values()
        ) or "- Sin datos."

        user_prompt = f"""Es el ESTUDIO MENSUAL de la cartera ({mes}). Es la única ocasión del
mes en la que se reevalúan posiciones: el mandato prohíbe operar por
impulso intrames. Tienes el contexto que ha ido generando el propio Sharky
durante el mes: los controles diarios y los escaneos semanales de noticias.

DIVISA BASE DE LA CARTERA: EUR.

ESTADO DE SUPERVIVENCIA:
{self._bloque_estado(health)}

CARTERA VALORADA A MERCADO HOY:
{self._bloque_cartera(valuation)}

TESIS ACTIVAS:
{bloque_tesis}

INCUMPLIMIENTOS DEL MANDATO:
{self._bloque_incumplimientos(incumplimientos)}

PLAN DEL MOTOR DE REBALANCEO (determinista, respeta los límites del mandato;
caja objetivo {plan.peso_cash_objetivo_pct:.1f}% = {plan.cash_objetivo_eur:,.2f} EUR):
{bloque_plan}

INDICADORES MACRO (hoy):
{bloque_macro}

CONCLUSIÓN DEL ESTUDIO DEL MES ANTERIOR:
{conclusion_mes_anterior.strip() or "- No hay estudio anterior."}

CONTEXTO DEL MES -- CONTROLES DIARIOS:
{self._formatear_memoria(memoria_mes)}

CONTEXTO DEL MES -- ESCANEOS SEMANALES DE NOTICIAS:
{self._formatear_noticias_del_mes(noticias_mes)}

Redacta el estudio mensual en Markdown y en español:
1. Balance del mes: evolución del NAV y del drawdown, qué posiciones
   aportaron y cuáles restaron, qué incumplimientos persistieron.
2. Régimen de mercado y riesgos (macro, geopolítica) sólo en lo que afecte
   a ESTA cartera.
3. Revisión posición a posición, en una tabla: veredicto MANTENER / AMPLIAR
   / REDUCIR / CERRAR y justificación cuantitativa apoyada en el contexto
   del mes (tesis, noticias, niveles, movimientos). Si la tesis de una
   posición ya no se sostiene, dilo claramente.
4. Contraste con el plan del motor de rebalanceo: dónde coincides, dónde
   discrepas y por qué. Tus propuestas deben respetar los límites del
   mandato; si alguna no lo hace, márcala como tal.
5. Qué vigilar el mes que viene: catalizadores y riesgos por posición.
6. Termina SIEMPRE con una sección `## {CONCLUSION_MES}` de 3 a 5 viñetas con
   las decisiones del mes: la leerá el estudio del mes siguiente.

Usa enlaces `[[Ticker]]` y `[[Sector]]`. Sé concreto y cuantitativo. No
inventes datos que no aparezcan arriba: si falta contexto de alguna semana
(escaneo no disponible, días simulados), dilo y tenlo en cuenta al decidir.
"""

        fallback = self._fallback_mensual(mes, health, plan)
        resultado = self._invocar(
            user_prompt,
            fallback,
            max_tokens=MAX_TOKENS_MENSUAL,
            effort=EFFORT_MENSUAL,
            variable_presupuesto="SHARKY_MAX_TOKENS_MENSUAL",
        )
        resultado.conclusion = extraer_conclusion(resultado.texto, CONCLUSION_MES) or (
            f"- Estudio de {mes} sin análisis de Claude: se aplica el plan del motor "
            f"de rebalanceo ({len(plan.propuestas)} propuesta(s))."
        )
        return resultado

    @staticmethod
    def _fallback_mensual(mes: str, health: HealthStatus, plan: MonthlyRebalanceReport) -> str:
        """Resumen determinista del mes: estado y plan del motor, sin veredictos."""
        lineas = [
            f"### 📊 Estudio de {mes} sin análisis de Claude",
            "",
            f"* **Estado vital:** `{health.estado_vital.value}` — NAV {health.nav_actual_eur:,.2f} €, "
            f"drawdown {health.drawdown_actual_pct:.2f}%.",
            f"* **Plan del motor de rebalanceo:** {len(plan.propuestas)} propuesta(s), caja objetivo "
            f"{plan.peso_cash_objetivo_pct:.1f}%.",
        ]
        lineas.extend(
            f"    * {p.ticker}: {p.accion.value} ({p.peso_actual_pct:.2f}% -> {p.peso_objetivo_pct:.2f}%)"
            for p in plan.propuestas
        )
        lineas += [
            "",
            "> Sin reevaluación de posiciones: nadie ha contrastado el plan con el",
            "> contexto del mes. Configura `ANTHROPIC_API_KEY` en `.env` y repite",
            "> `sharky monthly`.",
        ]
        return "\n".join(lineas)

    # ------------------------------------------------------------------
    # Comité de inversión (a demanda)
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
        return self._invocar(
            user_prompt,
            fallback,
            max_tokens=MAX_TOKENS_COMITE,
            effort=EFFORT_MENSUAL,
            variable_presupuesto="SHARKY_MAX_TOKENS_COMITE",
        )
