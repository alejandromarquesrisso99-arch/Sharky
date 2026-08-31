"""
Cliente y Conector para la API de Claude (Anthropic).
Incluye modo real mediante 'anthropic' y modo simulado para desarrollo/pruebas sin API key.
"""

from typing import Dict, Any, List, Optional
import os
from sharky.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, VAULT_PATH
from sharky.models import HealthStatus, MarketSnapshot


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
            "Eres Sharky, un cerebro de inversión cuya supervivencia depende de generar "
            "beneficios consistentes y respetar estrictamente la gestión de riesgo."
        )

    def generate_daily_reflection(
        self,
        health: HealthStatus,
        market_snapshots: Dict[str, MarketSnapshot],
        active_theses_count: int,
    ) -> str:
        """Genera la reflexión de cierre de jornada y autocrítica del cerebro."""
        if self.is_live and self.client:
            try:
                market_summary_lines = [
                    f"- {s.ticker}: ${s.precio_actual:,.2f} ({'+' if s.cambio_diario_pct >= 0 else ''}{s.cambio_diario_pct}%)"
                    for s in market_snapshots.values()
                ]
                market_text = "\n".join(market_summary_lines)

                user_prompt = f"""
Estado Vital Actual:
- Estado: {health.estado_vital.value}
- Salud: {health.salud_porcentaje:.1f}%
- Energía: {health.energia_actual:.1f}/100
- Capital: ${health.capital_actual:,.2f}
- PnL Total: ${health.pnl_total_usd:,.2f} ({health.pnl_total_pct:.2f}%)
- Tesis Activas: {active_theses_count}

Datos de Mercado del Día:
{market_text}

Por favor, genera tu entrada de diario para '05_Diario_Reflexion'. 
Recuerda tu instinto de supervivencia, evalúa los movimientos del mercado y redacta tu autocrítica.
Formato Markdown con enlaces tipo [[Ticker]] y [[Sectores]].
"""
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1500,
                    system=self._get_system_prompt(),
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return response.content[0].text
            except Exception as e:
                print(f"[ClaudeBrain] Error en llamada API a Claude: {e}. Recurriendo a generador local.")

        # Modo Simulación cuando aún no hay API key configurada
        tickers_str = ", ".join([f"[[{t}]]" for t in market_snapshots.keys()])
        return f"""### 📊 Análisis de la Jornada (Modo Simulación Sharky)

Hoy he monitoreado el comportamiento de {tickers_str}. La volatilidad del mercado se mantiene dentro de rangos operativos aceptables.

* **Salud Actual:** `{health.salud_porcentaje:.1f}%` ({health.estado_vital.value})
* **Capital Bajo Gestión:** `${health.capital_actual:,.2f}`
* **Tesis en Vigilancia:** `{active_theses_count}` posición(es) activa(s).

> **Aviso de Conexión:** Este análisis fue generado por el motor de respaldo local. 
> Cuando configures tu `ANTHROPIC_API_KEY` en el archivo `.env`, las reflexiones, tesis y decisiones serán orquestadas directamente por **Claude 3.7 Sonnet**.
"""

    def analyze_new_thesis(self, ticker: str, snapshot: MarketSnapshot) -> Dict[str, Any]:
        """Propone una nueva tesis estructurada para un activo evaluado."""
        if self.is_live and self.client:
            # Llamada con Claude para estructurar la tesis
            pass

        # Estructura por defecto
        return {
            "ticker": ticker,
            "empresa": f"{ticker} Corporation",
            "tipo": "Largo",
            "precio_entrada": snapshot.precio_actual,
            "stop_loss": round(snapshot.precio_actual * 0.92, 2),  # -8% Stop Loss
            "target_precio": round(snapshot.precio_actual * 1.20, 2),  # +20% Target (R:R ~ 2.5)
            "conviccion": 8,
            "capital_asignado": 1000.0,
            "ratio_rr": 2.5,
            "sectores": "[[Tecnologia]]",
        }
