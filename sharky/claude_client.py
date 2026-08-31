"""
Cliente y Conector para la API de Claude (Anthropic).
Incluye modo real con prompts estratégicos macro/geopolítica y modo simulación enriquecido.
"""

from typing import Dict, Any, List, Optional
import os
from sharky.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, VAULT_PATH
from sharky.models import HealthStatus, MarketSnapshot, MonthlyRebalanceReport


class ClaudeBrainClient:
    def __init__(self, api_key: Optional[str] = None, model: str = CLAUDE_MODEL):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.model = model
        self.client = None
        self.is_live = False

        if self.api_key and self.api_key != "TU_ANTHROPIC_API_KEY_AQUI":
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                self.is_live = True
            except Exception as e:
                print(f"[ClaudeBrain] Aviso: No se pudo instanciar Anthropic SDK ({e}). Usando modo simulación.")
                self.is_live = False

    def _get_system_prompt(self) -> str:
        """Lee el prompt del sistema desde la bóveda de Obsidian."""
        prompt_file = VAULT_PATH / "00_Sistema" / "Prompt_Sistema.md"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return (
            "Eres Sharky, un estratega macro y gestor de carteras cuya supervivencia "
            "depende de la asignación de cartera mensual y el rigor diario sin sobreoperar."
        )

    def generate_daily_intelligence(
        self,
        health: HealthStatus,
        market_snapshots: Dict[str, MarketSnapshot],
        macro_snapshots: Dict[str, MarketSnapshot],
        active_theses_count: int,
    ) -> str:
        """Genera el informe diario de inteligencia (Macro, Geopolítica, Inercias, Tesis)."""
        if self.is_live and self.client:
            try:
                market_text = "\n".join([
                    f"- {s.ticker}: ${s.precio_actual:,.2f} ({'+' if s.cambio_diario_pct >= 0 else ''}{s.cambio_diario_pct}%)"
                    for s in market_snapshots.values()
                ])
                macro_text = "\n".join([
                    f"- {s.ticker}: ${s.precio_actual:,.2f} ({'+' if s.cambio_diario_pct >= 0 else ''}{s.cambio_diario_pct}%)"
                    for s in macro_snapshots.values()
                ])

                user_prompt = f"""
Eres Sharky en tu jornada diaria de vigilancia (sin trading intradía).

ESTADO DE LA CARTERA:
- Salud: {health.salud_porcentaje:.1f}% ({health.estado_vital.value})
- Capital Total: ${health.capital_actual:,.2f} USD
- PnL Total: ${health.pnl_total_usd:,.2f} ({health.pnl_total_pct:.2f}%)
- Tesis Activas: {active_theses_count}

INDICADORES MACRO Y MERCADO HOY:
{macro_text}

ACTIVOS EN RADAR:
{market_text}

Genera tu informe de inteligencia para el diario:
1. Diagnóstico del tono del mercado e inercias (Tech, Energía, Bonos, Oro).
2. Riesgos geopolíticos y sesgos que debes evitar.
3. Evaluación de las posiciones en cartera (confirmación de que no hay stop-loss violado).
4. Preparación mental para el próximo rebalanceo mensual (Día 1).
Formato Markdown con enlaces [[Ticker]] y [[Sectores]].
"""
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1500,
                    system=self._get_system_prompt(),
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text
            except Exception as e:
                print(f"[ClaudeBrain] Error en llamada API: {e}. Usando generador simulado.")

        # Modo Simulación cuando aún no hay API key conectada
        return f"""### 🌐 Resumen de Inteligencia Diaria (Modo Simulación Sharky)

Hoy se ha realizado el seguimiento de los principales índices macro ([[SPY]], [[QQQ]], [[TLT]], [[GLD]]) y de la cesta tecnológica ([[NVDA]], [[ASML]], [[MSFT]], [[TSM]]).

* **Régimen Macro:** Los tipos a largo plazo y el dólar muestran estabilidad, permitiendo consolidación en múltiplos de renta variable.
* **Geopolítica y Cadena de Suministro:** Se mantiene la vigilancia sobre la cadena asiática de semiconductores ([[Semiconductores]]).
* **Disciplina Operativa:** No se efectúan compras ni ventas hoy. Las posiciones activas se mantienen protegidas con sus correspondientes `Stop Loss`.
* **Próximo Hito:** Todos los datos se están archivando para generar la lista definitiva de compra/venta el **Día 1 del próximo mes**.

> *(Aviso: Conecta tu `ANTHROPIC_API_KEY` en `.env` para obtener el razonamiento completo generado en vivo por Claude).*
"""
