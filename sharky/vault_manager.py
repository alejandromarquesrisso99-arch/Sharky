"""
Gestor de la Bóveda de Obsidian.
Lee, escribe y sincroniza notas en Markdown con metadatos YAML y enlaces de grafo.
"""

from pathlib import Path
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import yaml

from sharky.config import VAULT_PATH
from sharky.models import HealthStatus, InvestmentThesis, TradeOrder, VitalState


class VaultManager:
    def __init__(self, vault_path: Path = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Garantiza que todas las carpetas del cerebro existan en la bóveda."""
        subdirs = [
            "00_Sistema",
            "01_Tesis_Activas",
            "02_Tesis_Cerradas",
            "03_Activos/Sectores",
            "03_Activos/Empresas",
            "04_Operaciones_Bitacora",
            "05_Diario_Reflexion",
            "06_Lecciones_Aprendidas",
            "07_Plantillas",
        ]
        for d in subdirs:
            (self.vault_path / d).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def parse_markdown(content: str) -> Tuple[Dict[str, Any], str]:
        """Extrae el frontmatter YAML y el cuerpo de una nota Markdown."""
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        if match:
            raw_yaml = match.group(1)
            body = match.group(2)
            try:
                metadata = yaml.safe_load(raw_yaml) or {}
                return metadata, body.strip()
            except Exception:
                return {}, content.strip()
        return {}, content.strip()

    @staticmethod
    def build_markdown(metadata: Dict[str, Any], body: str) -> str:
        """Combina metadatos en YAML frontmatter con el cuerpo Markdown."""
        yaml_str = yaml.dump(metadata, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{yaml_str}\n---\n\n{body.strip()}\n"

    def read_health_status(self) -> HealthStatus:
        """Lee y parsea el archivo Estado_Vital.md."""
        file_path = self.vault_path / "00_Sistema" / "Estado_Vital.md"
        if not file_path.exists():
            return HealthStatus()

        content = file_path.read_text(encoding="utf-8")
        metadata, _ = self.parse_markdown(content)
        
        try:
            return HealthStatus(
                estado_vital=VitalState(metadata.get("estado_vital", "OPTIMO")),
                salud_porcentaje=float(metadata.get("salud_porcentaje", 100.0)),
                energia_actual=float(metadata.get("energia_actual", 100.0)),
                capital_inicial=float(metadata.get("capital_inicial", 10000.0)),
                capital_actual=float(metadata.get("capital_actual", 10000.0)),
                pnl_total_usd=float(metadata.get("pnl_total_usd", 0.0)),
                pnl_total_pct=float(metadata.get("pnl_total_pct", 0.0)),
                drawdown_maximo_pct=float(metadata.get("drawdown_maximo_pct", 0.0)),
                operaciones_ganadoras=int(metadata.get("operaciones_ganadoras", 0)),
                operaciones_perdedoras=int(metadata.get("operaciones_perdedoras", 0)),
                win_rate_pct=float(metadata.get("win_rate_pct", 0.0)),
                ultima_actualizacion=datetime.now()
            )
        except Exception:
            return HealthStatus()

    def update_health_status(self, health: HealthStatus, extra_summary: str = "") -> None:
        """Actualiza el archivo Estado_Vital.md en la bóveda."""
        file_path = self.vault_path / "00_Sistema" / "Estado_Vital.md"
        
        metadata = {
            "tipo": "dashboard",
            "estado_vital": health.estado_vital.value,
            "salud_porcentaje": round(health.salud_porcentaje, 2),
            "energia_actual": round(health.energia_actual, 2),
            "capital_inicial": round(health.capital_inicial, 2),
            "capital_actual": round(health.capital_actual, 2),
            "pnl_total_usd": round(health.pnl_total_usd, 2),
            "pnl_total_pct": round(health.pnl_total_pct, 2),
            "drawdown_maximo_pct": round(health.drawdown_maximo_pct, 2),
            "operaciones_ganadoras": health.operaciones_ganadoras,
            "operaciones_perdedoras": health.operaciones_perdedoras,
            "win_rate_pct": round(health.win_rate_pct, 2),
            "ultima_actualizacion": datetime.now().isoformat()
        }

        icon = "🟢" if health.estado_vital == VitalState.OPTIMO else ("🟡" if health.estado_vital == VitalState.ALERTA else ("🔴" if health.estado_vital == VitalState.CUIDADOS_INTENSIVOS else "💀"))

        body = f"""# 🫀 ESTADO VITAL DE SHARKY

> [!NOTE]
> Este archivo es actualizado automáticamente por el motor de Sharky tras cada sesión y evaluación de mercado.

---

## 📊 Métricas de Supervivencia en Tiempo Real

| Métrica | Valor Actual | Umbral Crítico |
| :--- | :--- | :--- |
| **Estado Vital** | `{icon} {health.estado_vital.value}` | `🔴 Cuidados Intensivos` (< 50% Salud) |
| **Salud Biológico-Digital** | `{health.salud_porcentaje:.1f}%` | `<= 0%` (Muerte del Agente) |
| **Energía Metabólica** | `{health.energia_actual:.1f} / 100.0` | `< 10.0` (Modo Hibernación) |
| **Capital Inicial** | `${health.capital_inicial:,.2f}` | - |
| **Capital Actual (NAV)** | `${health.capital_actual:,.2f}` | `${health.capital_inicial * 0.8:,.2f}` (-20% Drawdown) |
| **PnL Acumulado ($ / %)** | `{'+' if health.pnl_total_usd >= 0 else ''}${health.pnl_total_usd:,.2f} ({'+' if health.pnl_total_pct >= 0 else ''}{health.pnl_total_pct:.2f}%)` | - |
| **Drawdown Máximo Registrado** | `{health.drawdown_maximo_pct:.2f}%` | `> 15.00%` |
| **Tasa de Acierto (Win Rate)** | `{health.win_rate_pct:.1f}% ({health.operaciones_ganadoras}/{health.operaciones_ganadoras + health.operaciones_perdedoras})` | `< 40.0%` con R/R 1:1 |

---

## 🧠 Indicadores de Conexión y Memoria

* **Bóveda de Obsidian:** Conectada y sincronizada (`vault/`)
* **Proveedor de IA:** Preparado para Claude 3.7 Sonnet / Claude Opus
* **Última Actualización:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
{extra_summary}
"""
        content = self.build_markdown(metadata, body)
        file_path.write_text(content, encoding="utf-8")

    def list_active_theses(self) -> List[Tuple[Path, InvestmentThesis]]:
        """Lee y devuelve todas las tesis activas en la carpeta 01_Tesis_Activas."""
        theses_dir = self.vault_path / "01_Tesis_Activas"
        theses = []
        for file in theses_dir.glob("*.md"):
            content = file.read_text(encoding="utf-8")
            meta, body = self.parse_markdown(content)
            if not meta or meta.get("estado") != "Activa":
                continue
            try:
                thesis = InvestmentThesis(
                    ticker=meta.get("ticker", ""),
                    empresa=meta.get("empresa", meta.get("ticker", "")),
                    tipo=meta.get("tipo", "Largo"),
                    estado=meta.get("estado", "Activa"),
                    precio_entrada=float(meta.get("precio_entrada", 0.0)),
                    stop_loss=float(meta.get("stop_loss", 0.0)),
                    target_precio=float(meta.get("target_precio", 0.0)),
                    conviccion=int(meta.get("conviccion", 7)),
                    capital_asignado=float(meta.get("capital_asignado", 1000.0)),
                    ratio_rr=float(meta.get("ratio_rr", 2.0)),
                    fecha_apertura=str(meta.get("fecha_apertura", "")),
                    sectores=str(meta.get("sectores", "")),
                    empresa_nota=str(meta.get("empresa_nota", "")),
                    racional=body
                )
                theses.append((file, thesis))
            except Exception as e:
                print(f"[VaultManager] Error parseando tesis {file.name}: {e}")
        return theses

    def record_trade(self, order: TradeOrder) -> Path:
        """Crea una nota de operación en 04_Operaciones_Bitacora/."""
        date_str = order.fecha_ejecucion.strftime("%Y-%m-%d")
        filename = f"{date_str}_{order.modo.value}_{order.ticker}_{order.tipo_orden.value}.md"
        file_path = self.vault_path / "04_Operaciones_Bitacora" / filename

        meta = {
            "id_operacion": order.id_operacion,
            "modo": order.modo.value,
            "ticker": order.ticker,
            "tipo_orden": order.tipo_orden.value,
            "cantidad_acciones": order.cantidad_acciones,
            "precio_ejecutado": order.precio_ejecutado,
            "total_invertido_usd": order.total_invertido_usd,
            "stop_loss": order.stop_loss,
            "target_precio": order.target_precio,
            "estado": order.estado.value,
            "fecha_ejecucion": order.fecha_ejecucion.isoformat(),
            "tesis_referencia": order.tesis_referencia,
        }

        riesgo_usd = abs(order.precio_ejecutado - order.stop_loss) * order.cantidad_acciones
        beneficio_usd = abs(order.target_precio - order.precio_ejecutado) * order.cantidad_acciones
        ratio_rr = round(beneficio_usd / riesgo_usd, 2) if riesgo_usd > 0 else 0.0

        body = f"""# 📝 Registro de Operación: {order.tipo_orden.value} {order.ticker} ({order.id_operacion})

---

## Parámetros de la Ejecución

* **Activo:** `[[{order.ticker}]]`
* **Tipo:** {order.tipo_orden.value}
* **Cantidad:** `{order.cantidad_acciones:.2f} acciones` @ `${order.precio_ejecutado:,.2f}`
* **Capital Comprometido:** `${order.total_invertido_usd:,.2f}`
* **Riesgo Máximo (\$):** `${riesgo_usd:,.2f}`
* **Beneficio Esperado (\$):** `${beneficio_usd:,.2f}`
* **Ratio R:R:** `{ratio_rr}`

---

## Justificación

{order.justificacion or 'Operación ejecutada automáticamente por el motor Sharky basada en tesis previa.'}
"""
        content = self.build_markdown(meta, body)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def write_daily_journal(self, date_str: str, summary: str, health: HealthStatus, events: str = "") -> Path:
        """Crea una entrada de diario en 05_Diario_Reflexion/."""
        filename = f"{date_str}_Cierre_Mercado.md"
        file_path = self.vault_path / "05_Diario_Reflexion" / filename

        meta = {
            "fecha": date_str,
            "estado_vital": health.estado_vital.value,
            "salud_al_cierre": round(health.salud_porcentaje, 2),
            "energia_al_cierre": round(health.energia_actual, 2),
            "eventos_clave": events or "Revisión diaria del ciclo de mercado",
        }

        body = f"""# 📓 Diario de Reflexión: {date_str}

---

## 1. Resumen de la Jornada de Mercado

{summary}

---

## 2. Auditoría de Estado y Supervivencia

* **Estado Vital:** `{health.estado_vital.value}`
* **Salud Actual:** `{health.salud_porcentaje:.1f}%`
* **Energía Metabólica:** `{health.energia_actual:.1f} / 100.0`
* **Capital Total:** `${health.capital_actual:,.2f}`
* **PnL Acumulado:** `${health.pnl_total_usd:,.2f} ({health.pnl_total_pct:.2f}%)`

---

## 3. Autocrítica y Compromiso para Mañana

La disciplina y la paciencia son los únicos escudos contra la destrucción del capital. Seguiré estrictamente mis `[[Reglas_De_Supervivencia]]`.
"""
        content = self.build_markdown(meta, body)
        file_path.write_text(content, encoding="utf-8")
        return file_path
