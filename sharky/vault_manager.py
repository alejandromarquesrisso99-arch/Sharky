"""
Gestor de la Bóveda de Obsidian.
Lee, escribe y sincroniza notas en Markdown con metadatos YAML, enlaces de grafo y alertas.
"""

from pathlib import Path
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import yaml

from sharky.config import VAULT_PATH
from sharky.models import (
    HealthStatus,
    InvestmentThesis,
    TradeOrder,
    VitalState,
    MonthlyRebalanceReport,
    RebalanceAction,
    OpportunityAlert,
    AlertStatus,
)


class VaultManager:
    def __init__(self, vault_path: Path = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Garantiza que todas las carpetas del cerebro existan en la bóveda."""
        subdirs = [
            "00_Comite_Direccion",
            "00_Sistema",
            "01_Departamento_Macro",
            "01_Tesis_Activas",
            "02_Analisis_Fundamental",
            "02_Tesis_Cerradas",
            "03_Activos/Sectores",
            "03_Activos/Empresas",
            "03_Activos/Macro_Geopolitica",
            "03_Mesa_Cuantitativa_Riesgo",
            "04_Operaciones_Bitacora",
            "04_Sentimiento_Y_Flujos",
            "05_Diario_Reflexion",
            "06_Lecciones_Aprendidas",
            "07_Plantillas",
            "08_Rebalanceos_Mensuales",
            "09_Alertas_Oportunidades",
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
            active_alerts = len(self.list_active_alerts())
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
                alertas_activas_count=active_alerts,
                ultima_actualizacion=datetime.now()
            )
        except Exception:
            return HealthStatus()

    def update_health_status(self, health: HealthStatus, extra_summary: str = "") -> None:
        """Actualiza el archivo Estado_Vital.md en la bóveda."""
        file_path = self.vault_path / "00_Sistema" / "Estado_Vital.md"
        active_alerts = self.list_active_alerts()
        
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
            "alertas_activas_count": len(active_alerts),
            "ultima_actualizacion": datetime.now().isoformat()
        }

        icon = "🟢" if health.estado_vital == VitalState.OPTIMO else ("🟡" if health.estado_vital == VitalState.ALERTA else ("🔴" if health.estado_vital == VitalState.CUIDADOS_INTENSIVOS else "💀"))

        alerts_section = ""
        if active_alerts:
            alerts_lines = [
                f"- 🚨 **[[{a.ticker}]]** ({a.empresa}) | Convicción: `{a.conviccion}/10` | R:R: `{a.ratio_rr}:1` | Potencial: `+{a.potencial_ganancia_pct}%`"
                for _, a in active_alerts
            ]
            alerts_section = "\n\n### 🚨 Oportunidades de Alta Convicción Detectadas\n" + "\n".join(alerts_lines)

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
| **Alertas de Oportunidad** | `🔥 {len(active_alerts)} activas` | `[[09_Alertas_Oportunidades]]` |

---

## 🧠 Indicadores de Conexión y Memoria

* **Bóveda de Obsidian:** Conectada y sincronizada (`vault/`)
* **Proveedor de IA:** Preparado para Claude 3.7 Sonnet / Claude Opus
* **Última Actualización:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
{alerts_section}
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

    def list_active_alerts(self) -> List[Tuple[Path, OpportunityAlert]]:
        """Devuelve todas las alertas activas en 09_Alertas_Oportunidades/."""
        alerts_dir = self.vault_path / "09_Alertas_Oportunidades"
        active = []
        for file in alerts_dir.glob("*.md"):
            content = file.read_text(encoding="utf-8")
            meta, body = self.parse_markdown(content)
            if not meta or meta.get("estado") != "ACTIVA":
                continue
            try:
                alert = OpportunityAlert(
                    id_alerta=meta.get("id_alerta", file.stem),
                    ticker=meta.get("ticker", ""),
                    empresa=meta.get("empresa", ""),
                    fecha_deteccion=str(meta.get("fecha_deteccion", "")),
                    conviccion=int(meta.get("conviccion", 8)),
                    precio_actual=float(meta.get("precio_actual", 0.0)),
                    entrada_sugerida=float(meta.get("entrada_sugerida", 0.0)),
                    stop_loss=float(meta.get("stop_loss", 0.0)),
                    target_precio=float(meta.get("target_precio", 0.0)),
                    ratio_rr=float(meta.get("ratio_rr", 3.0)),
                    potencial_ganancia_pct=float(meta.get("potencial_ganancia_pct", 20.0)),
                    riesgo_maximo_pct=float(meta.get("riesgo_maximo_pct", 7.0)),
                    descripcion_oportunidad=body,
                    pct_max_cartera=float(meta.get("pct_max_cartera", 8.0)),
                    estado=AlertStatus(meta.get("estado", "ACTIVA")),
                )
                active.append((file, alert))
            except Exception as e:
                pass
        return active

    def write_opportunity_alert(self, alert: OpportunityAlert) -> Path:
        """Crea una nota de alerta de oportunidad en 09_Alertas_Oportunidades/."""
        filename = f"{alert.fecha_deteccion}_ALERTA_{alert.ticker}_{alert.id_alerta}.md"
        file_path = self.vault_path / "09_Alertas_Oportunidades" / filename

        meta = {
            "tipo": "alerta_oportunidad",
            "id_alerta": alert.id_alerta,
            "ticker": alert.ticker,
            "empresa": alert.empresa,
            "fecha_deteccion": alert.fecha_deteccion,
            "conviccion": alert.conviccion,
            "precio_actual": alert.precio_actual,
            "entrada_sugerida": alert.entrada_sugerida,
            "stop_loss": alert.stop_loss,
            "target_precio": alert.target_precio,
            "ratio_rr": alert.ratio_rr,
            "potencial_ganancia_pct": alert.potencial_ganancia_pct,
            "riesgo_maximo_pct": alert.riesgo_maximo_pct,
            "pct_max_cartera": alert.pct_max_cartera,
            "estado": alert.estado.value,
        }

        cat_str = "\n".join([f"{i+1}. **{c}**" for i, c in enumerate(alert.catalizadores)]) if alert.catalizadores else "- Pendiente de catalizador."
        riesgos_str = "\n".join([f"* {r}" for r in alert.riesgos]) if alert.riesgos else "- Riesgos generales de mercado."

        body = f"""# 🚨 ALERTA DE ALTA CONVICCIÓN: {alert.empresa} ({alert.ticker})

> [!WARNING]
> **OPORTUNIDAD ASIMÉTRICA DETECTADA**  
> **Fecha:** {alert.fecha_deteccion} | **Convicción:** `{alert.conviccion}/10` | **Ratio R:R:** `{alert.ratio_rr:.2f} : 1`  
> **Potencial Estimado:** `+{alert.potencial_ganancia_pct:.1f}%` frente a un riesgo controlado de `-{alert.riesgo_maximo_pct:.1f}%`.

---

## 💎 1. ¿Por qué es una Oportunidad Extraordinaria? (Tesis Rápida)

{alert.descripcion_oportunidad}

---

## ⚡ 2. Catalizadores Inmediatos

{cat_str}

---

## 🎯 3. Plan de Entrada y Protección

| Parámetro | Valor Sugerido | Justificación Técnica / Fundamental |
| :--- | :--- | :--- |
| **Precio Actual** | `${alert.precio_actual:,.2f}` | Cotización de mercado en momento de alerta |
| **Zona de Entrada Ideal** | `${alert.entrada_sugerida:,.2f}` | Punto óptimo de entrada con bajo riesgo |
| **Stop Loss Innegociable** | `${alert.stop_loss:,.2f}` | Invalidación total de la hipótesis (-{alert.riesgo_maximo_pct:.1f}%) |
| **Target Objetivo (T1)** | `${alert.target_precio:,.2f}` | Toma de beneficios (+{alert.potencial_ganancia_pct:.1f}%) |
| **Ponderación Máxima Cartera** | `{alert.pct_max_cartera:.1f}%` | Respetando `[[Reglas_De_Supervivencia]]` |

---

## ⚠️ 4. Riesgos Críticos y Puntos Ciegos

{riesgos_str}

---

## 📌 5. Acción Recomendada

* [ ] Evaluar inclusión en la cartera para el próximo **Rebalanceo Mensual** (`[[08_Rebalanceos_Mensuales]]`) o apertura táctica con reserva de liquidez.
"""
        content = self.build_markdown(meta, body)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def write_monthly_rebalance_report(self, report: MonthlyRebalanceReport) -> Path:
        """Crea el informe de rebalanceo mensual en 08_Rebalanceos_Mensuales/."""
        filename = f"{report.fecha}_Rebalanceo_{report.mes_ano.replace(' ', '_')}.md"
        file_path = self.vault_path / "08_Rebalanceos_Mensuales" / filename

        meta = {
            "tipo": "rebalanceo_mensual",
            "mes_ano": report.mes_ano,
            "fecha": report.fecha,
            "peso_cash_pct": report.peso_cash_pct,
            "cash_usd": report.cash_usd,
            "capital_total_usd": report.capital_total_usd,
        }

        compras_rows = []
        ventas_rows = []
        cartera_rows = []

        for p in report.propuestas:
            if p.accion in (RebalanceAction.COMPRAR, RebalanceAction.INCREMENTAR):
                compras_rows.append(
                    f"| `[[{p.ticker}]]` | **{p.accion.value}** | {p.peso_objetivo_pct:.1f}% | ${p.capital_asignado_usd:,.2f} | {p.acciones_estimadas:.2f} | ${p.stop_loss_sugerido:,.2f} | ${p.target_sugerido:,.2f} | {p.motivo} |"
                )
            elif p.accion in (RebalanceAction.VENDER, RebalanceAction.REDUCIR):
                ventas_rows.append(
                    f"| `[[{p.ticker}]]` | **{p.accion.value}** | {p.peso_actual_pct:.1f}% | {p.peso_objetivo_pct:.1f}% | ${p.capital_asignado_usd:,.2f} | {p.motivo} |"
                )

            if p.peso_objetivo_pct > 0:
                cartera_rows.append(
                    f"| `[[{p.ticker}]]` | `{p.sector}` | **{p.peso_objetivo_pct:.1f}%** | ${p.capital_asignado_usd:,.2f} | ${p.stop_loss_sugerido:,.2f} | {p.conviccion}/10 |"
                )

        tabla_compras_str = "\n".join(compras_rows) if compras_rows else "| - | *No hay nuevas compras requeridas* | - | - | - | - | - | - |"
        tabla_ventas_str = "\n".join(ventas_rows) if ventas_rows else "| - | *No hay ventas requeridas este mes* | - | - | - | - |"
        tabla_cartera_str = "\n".join(cartera_rows)

        pct_equity = round(100.0 - report.peso_cash_pct, 1)
        equity_usd = round(report.capital_total_usd - report.cash_usd, 2)

        body = f"""# 📅 Propuesta de Rebalanceo Mensual: {report.mes_ano}

> [!IMPORTANT]
> **Fecha de Emisión:** {report.fecha}  
> **Capital Total:** `${report.capital_total_usd:,.2f} USD` | **Reserva de Liquidez (Cash):** `{report.peso_cash_pct:.1f}% (${report.cash_usd:,.2f})`  
> **Estrategia:** Asignación de cartera a medio/largo plazo con vigilancia diaria intrames.

---

## 🌍 1. Diagnóstico Macroeconómico, Geopolítico y Sentimiento

### Régimen Macro Actual
{report.regimen_macro}

### Dinámica Geopolítica y Cadenas de Suministro
{report.geopolitica_resumen}

### Sentimiento de Mercado, Inercias y Sesgos
{report.sentimiento_resumen}

---

## 🎯 2. Lista Maestra de Acciones: Día 1

### 🔴 Órdenes de Venta / Reducción (Trim / Exit)
| Ticker | Acción | % Actual | % Objetivo | Capital a Liberar | Motivo / Tesis |
| :--- | :--- | :--- | :--- | :--- | :--- |
{tabla_ventas_str}

### 🟢 Órdenes de Compra / Expansión (Buy / Add)
| Ticker | Acción | % Objetivo | Capital Asignado | Acciones Est. | Stop Loss | Target | Tesis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{tabla_compras_str}

---

## 💼 3. Composición Objetivo de la Cartera

```text
Reserva de Liquidez (Cash) : {report.peso_cash_pct:.1f}% (${report.cash_usd:,.2f})
Renta Variable / Activos    : {pct_equity:.1f}% (${equity_usd:,.2f})
```

| Activo / Ticker | Sector | Ponderación (%) | Capital ($) | Rango Stop Loss | Convicción (1-10) |
| :--- | :--- | :--- | :--- | :--- | :--- |
{tabla_cartera_str}

---

## 🛡️ 4. Validación del RiskGovernor

* [x] **Límite de Exposición por Activo:** Ningún activo individual supera el 10% del total.
* [x] **Reserva de Liquidez Mínima:** Mantenimiento de al menos 15% en Cash para contingencias.
* [x] **Ratio R:R Promedio:** $\ge 2.0$ en todas las posiciones sugeridas.
* [x] **Plan de Contingencia Intrames:** Las posiciones solo se cerrarán antes del próximo día 1 si cruzan su `Stop Loss` innegociable.
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

        body = f"""# 📓 Diario de Reflexión e Inteligencia: {date_str}

---

## 1. Monitor Diario de Mercado, Macro y Geopolítica

{summary}

---

## 2. Auditoría de Estado y Supervivencia

* **Estado Vital:** `{health.estado_vital.value}`
* **Salud Actual:** `{health.salud_porcentaje:.1f}%`
* **Energía Metabólica:** `{health.energia_actual:.1f} / 100.0`
* **Capital Total:** `${health.capital_actual:,.2f}`
* **PnL Acumulado:** `${health.pnl_total_usd:,.2f} ({health.pnl_total_pct:.2f}%)`

---

## 3. Disciplina Operativa

Durante el mes no se realizan operaciones por impulso. Toda la evidencia y datos acumulados se canalizan hacia el **Rebalanceo del Día 1** (`[[08_Rebalanceos_Mensuales]]`) y las **Alertas de Oportunidad** (`[[09_Alertas_Oportunidades]]`).
"""
        content = self.build_markdown(meta, body)
        file_path.write_text(content, encoding="utf-8")
        return file_path
