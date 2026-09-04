"""
Gestor de la Bóveda de Obsidian.

Lee y escribe notas Markdown con frontmatter YAML. Regla transversal: si un
informe se apoya en datos no fiables (precios de referencia, posiciones
valoradas a coste, análisis simulado), la nota lo declara de forma visible.
"""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import yaml

from sharky.config import (
    BREACH_ESCALATION_DAYS,
    DRAWDOWN_ALERTA_MAX_PCT,
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
    DEATH_DRAWDOWN_PCT,
)
from sharky.models import (
    AlertStatus,
    HealthStatus,
    InvestmentThesis,
    MonthlyRebalanceReport,
    OpportunityAlert,
    OrderType,
    PortfolioValuation,
    PriceSource,
    RebalanceAction,
    RiskBreach,
    TradeOrder,
    VitalState,
)
from sharky.config import VAULT_PATH

ICONOS_VITALES = {
    VitalState.OPTIMO: "🟢",
    VitalState.ALERTA: "🟡",
    VitalState.CUIDADOS_INTENSIVOS: "🔴",
    VitalState.MUERTE: "💀",
}


def eur(valor: float) -> str:
    """Formatea un importe en la divisa base. Existe para que ningún informe
    vuelva a etiquetar euros con el símbolo del dólar."""
    return f"{valor:,.2f} €"


def _clave_incumplimiento(b: RiskBreach) -> str:
    """Identifica la 'misma' brecha entre ciclos para poder fecharla.

    Regla + sujeto es suficientemente estable: si RHM sigue sobrepesado
    mañana, sigue siendo la misma brecha que hoy aunque el porcentaje exacto
    haya cambiado un poco.
    """
    return f"{b.regla}|{b.sujeto}"


def _dias_abierta(fecha_iso: str) -> int:
    """Días transcurridos desde `fecha_iso` (``YYYY-MM-DD``). 0 si no es legible."""
    if not fecha_iso:
        return 0
    try:
        inicio = datetime.strptime(str(fecha_iso), "%Y-%m-%d")
    except ValueError:
        return 0
    return max(0, (datetime.now() - inicio).days)


class VaultManager:
    def __init__(self, vault_path: Path = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self._mapa_notas_cache: Optional[Dict[str, str]] = None
        self._ensure_structure()

    # ------------------------------------------------------------------
    # Resolución de enlaces del grafo
    # ------------------------------------------------------------------
    def _mapa_notas(self) -> Dict[str, str]:
        """Correspondencia ticker -> nombre de la ficha en Obsidian.

        El ticker y el nombre de la nota no siempre coinciden: la ficha de
        Rheinmetall se llama `Rheinmetall`, no `RHM`. La correspondencia la
        declara `nota_activo` en el libro de posiciones. Se memoiza porque los
        informes la consultan por cada fila.
        """
        if self._mapa_notas_cache is not None:
            return self._mapa_notas_cache

        mapa: Dict[str, str] = {}
        ledger = self.vault_path / "00_Sistema" / "Cartera_Real.md"
        if ledger.exists():
            meta, _ = self.parse_markdown(ledger.read_text(encoding="utf-8"))
            for cruda in meta.get("posiciones") or []:
                ticker = str(cruda.get("ticker", "")).strip()
                nota = str(cruda.get("nota_activo", "") or "").strip().strip("[]")
                if ticker and nota:
                    mapa[ticker.upper()] = nota
        self._mapa_notas_cache = mapa
        return mapa

    def enlace(self, ticker: str, nota: str = "") -> str:
        """Wikilink a la ficha del activo, mostrando siempre el ticker.

        El separador de alias de Obsidian (`[[Página|Alias]]`) es el mismo
        carácter `|` que delimita columnas en una tabla Markdown. Sin
        escapar, `[[Rheinmetall|RHM]]` dentro de una celda de tabla se
        parte en dos columnas para cualquier cosa que no sea el propio
        renderizador de Obsidian -- que sí entiende `\\|` como el alias.
        Bug real reportado en los diarios de 2026-09: la tabla "Mayores
        Movimientos" se desalineaba en cuanto una posición tenía nombre
        completo distinto del ticker.
        """
        destino = (nota or "").strip().strip("[]") or self._mapa_notas().get(
            (ticker or "").upper().strip(), ""
        )
        if not destino or destino == ticker:
            return f"[[{ticker}]]"
        return f"[[{destino}\\|{ticker}]]"

    def _ensure_structure(self) -> None:
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

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------
    @staticmethod
    def parse_markdown(content: str) -> Tuple[Dict[str, Any], str]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return {}, content.strip()
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
            return metadata, match.group(2).strip()
        except yaml.YAMLError:
            return {}, content.strip()

    @staticmethod
    def build_markdown(metadata: Dict[str, Any], body: str) -> str:
        yaml_str = yaml.dump(metadata, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{yaml_str}\n---\n\n{body.strip()}\n"

    # ------------------------------------------------------------------
    # Estado vital
    # ------------------------------------------------------------------
    @property
    def health_path(self) -> Path:
        return self.vault_path / "00_Sistema" / "Estado_Vital.md"

    def read_health_status(self) -> HealthStatus:
        """Lee Estado_Vital.md. Tolera el esquema antiguo en USD.

        Sin fichero o sin metadatos legibles, `ultima_actualizacion` se fija a
        `datetime.min` (no al modelo por defecto, que sería "ahora"): así una
        bóveda nueva nunca se confunde con "el ciclo de hoy ya se ejecutó".
        """
        if not self.health_path.exists():
            return HealthStatus(ultima_actualizacion=datetime.min)

        meta, _ = self.parse_markdown(self.health_path.read_text(encoding="utf-8"))
        if not meta:
            return HealthStatus(ultima_actualizacion=datetime.min)

        def num(*claves, defecto: float = 0.0) -> float:
            for c in claves:
                if c in meta and meta[c] is not None:
                    try:
                        valor = float(meta[c])
                    except (TypeError, ValueError):
                        continue
                    if valor == valor:  # descarta NaN
                        return valor
            return defecto

        try:
            estado = VitalState(str(meta.get("estado_vital", "OPTIMO")))
        except ValueError:
            estado = VitalState.OPTIMO

        capital_inicial = num("capital_inicial_eur", "capital_inicial")
        nav = num("nav_actual_eur", "capital_actual", defecto=capital_inicial)

        # Fecha del último ciclo persistido, no el instante de esta lectura: de
        # ella depende tanto el desgaste de energía (proporcional a los días
        # reales transcurridos) como la detección de "ya se ejecutó hoy" que usa
        # `sharky.cli startup`. Sin timestamp legible se asume una fecha muy
        # antigua para no bloquear el primer ciclo de una bóveda nueva o de un
        # fichero con el esquema heredado.
        ultima_actualizacion = datetime.min
        crudo = meta.get("ultima_actualizacion")
        if crudo:
            try:
                ultima_actualizacion = datetime.fromisoformat(str(crudo))
            except ValueError:
                pass

        return HealthStatus(
            estado_vital=estado,
            salud_porcentaje=min(100.0, max(0.0, num("salud_porcentaje", defecto=100.0))),
            energia_actual=min(100.0, max(0.0, num("energia_actual", defecto=100.0))),
            capital_inicial_eur=capital_inicial,
            nav_actual_eur=nav,
            # Si nunca se persistió el high-water mark, se siembra con el mayor
            # valor conocido para no fabricar un drawdown inexistente.
            nav_maximo_historico_eur=max(
                num("nav_maximo_historico_eur"), capital_inicial, nav
            ),
            pnl_total_eur=num("pnl_total_eur", "pnl_total_usd"),
            pnl_total_pct=num("pnl_total_pct"),
            drawdown_actual_pct=num("drawdown_actual_pct"),
            drawdown_maximo_pct=num("drawdown_maximo_pct"),
            operaciones_ganadoras=int(num("operaciones_ganadoras")),
            operaciones_perdedoras=int(num("operaciones_perdedoras")),
            win_rate_pct=num("win_rate_pct"),
            alertas_activas_count=len(self.list_active_alerts()),
            cobertura_datos_pct=num("cobertura_datos_pct", defecto=100.0),
            ultima_actualizacion=ultima_actualizacion,
        )

    def update_health_status(
        self,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
        extra_summary: str = "",
    ) -> Path:
        """Reescribe el cuadro de mandos Estado_Vital.md."""
        alertas = self.list_active_alerts()
        incumplimientos = incumplimientos or []

        # Antigüedad de cada incumplimiento: cuánto lleva abierto, no sólo si
        # está abierto hoy. Ver `_actualizar_antiguedad_incumplimientos`.
        antiguedad = self._actualizar_antiguedad_incumplimientos(incumplimientos)
        incumplimientos_con_edad = [
            (b, _dias_abierta(antiguedad.get(_clave_incumplimiento(b), "")))
            for b in incumplimientos
        ]
        escaladas = [b for b, dias in incumplimientos_con_edad if dias >= BREACH_ESCALATION_DAYS]

        meta = {
            "tipo": "dashboard",
            "divisa_base": "EUR",
            "estado_vital": health.estado_vital.value,
            "salud_porcentaje": round(health.salud_porcentaje, 2),
            "energia_actual": round(health.energia_actual, 2),
            "capital_inicial_eur": round(health.capital_inicial_eur, 2),
            "nav_actual_eur": round(health.nav_actual_eur, 2),
            "nav_maximo_historico_eur": round(health.nav_maximo_historico_eur, 2),
            "pnl_total_eur": round(health.pnl_total_eur, 2),
            "pnl_total_pct": round(health.pnl_total_pct, 2),
            "drawdown_actual_pct": round(health.drawdown_actual_pct, 2),
            "drawdown_maximo_pct": round(health.drawdown_maximo_pct, 2),
            "operaciones_ganadoras": health.operaciones_ganadoras,
            "operaciones_perdedoras": health.operaciones_perdedoras,
            "win_rate_pct": round(health.win_rate_pct, 2),
            "alertas_activas_count": len(alertas),
            "cobertura_datos_pct": round(health.cobertura_datos_pct, 2),
            "incumplimientos_activos": len(incumplimientos),
            "incumplimientos_escalados": len(escaladas),
            "incumplimientos_desde": antiguedad,
            "ultima_actualizacion": datetime.now().isoformat(),
        }

        icono = ICONOS_VITALES.get(health.estado_vital, "❔")
        umbral_muerte_eur = health.nav_maximo_historico_eur * (1 - DEATH_DRAWDOWN_PCT / 100.0)

        secciones: List[str] = []

        if health.cobertura_datos_pct < 100.0:
            secciones.append(
                "> [!WARNING]\n"
                f"> **Datos parcialmente estimados.** Sólo el {health.cobertura_datos_pct:.1f}% "
                "del NAV está respaldado por cotizaciones de mercado; el resto se valora a\n"
                "> coste de adquisición. Trata el PnL como una estimación incompleta."
            )

        if valuation:
            secciones.append(self._render_positions_section(valuation))

        if incumplimientos:
            secciones.append(self._render_breaches_section(incumplimientos_con_edad))

        if alertas:
            lineas = [
                f"- 🚨 **{self.enlace(a.ticker)}** ({a.empresa}) | Convicción `{a.conviccion}/10` "
                f"| R:R `{a.ratio_rr:.2f}:1` | Potencial `+{a.potencial_ganancia_pct:.1f}%`"
                for _, a in alertas
            ]
            secciones.append(
                "## 🚨 Oportunidades de Alta Convicción Activas\n\n" + "\n".join(lineas)
            )

        if extra_summary.strip():
            secciones.append(extra_summary.strip())

        cuerpo = f"""# 🫀 ESTADO VITAL DE SHARKY

> [!NOTE]
> Generado automáticamente por el motor de Sharky. Divisa base: **EUR**.
> La cartera se lee de [[Cartera_Real]], la única fuente de verdad de posiciones.

---

## 📊 Métricas de Supervivencia

| Métrica | Valor Actual | Umbral Crítico |
| :--- | :--- | :--- |
| **Estado Vital** | `{icono} {health.estado_vital.value}` | `🔴 Cuidados Intensivos` (drawdown ≥ {DRAWDOWN_ALERTA_MAX_PCT:.0f}%) |
| **Salud** | `{health.salud_porcentaje:.1f}%` | `0%` (drawdown ≥ {DEATH_DRAWDOWN_PCT:.0f}%) |
| **Energía Metabólica** | `{health.energia_actual:.1f} / 100.0` | `< 10.0` (hibernación) |
| **Capital de Referencia** | `{eur(health.capital_inicial_eur)}` | - |
| **NAV Actual** | `{eur(health.nav_actual_eur)}` | `{eur(umbral_muerte_eur)}` |
| **Máximo Histórico (HWM)** | `{eur(health.nav_maximo_historico_eur)}` | - |
| **PnL sobre Referencia** | `{health.pnl_total_eur:+,.2f} € ({health.pnl_total_pct:+.2f}%)` | - |
| **Drawdown Actual** | `{health.drawdown_actual_pct:.2f}%` | `> {DRAWDOWN_ALERTA_MAX_PCT:.2f}%` |
| **Drawdown Máximo** | `{health.drawdown_maximo_pct:.2f}%` | `> {DEATH_DRAWDOWN_PCT:.2f}%` |
| **Win Rate** | `{health.win_rate_pct:.1f}% ({health.operaciones_ganadoras}/{health.operaciones_ganadoras + health.operaciones_perdedoras})` | `< 40.0%` |
| **Cobertura de Datos** | `{health.cobertura_datos_pct:.1f}%` | `< 100%` |
| **Incumplimientos del Mandato** | `{len(incumplimientos)}` | `0` |
| **Incumplimientos Escalados (≥{BREACH_ESCALATION_DAYS}d abiertos)** | `{'🔺 ' if escaladas else ''}{len(escaladas)}` | `0` |
| **Alertas Activas** | `🔥 {len(alertas)}` | [[09_Alertas_Oportunidades]] |

> El drawdown se mide contra el **máximo histórico del NAV**, no contra el
> capital inicial.

**Última actualización:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`

---

{chr(10).join(f"{s}{chr(10)}{chr(10)}---{chr(10)}" for s in secciones)}
## 🔗 Enlaces Bidireccionales del Grafo

* Cartera: [[Cartera_Real]] | Riesgo: [[Metricas_Riesgo]], [[Politica_Control_Riesgo]]
* Mandato: [[Mandato_Institucional]], [[Reglas_De_Supervivencia]]
* Tesis: [[01_Tesis_Activas]] | Operaciones: [[04_Operaciones_Bitacora]]
"""
        self.health_path.write_text(self.build_markdown(meta, cuerpo), encoding="utf-8")
        return self.health_path

    def _render_positions_section(self, v: PortfolioValuation) -> str:
        filas = []
        for p in sorted(v.posiciones, key=lambda x: -x.valor_mercado_eur):
            marca = "" if p.fuente_precio.es_fiable else " ⚠️"
            fx = (
                f"{p.precio_cotizacion:,.2f} {p.divisa_cotizacion}"
                if p.divisa_cotizacion != v.divisa_base
                else f"{p.precio_cotizacion:,.2f} €"
            )
            filas.append(
                f"| {self.enlace(p.ticker, p.nota_activo)}{marca} | {p.sector} | {fx} | "
                f"{p.valor_mercado_eur:,.2f} € | "
                f"{p.coste_total_eur:,.2f} € | {p.pnl_eur:+,.2f} € | {p.pnl_pct:+.2f}% | {p.peso_pct:.2f}% |"
            )
        sectores = " · ".join(
            f"**{s}** {w:.1f}%"
            for s, w in sorted(v.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1])
        )
        return f"""## 💼 Cartera Valorada a Mercado

| Activo | Sector | Cotización | Valor | Coste | PnL | PnL % | Peso |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(filas)}
| **Efectivo** | Liquidez | - | **{v.efectivo_eur:,.2f} €** | - | - | - | **{v.peso_efectivo_pct:.2f}%** |
| **NAV TOTAL** | | | **{v.nav_eur:,.2f} €** | {v.coste_total_eur:,.2f} € | {v.pnl_total_eur:+,.2f} € | {v.pnl_total_pct:+.2f}% | 100% |

**Exposición sectorial:** {sectores}

*⚠️ = posición sin cotización fiable, valorada a coste.*"""

    def _actualizar_antiguedad_incumplimientos(
        self, incumplimientos: List[RiskBreach]
    ) -> Dict[str, str]:
        """Persiste la fecha de primera detección de cada brecha activa.

        Sin esto, cada ciclo vuelve a listar las mismas brechas desde cero y
        no hay forma de distinguir "lleva un día abierta" de "lleva dos
        meses abierta" -- que es justo la que más necesita escalar en
        visibilidad. Se lee del propio `Estado_Vital.md` (campo
        `incumplimientos_desde`) para no depender de un almacén aparte.
        """
        previas: Dict[str, str] = {}
        if self.health_path.exists():
            meta, _ = self.parse_markdown(self.health_path.read_text(encoding="utf-8"))
            crudo = (meta or {}).get("incumplimientos_desde") or {}
            if isinstance(crudo, dict):
                previas = {str(k): str(v) for k, v in crudo.items()}

        hoy = datetime.now().strftime("%Y-%m-%d")
        claves_activas = {_clave_incumplimiento(b) for b in incumplimientos}
        # Conserva la fecha original de las brechas que siguen abiertas;
        # las que ya no aparecen (resueltas, o cambió el motivo) se sueltan.
        actualizado = {k: v for k, v in previas.items() if k in claves_activas}
        for clave in claves_activas:
            actualizado.setdefault(clave, hoy)
        return actualizado

    @staticmethod
    def _render_breaches_section(
        incumplimientos_con_edad: List[Tuple[RiskBreach, int]],
    ) -> str:
        filas = []
        escaladas: List[Tuple[RiskBreach, int]] = []
        for b, dias in incumplimientos_con_edad:
            if dias >= BREACH_ESCALATION_DAYS:
                escaladas.append((b, dias))
            antiguedad_txt = f"{dias}d" + (" 🔺" if dias >= BREACH_ESCALATION_DAYS else "")
            filas.append(
                f"| {'🔴' if b.severidad == 'ALTA' else '🟡'} {b.severidad} | {b.regla} | "
                f"`{b.sujeto}` | {b.valor_actual_pct:.2f}% | {b.limite_pct:.1f}% | "
                f"{antiguedad_txt} | {b.accion_correctiva} |"
            )

        banner = ""
        if escaladas:
            detalle = ", ".join(f"`{b.sujeto}` ({b.regla}, {dias}d)" for b, dias in escaladas)
            banner = (
                "> [!CAUTION] Escalado por antigüedad\n"
                f"> **{len(escaladas)} incumplimiento(s) llevan {BREACH_ESCALATION_DAYS} días o más "
                f"sin resolverse:** {detalle}. El `RiskGovernor` los sigue detectando cada ciclo, "
                "pero nada los corrige solo: requieren una decisión manual.\n\n"
            )

        return f"""## 🛡️ Incumplimientos del Mandato ({len(incumplimientos_con_edad)})

{banner}> [!CAUTION]
> Detectados por el `RiskGovernor` contra [[Reglas_De_Supervivencia]].
> Se corrigen en el **Rebalanceo del Día 1** ([[08_Rebalanceos_Mensuales]]).

| Severidad | Regla | Sujeto | Actual | Límite | Abierta desde | Acción Correctiva |
| :--- | :--- | :--- | ---: | ---: | ---: | :--- |
{chr(10).join(filas)}"""

    # ------------------------------------------------------------------
    # Tesis
    # ------------------------------------------------------------------
    def leer_memoria_diario(self, dias: int) -> List[Dict[str, Any]]:
        """Frontmatter de las entradas de `05_Diario_Reflexion` de los
        últimos `dias` días, ordenadas de más antigua a más reciente.

        Lee sólo el frontmatter (fecha, estado vital, NAV, drawdown,
        eventos_clave, si ese día fue simulado...), nunca el cuerpo
        completo de la nota: es la diferencia entre un resumen de una
        línea por día y meter el diario entero -- ya extenso de por sí --
        dentro del prompt de cada informe nuevo.
        """
        carpeta = self.vault_path / "05_Diario_Reflexion"
        if dias <= 0 or not carpeta.exists():
            return []
        corte = datetime.now() - timedelta(days=dias)
        entradas: List[Dict[str, Any]] = []
        for file in sorted(carpeta.glob("*_Cierre_Mercado.md")):
            try:
                meta, _ = self.parse_markdown(file.read_text(encoding="utf-8"))
            except OSError:
                continue
            if not meta:
                continue
            try:
                fecha = datetime.strptime(str(meta.get("fecha", "")), "%Y-%m-%d")
            except ValueError:
                continue
            if fecha < corte:
                continue
            entradas.append(meta)
        entradas.sort(key=lambda m: str(m.get("fecha", "")))
        return entradas

    def list_active_theses(self) -> List[Tuple[Path, InvestmentThesis]]:
        """Tesis con `estado: Activa`.

        Una tesis expresa convicción, NO una tenencia: el NAV se calcula
        exclusivamente desde [[Cartera_Real]].
        """
        theses: List[Tuple[Path, InvestmentThesis]] = []
        for file in sorted((self.vault_path / "01_Tesis_Activas").glob("*.md")):
            meta, body = self.parse_markdown(file.read_text(encoding="utf-8"))
            if not meta or str(meta.get("estado", "")).strip() != "Activa":
                continue
            try:
                theses.append((
                    file,
                    InvestmentThesis(
                        ticker=str(meta.get("ticker", "")).strip(),
                        empresa=str(meta.get("empresa", meta.get("ticker", ""))),
                        tipo=str(meta.get("tipo", "Largo")),
                        estado="Activa",
                        precio_entrada=float(meta.get("precio_entrada", 0.0) or 0.0),
                        divisa=str(meta.get("divisa", "EUR")),
                        stop_loss=float(meta.get("stop_loss", 0.0) or 0.0),
                        target_precio=float(meta.get("target_precio", 0.0) or 0.0),
                        conviccion=int(meta.get("conviccion", 7) or 7),
                        ratio_rr=float(meta.get("ratio_rr", 0.0) or 0.0),
                        fecha_apertura=str(meta.get("fecha_apertura", "")),
                        sectores=str(meta.get("sectores", "")),
                        empresa_nota=str(meta.get("empresa_nota", "")),
                        racional=body,
                    ),
                ))
            except (TypeError, ValueError) as exc:
                print(f"[VaultManager] Tesis ilegible {file.name}: {exc}")
        return theses

    # ------------------------------------------------------------------
    # Alertas
    # ------------------------------------------------------------------
    def list_active_alerts(self) -> List[Tuple[Path, OpportunityAlert]]:
        activas: List[Tuple[Path, OpportunityAlert]] = []
        for file in sorted((self.vault_path / "09_Alertas_Oportunidades").glob("*.md")):
            meta, body = self.parse_markdown(file.read_text(encoding="utf-8"))
            if not meta or str(meta.get("estado", "")).strip() != "ACTIVA":
                continue
            try:
                activas.append((
                    file,
                    OpportunityAlert(
                        id_alerta=str(meta.get("id_alerta", file.stem)),
                        ticker=str(meta.get("ticker", "")).strip(),
                        empresa=str(meta.get("empresa", "")),
                        fecha_deteccion=str(meta.get("fecha_deteccion", "")),
                        conviccion=int(meta.get("conviccion", 8) or 8),
                        precio_actual=float(meta.get("precio_actual", 0.0) or 0.0),
                        divisa=str(meta.get("divisa", "USD")),
                        entrada_sugerida=float(meta.get("entrada_sugerida", 0.0) or 0.0),
                        stop_loss=float(meta.get("stop_loss", 0.0) or 0.0),
                        target_precio=float(meta.get("target_precio", 0.0) or 0.0),
                        ratio_rr=float(meta.get("ratio_rr", 0.0) or 0.0),
                        potencial_ganancia_pct=float(meta.get("potencial_ganancia_pct", 0.0) or 0.0),
                        riesgo_maximo_pct=float(meta.get("riesgo_maximo_pct", 0.0) or 0.0),
                        descripcion_oportunidad=body,
                        pct_max_cartera=float(meta.get("pct_max_cartera", 8.0) or 8.0),
                        estado=AlertStatus.ACTIVA,
                        # Sin esto, toda alerta releída de disco "olvida" su procedencia
                        # y vuelve a mostrarse como MERCADO aunque se escribiera como
                        # SIMULADO: la marca de fiabilidad que exige el invariante de
                        # `sharky.models` se perdía en el viaje de ida y vuelta.
                        fuente_precio=PriceSource(str(meta.get("fuente_precio", "MERCADO"))),
                    ),
                ))
            except (TypeError, ValueError) as exc:
                print(f"[VaultManager] Alerta ilegible {file.name}: {exc}")
        return activas

    def has_active_alert(self, ticker: str) -> bool:
        """Evita reemitir una alerta que ya está viva para el mismo activo."""
        clave = ticker.upper().strip()
        return any(a.ticker.upper() == clave for _, a in self.list_active_alerts())

    def write_opportunity_alert(self, alert: OpportunityAlert) -> Path:
        # El id ya contiene fecha y ticker: no se duplica en el nombre.
        file_path = self.vault_path / "09_Alertas_Oportunidades" / f"{alert.fecha_deteccion}_ALERTA_{alert.id_alerta}.md"

        meta = {
            "tipo": "alerta_oportunidad",
            "id_alerta": alert.id_alerta,
            "ticker": alert.ticker,
            "empresa": alert.empresa,
            "fecha_deteccion": alert.fecha_deteccion,
            "conviccion": alert.conviccion,
            "divisa": alert.divisa,
            "precio_actual": alert.precio_actual,
            "entrada_sugerida": alert.entrada_sugerida,
            "stop_loss": alert.stop_loss,
            "target_precio": alert.target_precio,
            "ratio_rr": alert.ratio_rr,
            "potencial_ganancia_pct": alert.potencial_ganancia_pct,
            "riesgo_maximo_pct": alert.riesgo_maximo_pct,
            "pct_max_cartera": alert.pct_max_cartera,
            "fuente_precio": alert.fuente_precio.value,
            "estado": alert.estado.value,
        }

        d = alert.divisa
        cat = "\n".join(f"{i+1}. **{c}**" for i, c in enumerate(alert.catalizadores)) or "- Pendiente de catalizador."
        rsg = "\n".join(f"* {r}" for r in alert.riesgos) or "- Riesgos generales de mercado."

        aviso = ""
        if not alert.fuente_precio.es_fiable:
            aviso = (
                "\n> [!WARNING]\n"
                f"> Precios derivados de una cotización **{alert.fuente_precio.value}**, "
                "no de datos de mercado en vivo. No operar sobre estos niveles sin verificar.\n"
            )

        cuerpo = f"""# 🚨 ALERTA DE ALTA CONVICCIÓN: {alert.empresa} ({alert.ticker})

> [!WARNING]
> **OPORTUNIDAD ASIMÉTRICA DETECTADA**
> **Fecha:** {alert.fecha_deteccion} | **Convicción:** `{alert.conviccion}/10` | **R:R:** `{alert.ratio_rr:.2f} : 1`
> **Potencial:** `+{alert.potencial_ganancia_pct:.1f}%` frente a un riesgo de `-{alert.riesgo_maximo_pct:.1f}%`.
{aviso}
---

## 💎 1. Tesis Rápida

{alert.descripcion_oportunidad}

---

## ⚡ 2. Catalizadores

{cat}

---

## 🎯 3. Plan de Entrada y Protección

> Todos los niveles se expresan en **{d}**, la divisa de cotización del activo.
> La cartera está denominada en EUR: el dimensionamiento en euros lo calcula el
> `RiskGovernor` al registrar la operación.

| Parámetro | Valor | Justificación |
| :--- | ---: | :--- |
| **Precio Actual** | `{alert.precio_actual:,.2f} {d}` | Cotización al emitir la alerta |
| **Zona de Entrada** | `{alert.entrada_sugerida:,.2f} {d}` | Punto óptimo riesgo/recompensa |
| **Stop Loss Innegociable** | `{alert.stop_loss:,.2f} {d}` | Invalidación de la hipótesis (-{alert.riesgo_maximo_pct:.1f}%) |
| **Target (T1)** | `{alert.target_precio:,.2f} {d}` | Toma de beneficios (+{alert.potencial_ganancia_pct:.1f}%) |
| **Peso Máximo en Cartera** | `{alert.pct_max_cartera:.1f}%` | Según [[Reglas_De_Supervivencia]] |

---

## ⚠️ 4. Riesgos y Puntos Ciegos

{rsg}

---

## 📌 5. Acción Recomendada

* [ ] Evaluar en el próximo **Rebalanceo del Día 1** ([[08_Rebalanceos_Mensuales]]).
* [ ] Verificar que la entrada no rompe los límites de [[Cartera_Real]] (activo ≤ {MAX_POSITION_SIZE_PCT:.0f}%, sector ≤ {MAX_SECTOR_SIZE_PCT:.0f}%, caja ≥ {MIN_CASH_PCT:.0f}%).

---

## 🔗 Enlaces del Grafo

* Activo: {self.enlace(alert.ticker)} | MOC: [[09_Alertas_Oportunidades]]
* Riesgo: [[Politica_Control_Riesgo]] | Cartera: [[Cartera_Real]]
"""
        file_path.write_text(self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "09_Alertas_Oportunidades",
            "## 🔥 Alertas Activas en Radar",
            f"* 🚨 [[{file_path.stem}]] — **{alert.empresa}** ({alert.ticker})",
        )
        return file_path

    # ------------------------------------------------------------------
    # Operaciones
    # ------------------------------------------------------------------
    def write_trade_note(
        self,
        order: TradeOrder,
        veredicto: str,
        pnl_realizado_eur: Optional[float] = None,
    ) -> Path:
        """Registra una operación aprobada en la bitácora."""
        fecha = order.fecha_ejecucion.strftime("%Y-%m-%d")
        sentido = order.tipo_orden.value
        file_path = (
            self.vault_path / "04_Operaciones_Bitacora"
            / f"{fecha}_{order.modo.value}_{order.ticker}_{sentido}_{order.id_operacion}.md"
        )

        meta = {
            "tipo": "operacion",
            "id_operacion": order.id_operacion,
            "modo": order.modo.value,
            "ticker": order.ticker,
            "tipo_orden": sentido,
            "fecha_ejecucion": order.fecha_ejecucion.isoformat(),
            "cantidad": order.cantidad_acciones,
            "precio_ejecutado": order.precio_ejecutado,
            "divisa_ejecucion": order.divisa_ejecucion,
            "tipo_cambio_a_eur": order.tipo_cambio_a_eur,
            "total_eur": round(order.total_invertido_eur, 2),
            "comision_eur": round(order.comision_eur, 2),
            "stop_loss": order.stop_loss,
            "target_precio": order.target_precio,
            "estado": order.estado.value,
            "tesis_referencia": order.tesis_referencia,
        }
        if pnl_realizado_eur is not None:
            meta["pnl_realizado_eur"] = round(pnl_realizado_eur, 2)

        d = order.divisa_ejecucion
        filas_extra = ""
        if order.tipo_orden == OrderType.COMPRA:
            filas_extra = (
                f"| **Stop Loss** | `{order.stop_loss:,.2f} {d}` |\n"
                f"| **Target** | `{order.target_precio:,.2f} {d}` |\n"
            )
        elif pnl_realizado_eur is not None:
            filas_extra = f"| **PnL Realizado** | `{pnl_realizado_eur:+,.2f} €` |\n"

        conversion = ""
        if d != "EUR":
            conversion = (
                f"| **Tipo de Cambio Aplicado** | `1 {d} = {order.tipo_cambio_a_eur:.6f} EUR` |\n"
            )

        cuerpo = f"""# 🧾 Operación {sentido}: {order.ticker}

> [!NOTE]
> **Modo:** `{order.modo.value}` | **ID:** `{order.id_operacion}`
> **Ejecutada:** {order.fecha_ejecucion.strftime('%Y-%m-%d %H:%M:%S')}
> Sharky **no** envía órdenes al broker: esta nota registra una ejecución ya
> realizada en {self._custodio_hint()}.

---

## 1. Detalle de la Ejecución

| Campo | Valor |
| :--- | ---: |
| **Activo** | {self.enlace(order.ticker)} |
| **Sentido** | `{sentido}` |
| **Cantidad** | `{order.cantidad_acciones:,.6f}` títulos |
| **Precio** | `{order.precio_ejecutado:,.4f} {d}` |
{conversion}| **Importe Total** | `{order.total_invertido_eur:,.2f} €` |
| **Comisión** | `{order.comision_eur:,.2f} €` |
{filas_extra}
---

## 2. Veredicto del RiskGovernor

```text
{veredicto}
```

---

## 3. Justificación

{order.justificacion or "*Sin justificación registrada.*"}

---

## 🔗 Enlaces del Grafo

* Activo: {self.enlace(order.ticker)} | Tesis: [[{order.tesis_referencia or '01_Tesis_Activas'}]]
* Cartera: [[Cartera_Real]] | Riesgo: [[Politica_Control_Riesgo]]
* MOC: [[04_Operaciones_Bitacora]]
"""
        file_path.write_text(self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "04_Operaciones_Bitacora",
            "## 📋 Operaciones Registradas",
            f"* 🧾 [[{file_path.stem}]] — {sentido} {order.ticker}",
        )
        return file_path

    def _custodio_hint(self) -> str:
        ledger = self.vault_path / "00_Sistema" / "Cartera_Real.md"
        if ledger.exists():
            meta, _ = self.parse_markdown(ledger.read_text(encoding="utf-8"))
            return str(meta.get("custodio", "tu custodio"))
        return "tu custodio"

    # ------------------------------------------------------------------
    # Rebalanceo mensual
    # ------------------------------------------------------------------
    def write_monthly_rebalance_report(self, report: MonthlyRebalanceReport) -> Path:
        file_path = (
            self.vault_path / "08_Rebalanceos_Mensuales"
            / f"{report.fecha}_Rebalanceo_{report.mes_ano.replace(' ', '_')}.md"
        )

        meta = {
            "tipo": "rebalanceo_mensual",
            "mes_ano": report.mes_ano,
            "fecha": report.fecha,
            "divisa_base": "EUR",
            "nav_total_eur": round(report.nav_total_eur, 2),
            "peso_cash_objetivo_pct": round(report.peso_cash_objetivo_pct, 2),
            "cash_objetivo_eur": round(report.cash_objetivo_eur, 2),
            "num_propuestas": len(report.propuestas),
            "incumplimientos_corregidos": len(report.incumplimientos),
            "cobertura_datos_pct": round(report.cobertura_datos_pct, 2),
        }

        ventas, compras, objetivo = [], [], []
        for p in report.propuestas:
            accion = p.accion.value
            marca = "" if p.fuente_precio.es_fiable else " ⚠️"
            if p.accion in (RebalanceAction.VENDER, RebalanceAction.REDUCIR):
                ventas.append(
                    f"| {self.enlace(p.ticker, p.nota_activo)}{marca} | **{accion}** | "
                    f"{p.peso_actual_pct:.2f}% | {p.peso_objetivo_pct:.2f}% | "
                    f"{abs(p.delta_eur):,.2f} € | {p.motivo} |"
                )
            elif p.accion in (RebalanceAction.COMPRAR, RebalanceAction.INCREMENTAR):
                compras.append(
                    f"| {self.enlace(p.ticker, p.nota_activo)}{marca} | **{accion}** | "
                    f"{p.peso_actual_pct:.2f}% | {p.peso_objetivo_pct:.2f}% | {p.delta_eur:,.2f} € | "
                    f"{p.acciones_estimadas:,.4f} | {p.stop_loss_sugerido:,.2f} {p.divisa_precio} | "
                    f"{p.target_sugerido:,.2f} {p.divisa_precio} | {p.motivo} |"
                )
            if p.peso_objetivo_pct > 0:
                objetivo.append(
                    f"| {self.enlace(p.ticker, p.nota_activo)} | {p.sector} | **{p.peso_objetivo_pct:.2f}%** | "
                    f"{p.capital_objetivo_eur:,.2f} € | {p.conviccion}/10 |"
                )

        t_ventas = "\n".join(ventas) or "| - | *Ninguna venta requerida* | - | - | - | - |"
        t_compras = "\n".join(compras) or "| - | *Ninguna compra requerida* | - | - | - | - | - | - | - |"
        t_objetivo = "\n".join(objetivo) or "| - | - | - | - | - |"

        pct_equity = round(100.0 - report.peso_cash_objetivo_pct, 2)
        equity_eur = round(report.nav_total_eur - report.cash_objetivo_eur, 2)

        seccion_incumplimientos = ""
        if report.incumplimientos:
            filas = [
                f"| {'🔴' if b.severidad == 'ALTA' else '🟡'} | {b.regla} | `{b.sujeto}` | "
                f"{b.valor_actual_pct:.2f}% | {b.limite_pct:.1f}% |"
                for b in report.incumplimientos
            ]
            seccion_incumplimientos = f"""
## 🛡️ Incumplimientos que este rebalanceo corrige ({len(report.incumplimientos)})

| Sev. | Regla | Sujeto | Actual | Límite |
| :--- | :--- | :--- | ---: | ---: |
{chr(10).join(filas)}

---
"""

        seccion_avisos = ""
        if report.advertencias or report.cobertura_datos_pct < 100.0:
            avisos = "\n".join(f"> * {a}" for a in report.advertencias)
            seccion_avisos = f"""
> [!WARNING]
> **Calidad de los datos:** cobertura de mercado del {report.cobertura_datos_pct:.1f}%.
{avisos}

---
"""

        cuerpo = f"""# 📅 Propuesta de Rebalanceo: {report.mes_ano}

> [!IMPORTANT]
> **Fecha de emisión:** {report.fecha}
> **NAV:** `{eur(report.nav_total_eur)}` | **Liquidez objetivo:** `{report.peso_cash_objetivo_pct:.2f}% ({eur(report.cash_objetivo_eur)})`
> Todos los importes en **EUR**. Los precios de stop y target van en la divisa
> de cotización de cada activo.
{seccion_avisos}
---

## 🌍 1. Diagnóstico

### Régimen Macro
{report.regimen_macro}

### Geopolítica y Cadenas de Suministro
{report.geopolitica_resumen}

### Sentimiento e Inercias
{report.sentimiento_resumen}

---
{seccion_incumplimientos}
## 🎯 2. Lista Maestra de Acciones: Día 1

### 🔴 Ventas y Reducciones

| Activo | Acción | % Actual | % Objetivo | Importe a Liberar | Motivo |
| :--- | :--- | ---: | ---: | ---: | :--- |
{t_ventas}

### 🟢 Compras y Ampliaciones

| Activo | Acción | % Actual | % Objetivo | Importe a Invertir | Títulos Est. | Stop Loss | Target | Motivo |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
{t_compras}

---

## 💼 3. Composición Objetivo

```text
Liquidez (Cash)      : {report.peso_cash_objetivo_pct:6.2f}%  ({report.cash_objetivo_eur:>10,.2f} €)
Renta Variable/Activos: {pct_equity:6.2f}%  ({equity_eur:>10,.2f} €)
```

| Activo | Sector | Peso Objetivo | Capital | Convicción |
| :--- | :--- | ---: | ---: | ---: |
{t_objetivo}

---

## 🛡️ 4. Validación del RiskGovernor

Verificado de forma determinista contra [[Reglas_De_Supervivencia]]:

* Máximo por activo: **{MAX_POSITION_SIZE_PCT:.1f}%** del NAV.
* Máximo por sector: **{MAX_SECTOR_SIZE_PCT:.1f}%** del NAV.
* Liquidez mínima: **{MIN_CASH_PCT:.1f}%** del NAV.
* Ratio R:R mínimo exigido en toda compra nueva.

*⚠️ junto a un activo = precio no fiable; verificar antes de ejecutar.*

---

## 🔗 Enlaces del Grafo

* MOC: [[08_Rebalanceos_Mensuales]] | Cartera: [[Cartera_Real]]
* Mandato: [[Mandato_Institucional]], [[Reglas_De_Supervivencia]]
* Tesis: [[01_Tesis_Activas]] | Riesgo: [[Politica_Control_Riesgo]], [[Estado_Vital]]
"""
        file_path.write_text(self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "08_Rebalanceos_Mensuales",
            "## 📋 Informes de Rebalanceo Emitidos",
            f"* 📅 [[{file_path.stem}]] ({report.mes_ano})",
        )
        return file_path

    # ------------------------------------------------------------------
    # Diario
    # ------------------------------------------------------------------
    def write_daily_journal(
        self,
        date_str: str,
        summary: str,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation] = None,
        events: str = "",
        inteligencia_simulada: bool = False,
    ) -> Path:
        file_path = self.vault_path / "05_Diario_Reflexion" / f"{date_str}_Cierre_Mercado.md"

        meta = {
            "fecha": date_str,
            "estado_vital": health.estado_vital.value,
            "nav_eur": round(health.nav_actual_eur, 2),
            "salud_al_cierre": round(health.salud_porcentaje, 2),
            "energia_al_cierre": round(health.energia_actual, 2),
            "drawdown_actual_pct": round(health.drawdown_actual_pct, 2),
            "cobertura_datos_pct": round(health.cobertura_datos_pct, 2),
            "inteligencia_simulada": inteligencia_simulada,
            "eventos_clave": events or "Revisión diaria del ciclo de mercado",
        }

        aviso = ""
        if inteligencia_simulada:
            aviso = (
                "\n> [!WARNING]\n"
                "> **Análisis generado en modo simulación**, no por Claude. Es texto\n"
                "> de plantilla sin capacidad de razonamiento sobre los datos de hoy.\n"
                "> Configura `ANTHROPIC_API_KEY` en `.env` para obtener análisis real.\n"
            )

        seccion_cartera = ""
        if valuation:
            top = sorted(valuation.posiciones, key=lambda p: -abs(p.pnl_pct))[:5]
            filas = "\n".join(
                f"| {self.enlace(p.ticker, p.nota_activo)} | {p.valor_mercado_eur:,.2f} € | "
                f"{p.pnl_eur:+,.2f} € | {p.pnl_pct:+.2f}% |"
                for p in top
            )
            seccion_cartera = f"""
## 3. Mayores Movimientos de la Cartera

| Activo | Valor | PnL | PnL % |
| :--- | ---: | ---: | ---: |
{filas}

---
"""

        cuerpo = f"""# 📓 Diario de Reflexión e Inteligencia: {date_str}
{aviso}
---

## 1. Monitor de Mercado, Macro y Geopolítica

{summary}

---

## 2. Auditoría de Supervivencia

* **Estado Vital:** `{health.estado_vital.value}` (salud {health.salud_porcentaje:.1f}%)
* **Energía Metabólica:** `{health.energia_actual:.1f} / 100.0`
* **NAV:** `{eur(health.nav_actual_eur)}` (máximo histórico `{eur(health.nav_maximo_historico_eur)}`)
* **Drawdown Actual:** `{health.drawdown_actual_pct:.2f}%`
* **PnL sobre Referencia:** `{health.pnl_total_eur:+,.2f} € ({health.pnl_total_pct:+.2f}%)`
* **Cobertura de Datos:** `{health.cobertura_datos_pct:.1f}%`

---
{seccion_cartera}
## 4. Disciplina Operativa

No se opera por impulso durante el mes. La evidencia se canaliza al
**Rebalanceo del Día 1** ([[08_Rebalanceos_Mensuales]]) y a las alertas de
oportunidad ([[09_Alertas_Oportunidades]]). Única excepción intrames: el
stop-loss de emergencia.

---

## 🔗 Enlaces del Grafo

* MOC: [[05_Diario_Reflexion]] | Cartera: [[Cartera_Real]] | Estado: [[Estado_Vital]]
* Mandato: [[Mandato_Institucional]], [[Reglas_De_Supervivencia]]
* Departamentos: [[01_Departamento_Macro]], [[02_Analisis_Fundamental]], [[03_Mesa_Cuantitativa_Riesgo]], [[04_Sentimiento_Y_Flujos]]
"""
        file_path.write_text(self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc("05_Diario_Reflexion", "## 📋 Entradas del Diario", f"* 📓 [[{file_path.stem}]]")
        return file_path

    # ------------------------------------------------------------------
    # MOCs
    # ------------------------------------------------------------------
    def _append_to_moc(self, carpeta: str, encabezado: str, linea: str) -> None:
        """Inserta un enlace bajo un encabezado del MOC, sin duplicar."""
        moc_path = self.vault_path / carpeta / f"{carpeta}.md"
        if not moc_path.exists():
            return
        texto = moc_path.read_text(encoding="utf-8")
        if linea.strip() in texto:
            return
        if encabezado in texto:
            texto = texto.replace(encabezado, f"{encabezado}\n\n{linea}", 1)
        else:
            texto = texto.rstrip() + f"\n\n{encabezado}\n\n{linea}\n"
        moc_path.write_text(texto, encoding="utf-8")
