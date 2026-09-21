"""
Gestor de la Bóveda de Obsidian.

Lee y escribe notas Markdown con frontmatter YAML. Regla transversal: si un
informe se apoya en datos no fiables (precios de referencia, posiciones
valoradas a coste, análisis simulado), la nota lo declara de forma visible.
"""

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta

import yaml

from sharky.atomic_io import atomic_write_text
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
    LevelAlert,
    LevelKind,
    MonthlyRebalanceReport,
    OpportunityAlert,
    OrderType,
    PortfolioValuation,
    Position,
    PriceSource,
    RebalanceAction,
    RiskBreach,
    TradeOrder,
    VitalState,
)
from sharky.config import VAULT_PATH
from sharky.level_watch import texto as texto_nivel
from sharky.claude_client import (
    CONCLUSION_EXPLORACION,
    CONCLUSION_SEMANA,
    IntelligenceResult,
    extraer_conclusion,
)
from sharky.news_scanner import NewsScanResult

if TYPE_CHECKING:  # sólo para las anotaciones: no carga esos módulos
    from sharky.market_explorer import MarketExplorationResult
    from sharky.thesis_review import ThesisVerdict

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
            "04_Sentimiento_Y_Flujos/Noticias_Semanales",
            "05_Diario_Reflexion",
            "06_Lecciones_Aprendidas",
            "07_Plantillas",
            "08_Rebalanceos_Mensuales",
            "09_Alertas_Oportunidades",
            "09_Alertas_Oportunidades/Exploraciones",
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

        Sin fichero o sin metadatos legibles, `ultima_actualizacion` y
        `ultimo_ciclo_diario` se fijan a `datetime.min` (no al modelo por
        defecto, que sería "ahora"): así una bóveda nueva nunca se confunde
        con "el ciclo de hoy ya se ejecutó".
        """
        if not self.health_path.exists():
            return HealthStatus(ultima_actualizacion=datetime.min, ultimo_ciclo_diario=datetime.min)

        meta, _ = self.parse_markdown(self.health_path.read_text(encoding="utf-8"))
        if not meta:
            return HealthStatus(ultima_actualizacion=datetime.min, ultimo_ciclo_diario=datetime.min)

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

        # Igual que `ultima_actualizacion`, pero sólo lo escribe `run_daily_cycle`
        # (ver `update_health_status`): es lo que decide si el ciclo de hoy ya
        # corrió, sin que una operación registrada de por medio lo confunda.
        ultimo_ciclo_diario = datetime.min
        crudo_ciclo = meta.get("ultimo_ciclo_diario")
        if crudo_ciclo:
            try:
                ultimo_ciclo_diario = datetime.fromisoformat(str(crudo_ciclo))
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
            ultimo_ciclo_diario=ultimo_ciclo_diario,
        )

    def update_health_status(
        self,
        health: HealthStatus,
        valuation: Optional[PortfolioValuation] = None,
        incumplimientos: Optional[List[RiskBreach]] = None,
        alertas_niveles: Optional[List[LevelAlert]] = None,
        extra_summary: str = "",
        ciclo_diario: bool = False,
    ) -> Path:
        """Reescribe el cuadro de mandos Estado_Vital.md.

        `ciclo_diario=True` sólo lo pasa `run_daily_cycle`: es la única
        llamada que debe marcar "el ciclo de hoy ya se ejecutó"
        (`ultimo_ciclo_diario`). Cualquier otra escritura -- p.ej.
        `TradeRecorder` tras registrar una operación -- preserva el valor
        anterior tal cual (ver CICLO-2).
        """
        alertas = self.list_active_alerts()
        incumplimientos = incumplimientos or []
        alertas_niveles = alertas_niveles or []

        ultimo_ciclo_previo = "1970-01-01T00:00:00"
        if self.health_path.exists():
            meta_previo, _ = self.parse_markdown(self.health_path.read_text(encoding="utf-8"))
            ultimo_ciclo_previo = str(
                (meta_previo or {}).get("ultimo_ciclo_diario", ultimo_ciclo_previo)
            )

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
            "stops_alcanzados": sum(
                1 for a in alertas_niveles if a.tipo is LevelKind.STOP_LOSS
            ),
            "targets_alcanzados": sum(
                1 for a in alertas_niveles if a.tipo is LevelKind.TAKE_PROFIT
            ),
            "niveles_no_verificables": sum(
                1 for a in alertas_niveles if a.tipo is LevelKind.NO_VERIFICABLE
            ),
            "incumplimientos_activos": len(incumplimientos),
            "incumplimientos_escalados": len(escaladas),
            "incumplimientos_desde": antiguedad,
            "ultima_actualizacion": datetime.now().isoformat(),
            "ultimo_ciclo_diario": (
                datetime.now().isoformat() if ciclo_diario else ultimo_ciclo_previo
            ),
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

        if alertas_niveles:
            secciones.append(self._render_levels_section(alertas_niveles))

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
        atomic_write_text(self.health_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
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

    def _render_levels_section(self, alertas: List[LevelAlert]) -> str:
        """Sección de niveles alcanzados del cuadro de mandos.

        Va por delante de los incumplimientos del mandato porque un stop
        cruzado es la única cosa de esta nota que exige actuar hoy: un tope
        de concentración excedido se corrige en el rebalanceo, un stop no.
        """
        stops = [a for a in alertas if a.tipo is LevelKind.STOP_LOSS]
        targets = [a for a in alertas if a.tipo is LevelKind.TAKE_PROFIT]
        mudos = [a for a in alertas if a.tipo is LevelKind.NO_VERIFICABLE]

        bloques: List[str] = []

        if stops:
            detalle = "\n".join(f"> - {texto_nivel(a, self.enlace)}" for a in stops)
            bloques.append(
                "> [!DANGER] Salida obligatoria\n"
                f"> **{len(stops)} posición(es) han cruzado su stop-loss.** El mandato "
                "no admite discreción aquí: se liquidan.\n"
                f"{detalle}"
            )

        if targets:
            detalle = "\n".join(f"> - {texto_nivel(a, self.enlace)}" for a in targets)
            bloques.append(
                "> [!TIP] Objetivo alcanzado\n"
                f"> **{len(targets)} posición(es) han alcanzado su target.** Esto NO obliga "
                "a vender: el stop propuesto deja correr la posición sin arriesgar el "
                "principal ya ganado.\n"
                f"{detalle}"
            )

        if mudos:
            detalle = "\n".join(f"> - {texto_nivel(a, self.enlace)}" for a in mudos)
            bloques.append(
                "> [!WARNING] Niveles sin verificar\n"
                f"> **{len(mudos)} tesis no se han podido comprobar hoy.** Que no aparezca "
                "un aviso no significa que el nivel no se haya cruzado.\n"
                f"{detalle}"
            )

        cuerpo = "\n\n".join(bloques)
        return f"## 🎯 Niveles Alcanzados ({len(stops)} stop / {len(targets)} target)\n\n{cuerpo}"

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

    def leer_ultimas_noticias_semanales(self) -> Optional[Dict[str, Any]]:
        """Último escaneo de noticias: fecha, disponibilidad y resumen por activo.

        Es la base con la que `SharkyAgent.noticias_semanales_pendiente`
        decide si toca lanzar el escaneo de esta semana, y también el
        contexto que recibe el Comité de Inversión (el estudio mensual lee
        todas las semanas del mes con `leer_noticias_semanales`), para que
        las noticias reales pesen en sus lecturas, no sólo queden archivadas
        en `Noticias_Semanales/` sin que nadie las use. `resumen` es sólo la
        sección "1. Resumen por Activo"
        del cuerpo -- sin las fuentes citadas ni los enlaces del grafo, que
        no aportan nada a un prompt y sólo gastarían tokens.
        """
        carpeta = self.vault_path / "04_Sentimiento_Y_Flujos" / "Noticias_Semanales"
        if not carpeta.exists():
            return None
        elegido: Optional[Dict[str, Any]] = None
        for file in carpeta.glob("*_Noticias_Semanales.md"):
            try:
                meta, cuerpo = self.parse_markdown(file.read_text(encoding="utf-8"))
            except OSError:
                continue
            try:
                fecha = datetime.strptime(str(meta.get("fecha", "")), "%Y-%m-%d").date()
            except ValueError:
                continue
            if elegido is None or fecha > elegido["fecha"]:
                elegido = {
                    "fecha": fecha,
                    "disponible": bool(meta.get("disponible", True)),
                    "resumen": self._extraer_resumen_noticias(cuerpo),
                }
        return elegido

    def leer_noticias_semanales(self, dias: int) -> List[Dict[str, Any]]:
        """Escaneos semanales de los últimos `dias` días, del más antiguo al
        más reciente. Es el contexto de noticias del estudio mensual: todas
        las semanas del mes, no sólo la última."""
        carpeta = self.vault_path / "04_Sentimiento_Y_Flujos" / "Noticias_Semanales"
        if dias <= 0 or not carpeta.exists():
            return []
        corte = date.today() - timedelta(days=dias)
        escaneos: List[Dict[str, Any]] = []
        for file in carpeta.glob("*_Noticias_Semanales.md"):
            try:
                meta, cuerpo = self.parse_markdown(file.read_text(encoding="utf-8"))
                fecha = datetime.strptime(str(meta.get("fecha", "")), "%Y-%m-%d").date()
            except (OSError, ValueError):
                continue
            if fecha < corte:
                continue
            escaneos.append({
                "fecha": fecha,
                "disponible": bool(meta.get("disponible", True)),
                "resumen": self._extraer_resumen_noticias(cuerpo),
                "conclusion": str(meta.get("conclusion_semana") or ""),
            })
        escaneos.sort(key=lambda e: e["fecha"])
        return escaneos

    def leer_ultima_fecha_noticias_semanales(self) -> Optional[date]:
        """Sólo la fecha del último escaneo. Ver `leer_ultimas_noticias_semanales`."""
        elegido = self.leer_ultimas_noticias_semanales()
        return elegido["fecha"] if elegido else None

    @staticmethod
    def _extraer_resumen_noticias(cuerpo: str) -> str:
        """Aísla la sección "1. Resumen por Activo" del cuerpo de la nota."""
        inicio = cuerpo.find("## 1. Resumen por Activo")
        if inicio == -1:
            return cuerpo.strip()
        fin = cuerpo.find("## 2. Fuentes Citadas", inicio)
        fragmento = cuerpo[inicio:fin if fin != -1 else None]
        return fragmento.replace("## 1. Resumen por Activo", "", 1).strip()

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

    def leer_fechas_revision_tesis(self) -> Dict[str, str]:
        """Ticker -> `fecha_revision` de cada tesis activa que la tenga.

        Es lo que alimenta la red de seguridad de `thesis_review.seleccionar`:
        una tesis que nadie ha mirado en meses entra a revisión aunque no se
        haya movido.
        """
        fechas: Dict[str, str] = {}
        for file in sorted((self.vault_path / "01_Tesis_Activas").glob("*.md")):
            try:
                meta, _ = self.parse_markdown(file.read_text(encoding="utf-8"))
            except OSError:
                continue
            ticker = str((meta or {}).get("ticker", "")).strip().upper()
            revision = (meta or {}).get("fecha_revision")
            if ticker and revision:
                fechas[ticker] = str(revision)
        return fechas

    # ------------------------------------------------------------------
    # Revisión de tesis
    # ------------------------------------------------------------------
    # Campos del frontmatter que una revisión NO puede tocar jamás. El stop es
    # la única salida obligatoria del mandato y `level_watch` lo compara cada
    # día contra el precio real; `conviccion` ordena los candidatos de compra
    # del motor de rebalanceo. Si una revisión mensual pudiera reescribirlos,
    # una posición que se acerca a su stop recibiría uno más bajo cada mes con
    # una justificación impecable. La revisión propone; los aplica una persona.
    CAMPOS_INTOCABLES = (
        "ticker", "estado", "tipo", "divisa", "precio_entrada", "stop_loss",
        "target_precio", "conviccion", "ratio_rr", "unidades", "fecha_apertura",
    )

    # Únicos campos que la revisión escribe.
    CAMPOS_DE_REVISION = ("fecha_revision", "veredicto_revision")

    def anotar_revision_tesis(
        self,
        ruta: Path,
        veredicto: "ThesisVerdict",
        fecha_str: str,
        motivos: Optional[List[str]] = None,
    ) -> Path:
        """Apila una revisión fechada sobre una tesis, sin borrar nada.

        La nota crece hacia abajo: lo que se escribió en su día se conserva
        intacto y encima se apila lo que se piensa hoy. Esa acumulación es el
        punto -- la única pregunta que enseña algo es *¿tenía razón mi tesis
        de agosto?*, y no se puede responder si la tesis de agosto ya no
        existe.

        El frontmatter se edita como TEXTO, no reserializando el YAML: así
        toda línea que esta función no escribe queda byte a byte idéntica, en
        vez de "sólo" numéricamente equivalente (un round-trip convierte
        `3.141590` en `3.14159`). Sobre esa base, `CAMPOS_INTOCABLES` se
        comprueba además de forma explícita: una regresión futura que
        intentara mover un stop desde aquí levanta una excepción en vez de
        asentarlo en silencio.
        """
        original = ruta.read_text(encoding="utf-8")
        meta_previa, _ = self.parse_markdown(original)

        casada = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", original, re.DOTALL)
        if not casada:
            raise ValueError(f"{ruta.name}: la nota no tiene frontmatter que anotar")
        apertura, frontmatter, cierre, cuerpo = casada.groups()

        frontmatter_nuevo = self._fijar_clave(frontmatter, "fecha_revision", fecha_str)
        frontmatter_nuevo = self._fijar_clave(
            frontmatter_nuevo, "veredicto_revision", veredicto.veredicto
        )

        nuevo = (
            apertura + frontmatter_nuevo + cierre
            + self._con_seccion_revision(cuerpo, veredicto, fecha_str, motivos)
        )

        meta_nueva, _ = self.parse_markdown(nuevo)
        self._comprobar_campos_intocables(ruta, meta_previa, meta_nueva)

        atomic_write_text(ruta, nuevo, encoding="utf-8")
        return ruta

    @classmethod
    def _comprobar_campos_intocables(
        cls, ruta: Path, previa: Dict[str, Any], nueva: Dict[str, Any]
    ) -> None:
        cambiados = [
            campo for campo in cls.CAMPOS_INTOCABLES
            if previa.get(campo) != nueva.get(campo)
        ]
        if cambiados:
            raise ValueError(
                f"{ruta.name}: una revisión ha intentado modificar "
                f"{', '.join(cambiados)}. Esos campos sólo los cambia una persona."
            )

    @staticmethod
    def _fijar_clave(frontmatter: str, clave: str, valor: str) -> str:
        """Fija `clave: valor` en el frontmatter, sin tocar el resto del texto.

        Sólo se usa con claves de valor escalar en la misma línea
        (`CAMPOS_DE_REVISION`): sustituir una clave cuyo valor fuera una lista
        de varias líneas dejaría los elementos huérfanos.
        """
        patron = re.compile(rf"^{re.escape(clave)}:[^\n]*$", re.MULTILINE)
        linea = f"{clave}: {valor}"
        if patron.search(frontmatter):
            return patron.sub(linea, frontmatter, count=1)
        return frontmatter.rstrip("\n") + "\n" + linea

    @staticmethod
    def _con_seccion_revision(
        cuerpo: str,
        veredicto: "ThesisVerdict",
        fecha_str: str,
        motivos: Optional[List[str]] = None,
    ) -> str:
        """Inserta la sección antes de los enlaces del grafo, o al final."""
        iconos = {
            "MANTENER": "\U0001f7e2", "AMPLIAR": "\U0001f535",
            "REDUCIR": "\U0001f7e1", "CERRAR": "\U0001f534",
        }
        motivo = (
            f"> Seleccionada para revisión porque: {', '.join(motivos)}.\n\n"
            if motivos else ""
        )
        propuesta = ""
        if veredicto.propuesta_niveles.strip():
            propuesta = (
                "\n> [!WARNING]\n"
                "> **Propuesta de niveles — NO aplicada.** "
                f"{veredicto.propuesta_niveles.strip()}\n"
                "> Los niveles de este frontmatter sólo los cambia una persona: "
                "revisa la propuesta y edítalos tú si estás de acuerdo.\n"
            )

        seccion = f"""## \U0001f504 Revisión {fecha_str} — {iconos.get(veredicto.veredicto, '')} {veredicto.veredicto}

{motivo}**Qué ha cambiado:** {veredicto.que_ha_cambiado.strip() or "_Sin cambios relevantes registrados._"}

**Qué sigue en pie:** {veredicto.que_sigue_en_pie.strip() or "_Sin detallar._"}

**Qué la invalidaría ahora:** {veredicto.que_la_invalidaria.strip() or "_Sin detallar._"}
{propuesta}"""

        return VaultManager._insertar_antes_del_grafo(cuerpo, seccion)

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
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "09_Alertas_Oportunidades",
            "## 🔥 Alertas Activas en Radar",
            f"* 🚨 [[{file_path.stem}]] — **{alert.empresa}** ({alert.ticker})",
        )
        return file_path

    # ------------------------------------------------------------------
    # Exploraciones de mercado
    # ------------------------------------------------------------------
    def write_market_exploration(
        self,
        fecha_str: str,
        resultado: "MarketExplorationResult",
        diagnostico: List[Dict[str, str]],
        alertas_emitidas: List[OpportunityAlert],
    ) -> Path:
        """Registra una exploración de mercado con el veredicto de cada candidato.

        La nota guarda por separado y a la vista las dos mitades del proceso:
        la tesis cualitativa que propuso Claude y lo que el filtro
        cuantitativo dijo de cada candidato con precios reales. Una
        exploración con ocho candidatos y cero alertas es un resultado
        legítimo -- la empresa puede ser excelente y su precio no ofrecer
        asimetría hoy -- y esta tabla es lo que impide leerlo como un fallo.
        """
        file_path = (
            self.vault_path / "09_Alertas_Oportunidades" / "Exploraciones"
            / f"{fecha_str}_Exploracion_Mercado.md"
        )

        propuestos = [c.ticker for c in resultado.candidatos]
        emitidas = [a.ticker for a in alertas_emitidas]

        meta = {
            "tipo": "exploracion_mercado",
            "fecha": fecha_str,
            "modelo": resultado.modelo,
            "disponible": resultado.disponible,
            "busquedas_realizadas": resultado.busquedas_realizadas,
            "candidatos_propuestos": len(propuestos),
            "alertas_emitidas": len(emitidas),
            "tickers_propuestos": propuestos,
            "tickers_alertados": emitidas,
            "conclusion_exploracion": (
                extraer_conclusion(resultado.texto, CONCLUSION_EXPLORACION)
                if resultado.disponible else ""
            ),
        }

        aviso = ""
        if not resultado.disponible:
            aviso = (
                "\n> [!WARNING]\n"
                "> **Exploración no disponible.** "
                f"{resultado.error or 'Sin más detalle.'} Configura "
                "`ANTHROPIC_API_KEY` en `.env` para que la búsqueda se ejecute.\n"
            )
        elif resultado.aviso_parseo:
            aviso = (
                "\n> [!WARNING]\n"
                f"> **No se pudo leer la lista de candidatos:** {resultado.aviso_parseo}.\n"
                "> El informe de abajo sigue siendo válido, pero ningún candidato pasó "
                "por el filtro cuantitativo y no se ha emitido ninguna alerta.\n"
            )

        fuentes_md = "\n".join(f"- {f}" for f in resultado.fuentes) or "- Sin fuentes citadas."

        cuerpo = f"""# 🔭 Exploración de Mercado: {fecha_str}

> [!INFO]
> **Búsqueda activa de oportunidades fuera del universo de vigilancia.**
> **Candidatos propuestos:** `{len(propuestos)}` | **Confirmados por datos:** `{len(emitidas)}` | **Búsquedas web:** `{resultado.busquedas_realizadas}`
{aviso}
---

## 1. Candidatos Propuestos

{resultado.texto or "_Sin informe._"}

---

## 2. Veredicto Cuantitativo

> La convicción de arriba es cualitativa. Esta tabla es lo que dicen los
> precios reales: se aplican los mismos umbrales que a cualquier otra alerta
> ([[09_Alertas_Oportunidades]]). Un `NO CUALIFICA` no descarta la empresa,
> descarta su precio de hoy.

{self._tabla_diagnostico(diagnostico)}

---

## 3. Alertas Emitidas

{self._lista_alertas_emitidas(alertas_emitidas)}

---

## 4. Fuentes Citadas

{fuentes_md}

---

## 🔗 Enlaces del Grafo

* MOC: [[09_Alertas_Oportunidades]] | Cartera: [[Cartera_Real]]
* Riesgo: [[Politica_Control_Riesgo]] | Rebalanceo: [[08_Rebalanceos_Mensuales]]
"""
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "09_Alertas_Oportunidades",
            "## 🔭 Exploraciones de Mercado",
            f"* 🔭 [[{file_path.stem}]] — {len(propuestos)} candidato(s), "
            f"{len(emitidas)} alerta(s)",
        )
        return file_path

    @staticmethod
    def _tabla_diagnostico(diagnostico: List[Dict[str, str]]) -> str:
        """Traza del filtro cuantitativo, un candidato por fila."""
        if not diagnostico:
            return "_No se evaluó ningún candidato._"
        iconos = {
            "ALERTA": "🚨", "NO CUALIFICA": "⚪", "SIN DATOS": "❓",
            "OMITIDO": "↩️", "DESCARTADO": "🚫",
        }
        filas = "\n".join(
            f"| {iconos.get(d['veredicto'], '·')} `{d['ticker']}` | "
            f"**{d['veredicto']}** | {d['detalle']} |"
            for d in diagnostico
        )
        return (
            "| Candidato | Veredicto | Motivo |\n"
            "| :--- | :--- | :--- |\n"
            f"{filas}"
        )

    def _lista_alertas_emitidas(self, alertas: List[OpportunityAlert]) -> str:
        if not alertas:
            return (
                "_Ningún candidato superó el filtro cuantitativo, así que no se ha "
                "emitido ninguna alerta. La exploración queda como registro de ideas "
                "para volver a mirarlas cuando el precio acompañe._"
            )
        return "\n".join(
            f"* 🚨 **{a.empresa}** ({self.enlace(a.ticker)}) — convicción "
            f"`{a.conviccion}/10`, R:R `{a.ratio_rr:.2f}:1`, potencial "
            f"`+{a.potencial_ganancia_pct:.1f}%` frente a `-{a.riesgo_maximo_pct:.1f}%`."
            for a in alertas
        )

    def leer_ultima_exploracion(self) -> Optional[Dict[str, Any]]:
        """Frontmatter de la exploración de mercado más reciente, si la hay.

        La usa la app para enseñar en el radar cuándo se exploró por última
        vez y con qué resultado, igual que la tarjeta de noticias usa
        `leer_ultimas_noticias_semanales`.
        """
        carpeta = self.vault_path / "09_Alertas_Oportunidades" / "Exploraciones"
        if not carpeta.exists():
            return None
        elegido: Optional[Dict[str, Any]] = None
        for file in carpeta.glob("*_Exploracion_Mercado.md"):
            try:
                meta, _ = self.parse_markdown(file.read_text(encoding="utf-8"))
                fecha = datetime.strptime(str(meta.get("fecha", "")), "%Y-%m-%d").date()
            except (OSError, ValueError):
                continue
            if elegido is None or fecha > elegido["fecha"]:
                elegido = {
                    "fecha": fecha,
                    "id": file.relative_to(self.vault_path).as_posix(),
                    "disponible": bool(meta.get("disponible", True)),
                    "modelo": str(meta.get("modelo") or ""),
                    "candidatos": int(meta.get("candidatos_propuestos") or 0),
                    "alertas": int(meta.get("alertas_emitidas") or 0),
                    "conclusion": str(meta.get("conclusion_exploracion") or ""),
                }
        return elegido

    # ------------------------------------------------------------------
    # Ciclo de vida de una tesis
    # ------------------------------------------------------------------
    # Una tesis nace de una alerta ejecutada y muere en la venta que cierra la
    # posición. Hasta 2026-09 no hacía ninguna de las dos cosas sola, y la
    # segunda omisión tenía consecuencias: una tesis sin posición abierta entra
    # en `MonthlyRebalanceEngine._candidatos` como candidata de COMPRA, así que
    # vender por stop dejaba viva una tesis que el Día 1 siguiente proponía
    # recomprar -- con la convicción intacta y unos niveles que el mercado
    # acababa de demostrar falsos.
    #
    # A diferencia de la revisión mensual, aquí sí se cambia `estado`: cerrar
    # una tesis no es un juicio del modelo sino un hecho contable (vendiste).
    # La prosa, en cambio, sigue la misma regla que la revisión -- se apila una
    # sección de cierre, no se reescribe nada.
    def buscar_tesis(self, ticker: str, carpeta: str = "01_Tesis_Activas") -> Optional[Path]:
        """Ruta de la nota de tesis de `ticker`, si existe en esa carpeta."""
        clave = (ticker or "").upper().strip()
        if not clave:
            return None
        for file in sorted((self.vault_path / carpeta).glob("*.md")):
            if file.stem == file.parent.name:
                continue
            try:
                meta, _ = self.parse_markdown(file.read_text(encoding="utf-8"))
            except OSError:
                continue
            if str((meta or {}).get("ticker", "")).upper().strip() == clave:
                return file
        return None

    def cerrar_tesis(
        self,
        ticker: str,
        fecha_str: str,
        pnl_realizado_eur: Optional[float] = None,
        motivo: str = "",
        precio_salida: Optional[float] = None,
        divisa: str = "",
    ) -> Optional[Path]:
        """Archiva la tesis de `ticker` en `02_Tesis_Cerradas`.

        Devuelve la ruta nueva, o None si esa tesis no existía (posición sin
        tesis documentada: es legítimo y no debe romper el registro de una
        venta real).
        """
        origen = self.buscar_tesis(ticker)
        if origen is None:
            return None

        original = origen.read_text(encoding="utf-8")
        casada = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", original, re.DOTALL)
        if not casada:
            return None
        apertura, frontmatter, cierre, cuerpo = casada.groups()

        frontmatter = self._fijar_clave(frontmatter, "estado", "Cerrada")
        frontmatter = self._fijar_clave(frontmatter, "fecha_cierre", fecha_str)
        frontmatter = self._fijar_clave(frontmatter, "tiene_posicion", "false")
        if pnl_realizado_eur is not None:
            frontmatter = self._fijar_clave(
                frontmatter, "pnl_realizado_eur", f"{pnl_realizado_eur:.2f}"
            )

        resultado = ""
        if pnl_realizado_eur is not None:
            signo = "ganancia" if pnl_realizado_eur >= 0 else "pérdida"
            resultado = f"\n**Resultado realizado:** {pnl_realizado_eur:+,.2f} € ({signo})."
        salida = ""
        if precio_salida:
            salida = f"\n**Precio de salida:** {precio_salida:,.2f} {divisa or ''}".rstrip()

        seccion = f"""## \U0001f4c1 Cierre {fecha_str}

> Esta tesis está cerrada. Se conserva como registro: lo que se pensó al
> abrirla y en cada revisión sigue escrito arriba, sin tocar.

**Motivo:** {motivo or "venta registrada en la bitácora."}{resultado}{salida}

**Pendiente de post-mortem:** ¿qué parte de la tesis original se cumplió y
qué parte no? Si el cierre vino de un stop-loss, la lección va a
[[06_Lecciones_Aprendidas]] (ver el protocolo en [[02_Tesis_Cerradas]]).
"""

        nuevo = apertura + frontmatter + cierre + self._insertar_antes_del_grafo(cuerpo, seccion)

        destino = self.vault_path / "02_Tesis_Cerradas" / origen.name
        destino.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(destino, nuevo, encoding="utf-8")
        origen.unlink(missing_ok=True)

        self._retirar_de_moc("01_Tesis_Activas", origen.stem)
        self._append_to_moc(
            "02_Tesis_Cerradas",
            "## 📋 Registro Histórico de Tesis",
            f"* 📁 [[{destino.stem}]] — **{ticker}** cerrada el {fecha_str}"
            + (f" ({pnl_realizado_eur:+,.2f} €)" if pnl_realizado_eur is not None else ""),
        )
        return destino

    def crear_tesis_desde_alerta(
        self,
        alerta: OpportunityAlert,
        fecha_str: str,
        precio_entrada: float,
        divisa_entrada: str = "",
        stop_loss: float = 0.0,
        target_precio: float = 0.0,
        sector: str = "",
        id_operacion: str = "",
    ) -> Path:
        """Convierte una alerta ejecutada en tesis activa.

        La alerta ya traía `stop_loss`, `target_precio` y `ratio_rr` calculados
        con la estructura real de precios: sin este puente esos niveles se
        quedaban en la nota de la alerta y la posición recién comprada no tenía
        ningún stop que `level_watch` pudiera vigilar hasta que alguien
        escribiera la tesis a mano.

        Los niveles que se asientan son los de la ORDEN, no los de la alerta:
        si compraste a otro precio o con otro stop, manda lo que ejecutaste.
        """
        destino = self.vault_path / "01_Tesis_Activas" / f"Tesis_{alerta.ticker}.md"
        divisa = divisa_entrada or alerta.divisa
        stop = stop_loss or alerta.stop_loss
        target = target_precio or alerta.target_precio

        riesgo = precio_entrada - stop
        ratio = round((target - precio_entrada) / riesgo, 2) if riesgo > 0 else alerta.ratio_rr

        meta = {
            "ticker": alerta.ticker,
            "empresa": alerta.empresa,
            "tipo": "Largo",
            "estado": "Activa",
            "precio_entrada": round(precio_entrada, 4),
            "stop_loss": round(stop, 4),
            "target_precio": round(target, 4),
            "conviccion": alerta.conviccion,
            "ratio_rr": ratio,
            "fecha_apertura": fecha_str,
            "sectores": f"[[{sector}]]" if sector else "",
            "empresa_nota": f"[[{alerta.ticker}]]",
            "divisa": divisa,
            "tiene_posicion": True,
            "origen_alerta": alerta.id_alerta,
        }

        tesis, catalizadores, riesgos = self._secciones_de_alerta(
            alerta.descripcion_oportunidad
        )
        operacion = (
            f"\n* Operación de apertura: `{id_operacion}` ([[04_Operaciones_Bitacora]])"
            if id_operacion else ""
        )

        cuerpo = f"""# 🎯 Tesis de Inversión: {alerta.empresa} ({alerta.ticker})

> [!NOTE]
> **Tesis abierta desde una alerta del radar** (`{alerta.id_alerta}`), al
> registrar la compra del {fecha_str}. La convicción y el racional vienen de
> la alerta; los niveles, de la orden realmente ejecutada.

---

## 💡 Racional de Inversión

{tesis}

---

## 🚀 Catalizadores Principales

{catalizadores}

---

## ⚠️ Riesgos Monitoreados

{riesgos}

---

## 🛑 Plan de Riesgo y Salida

| Parámetro | Valor |
| :--- | ---: |
| **Entrada ejecutada** | `{precio_entrada:,.2f} {divisa}` |
| **Stop Loss Innegociable** | `{stop:,.2f} {divisa}` |
| **Target Objetivo** | `{target:,.2f} {divisa}` |
| **Ratio R:R** | `{ratio:.2f} : 1` |
| **Peso máximo en cartera** | `{alerta.pct_max_cartera:.1f}%` |

> El stop-loss es la única salida obligatoria del mandato: [[level_watch]] lo
> compara cada día contra el precio real ([[Reglas_De_Supervivencia]]).

---

## 🔗 Enlaces Bidireccionales del Grafo

* Ficha de Empresa: {self.enlace(alerta.ticker)}
* Alerta de origen: [[{alerta.fecha_deteccion}_ALERTA_{alerta.id_alerta}]]
* Cartera (fuente de verdad): [[Cartera_Real]]
* Validación de Riesgo: [[Politica_Control_Riesgo]], [[Reglas_De_Supervivencia]]
* MOC de Tesis: [[01_Tesis_Activas]]{operacion}
"""
        atomic_write_text(destino, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "01_Tesis_Activas",
            "## 📈 Tesis Vivas",
            f"* 🎯 [[{destino.stem}]] — **{alerta.empresa}** ({alerta.ticker})",
        )
        return destino

    @staticmethod
    def _secciones_de_alerta(cuerpo: str) -> Tuple[str, str, str]:
        """Aísla tesis, catalizadores y riesgos del cuerpo de una alerta.

        `list_active_alerts` reconstruye la alerta desde disco con el cuerpo
        entero en `descripcion_oportunidad` -- los catalizadores y los riesgos
        viven ahí como prosa, no como campos. Copiar el cuerpo completo a la
        tesis arrastraría tablas de precios ya caducadas, así que se extraen
        las tres secciones que sí son convicción.
        """
        def seccion(desde: str, hasta: str, defecto: str) -> str:
            i = cuerpo.find(desde)
            if i == -1:
                return defecto
            j = cuerpo.find(hasta, i)
            trozo = cuerpo[i + len(desde): j if j != -1 else None]
            return trozo.strip().strip("-").strip() or defecto

        # Una alerta recién construida en memoria (no releída de disco) trae su
        # racional como texto plano, sin los encabezados que escribe
        # `write_opportunity_alert`. En ese caso el cuerpo entero ES el
        # racional, y perderlo dejaría la tesis sin la convicción que la
        # justifica.
        sin_formato = "## " not in cuerpo
        defecto_tesis = cuerpo.strip() if sin_formato and cuerpo.strip() else (
            "_Racional heredado de la alerta._"
        )
        return (
            seccion("## 💎 1. Tesis Rápida", "## ⚡ 2.", defecto_tesis),
            seccion("## ⚡ 2. Catalizadores", "## 🎯 3.", "1. _Pendiente de detallar._"),
            seccion("## ⚠️ 4. Riesgos y Puntos Ciegos", "## 📌 5.", "* _Pendiente de detallar._"),
        )

    @staticmethod
    def _insertar_antes_del_grafo(cuerpo: str, seccion: str) -> str:
        """Inserta una sección antes de los enlaces del grafo, o al final."""
        marca = re.search(r"^## \U0001f517", cuerpo, re.MULTILINE)
        if marca:
            return (
                cuerpo[: marca.start()].rstrip("\n")
                + "\n\n" + seccion.rstrip("\n")
                + "\n\n---\n\n" + cuerpo[marca.start():]
            )
        return cuerpo.rstrip("\n") + "\n\n---\n\n" + seccion

    # ------------------------------------------------------------------
    # Ciclo de vida de una alerta
    # ------------------------------------------------------------------
    def marcar_alerta(
        self,
        alerta: OpportunityAlert,
        estado: AlertStatus,
        fecha_str: str,
        motivo: str = "",
    ) -> Optional[Path]:
        """Cierra una alerta con su estado y motivo, y la saca del radar activo.

        `AlertStatus` define EJECUTADA, DESCARTADA y EXPIRADA desde el
        principio, pero hasta 2026-09 nada las asignaba: toda alerta nacía
        ACTIVA y ahí se quedaba. Dos consecuencias, las dos silenciosas: el
        ticker quedaba vetado para siempre en `has_active_alert`, y la alerta
        seguía entrando cada mes en el rebalanceo con sus niveles congelados
        mientras el motor tomaba precio fresco.
        """
        carpeta = self.vault_path / "09_Alertas_Oportunidades"
        # El nombre canónico lo fija `write_opportunity_alert`; el barrido por
        # `id_alerta` cubre las notas heredadas de la versión anterior, que
        # seguían otra convención de nombre (`..._ALERTA_ASML_Monopolio_HighNA`).
        candidata: Optional[Path] = carpeta / (
            f"{alerta.fecha_deteccion}_ALERTA_{alerta.id_alerta}.md"
        )
        if candidata is not None and not candidata.exists():
            candidata = next(
                (
                    f for f in sorted(carpeta.glob("*.md"))
                    if self.parse_markdown(f.read_text(encoding="utf-8"))[0].get("id_alerta")
                    == alerta.id_alerta
                ),
                None,
            )
        if candidata is None or not candidata.exists():
            return None
        ruta = candidata

        original = ruta.read_text(encoding="utf-8")
        casada = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", original, re.DOTALL)
        if not casada:
            return None
        apertura, frontmatter, cierre, cuerpo = casada.groups()

        frontmatter = self._fijar_clave(frontmatter, "estado", estado.value)
        frontmatter = self._fijar_clave(frontmatter, "fecha_cierre_alerta", fecha_str)
        if motivo:
            frontmatter = self._fijar_clave(
                frontmatter, "motivo_cierre", yaml.safe_dump(motivo, allow_unicode=True).strip()
            )

        aviso = (
            f"\n> [!NOTE]\n"
            f"> **Alerta {estado.value} el {fecha_str}.** {motivo}\n"
            f"> Los niveles de abajo son los del día de emisión "
            f"(`{alerta.fecha_deteccion}`) y ya no se vigilan.\n"
        )
        # El aviso va arriba del todo: quien abra la nota tiene que ver que no
        # está viva antes de leer un precio de entrada que ya no sirve.
        cuerpo = re.sub(r"^(# .*\n)", r"\1" + aviso, cuerpo, count=1) or (aviso + cuerpo)

        atomic_write_text(ruta, apertura + frontmatter + cierre + cuerpo, encoding="utf-8")

        self._retirar_de_moc("09_Alertas_Oportunidades", ruta.stem)
        icono = {"EJECUTADA": "✅", "EXPIRADA": "⚪", "DESCARTADA": "🚫"}.get(estado.value, "·")
        self._append_to_moc(
            "09_Alertas_Oportunidades",
            "## 🗄️ Alertas Caducadas / Histórico",
            f"* {icono} [[{ruta.stem}]] — **{alerta.empresa}** ({alerta.ticker}) — "
            f"`{estado.value}` el {fecha_str}. {motivo}",
        )
        return ruta

    def _retirar_de_moc(self, carpeta: str, nombre_nota: str) -> None:
        """Borra del MOC la línea que enlaza a `nombre_nota`.

        Complementa a `_append_to_moc`: sin esto, una alerta caducada seguiría
        figurando bajo "Alertas Activas en Radar" además de aparecer en el
        histórico, y el MOC diría dos cosas contradictorias a la vez.
        """
        moc_path = self.vault_path / carpeta / f"{carpeta}.md"
        if not moc_path.exists():
            return
        texto = moc_path.read_text(encoding="utf-8")
        lineas = [
            linea for linea in texto.splitlines()
            if f"[[{nombre_nota}]]" not in linea
        ]
        nuevo = "\n".join(lineas)
        if nuevo != texto:
            atomic_write_text(moc_path, nuevo.rstrip() + "\n", encoding="utf-8")

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
            / f"{fecha}_{order.ticker}_{sentido}_{order.id_operacion}.md"
        )

        meta = {
            "tipo": "operacion",
            "id_operacion": order.id_operacion,
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
> **ID:** `{order.id_operacion}`
> **Ejecutada:** {order.fecha_ejecucion.strftime('%Y-%m-%d %H:%M:%S')}
> Sharky **no** envía órdenes al broker: esta nota registra una ejecución ya
> realizada en {self._custodio_hint()}. No existe modo simulación: toda
> entrada es una compra o venta real, asentada en [[Cartera_Real]].

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
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
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
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "08_Rebalanceos_Mensuales",
            "## 📋 Informes de Rebalanceo Emitidos",
            f"* 📅 [[{file_path.stem}]] ({report.mes_ano})",
        )
        return file_path

    # ------------------------------------------------------------------
    # Estudio mensual
    # ------------------------------------------------------------------
    def _ruta_estudio_mensual(self, mes: str) -> Path:
        """`mes` en formato `YYYY-MM`. Nombre de archivo = fuente de verdad
        de si el estudio de ese mes ya se hizo (ver `existe_estudio_mensual`)."""
        return self.vault_path / "08_Rebalanceos_Mensuales" / f"{mes}_Estudio_Mensual.md"

    def existe_estudio_mensual(self, mes: str) -> bool:
        return self._ruta_estudio_mensual(mes).exists()

    def leer_meta_estudio_mensual(self, mes: str) -> Dict[str, Any]:
        """Frontmatter del estudio de `mes`, o {} si no existe o no se lee."""
        ruta = self._ruta_estudio_mensual(mes)
        if not ruta.exists():
            return {}
        try:
            meta, _ = self.parse_markdown(ruta.read_text(encoding="utf-8"))
        except OSError:
            return {}
        return meta or {}

    def leer_conclusion_estudio_anterior(self, mes: str) -> str:
        """Conclusión del último estudio mensual anterior a `mes` (`YYYY-MM`).

        Da continuidad entre estudios: el de este mes puede comprobar si las
        decisiones del anterior funcionaron.
        """
        carpeta = self.vault_path / "08_Rebalanceos_Mensuales"
        anteriores = sorted(
            f for f in carpeta.glob("*_Estudio_Mensual.md") if f.name[:7] < mes
        ) if carpeta.exists() else []
        if not anteriores:
            return ""
        try:
            meta, _ = self.parse_markdown(anteriores[-1].read_text(encoding="utf-8"))
        except OSError:
            return ""
        return str(meta.get("conclusion_mes") or "")

    def write_monthly_study(
        self,
        mes: str,
        fecha_str: str,
        resultado: IntelligenceResult,
        health: HealthStatus,
        ruta_rebalanceo: Optional[Path] = None,
    ) -> Path:
        """Estudio mensual completo de la cartera, junto al plan del motor."""
        file_path = self._ruta_estudio_mensual(mes)

        meta = {
            "tipo": "estudio_mensual",
            "mes": mes,
            "fecha": fecha_str,
            "modelo": resultado.modelo,
            "inteligencia_simulada": resultado.simulado,
            "nav_eur": round(health.nav_actual_eur, 2),
            "drawdown_actual_pct": round(health.drawdown_actual_pct, 2),
            "conclusion_mes": resultado.conclusion.strip(),
        }

        aviso = ""
        if resultado.simulado:
            aviso = (
                "\n> [!WARNING]\n"
                "> **Estudio generado sin Claude.** No hay reevaluación de posiciones,\n"
                "> sólo el plan determinista del motor de rebalanceo.\n"
                + (f"> Error: `{resultado.error}`\n" if resultado.error else "")
            )

        enlace_plan = (
            f"[[{ruta_rebalanceo.stem}]]" if ruta_rebalanceo else "[[08_Rebalanceos_Mensuales]]"
        )

        cuerpo = f"""# 🧠 Estudio Mensual de la Cartera: {mes}
{aviso}
---

Plan del motor de rebalanceo contrastado en este estudio: {enlace_plan}

---

{resultado.texto}

---

## 🔗 Enlaces del Grafo

* MOC: [[08_Rebalanceos_Mensuales]] | Cartera: [[Cartera_Real]] | Estado: [[Estado_Vital]]
* Contexto del mes: [[05_Diario_Reflexion]], [[04_Sentimiento_Y_Flujos]]
* Mandato: [[Mandato_Institucional]], [[Reglas_De_Supervivencia]]
"""
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "08_Rebalanceos_Mensuales",
            "## 🧠 Estudios Mensuales",
            f"* 🧠 [[{file_path.stem}]]",
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
        conclusion: str = "",
        posiciones_a_vigilar: Optional[List[str]] = None,
    ) -> Path:
        """Control diario de la cartera.

        El frontmatter es lo que releen los niveles superiores (ver
        `leer_memoria_diario`): `conclusion_ia` para el escaneo semanal y el
        estudio mensual, `precios_eur` para que el control del día siguiente
        mida cuánto se ha movido cada posición, y `posiciones_a_vigilar` para
        que el escaneo semanal investigue primero lo que se movió con fuerza.
        """
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
            "conclusion_ia": conclusion.strip(),
            "posiciones_a_vigilar": list(posiciones_a_vigilar or []),
            # Sólo precios fiables: una referencia inventada no puede servir
            # de base para medir el movimiento de mañana.
            "precios_eur": {
                p.ticker: round(p.precio_unitario_eur, 6)
                for p in (valuation.posiciones if valuation else [])
                if p.fuente_precio.es_fiable
            },
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

## 1. Control Diario de la Cartera

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
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc("05_Diario_Reflexion", "## 📋 Entradas del Diario", f"* 📓 [[{file_path.stem}]]")
        return file_path

    # ------------------------------------------------------------------
    # Noticias semanales
    # ------------------------------------------------------------------
    def write_weekly_news_report(
        self,
        fecha_str: str,
        resultado: NewsScanResult,
        positions: List[Position],
    ) -> Path:
        """Registra el escaneo semanal de noticias de la cartera.

        A diferencia del diario, esta nota no lleva estado vital ni NAV: es
        un digest de lo que ha pasado esta semana en cada activo, con las
        fuentes citadas para poder verificarlo. `leer_ultima_fecha_noticias_semanales`
        vuelve a leer esta misma carpeta para saber cuándo tocó el último
        escaneo, así que el nombre de archivo (`{{fecha}}_Noticias_Semanales.md`)
        y el frontmatter `fecha` son la fuente de verdad, no un registro aparte.
        """
        file_path = (
            self.vault_path / "04_Sentimiento_Y_Flujos" / "Noticias_Semanales"
            / f"{fecha_str}_Noticias_Semanales.md"
        )

        meta = {
            "tipo": "noticias_semanales",
            "fecha": fecha_str,
            "activos": [p.ticker for p in positions],
            "modelo": resultado.modelo,
            "busquedas_realizadas": resultado.busquedas_realizadas,
            "disponible": resultado.disponible,
            # Lo que relee el estudio mensual además del resumen por activo.
            "conclusion_semana": (
                extraer_conclusion(resultado.texto, CONCLUSION_SEMANA) if resultado.disponible else ""
            ),
        }

        aviso = ""
        if not resultado.disponible:
            aviso = (
                "\n> [!WARNING]\n"
                "> **Escaneo no disponible esta semana.** "
                f"{resultado.error or 'Sin más detalle.'} Configura "
                "`ANTHROPIC_API_KEY` en `.env` para que el escaneo se ejecute.\n"
            )

        fuentes_md = "\n".join(f"- {f}" for f in resultado.fuentes) or "- Sin fuentes citadas."
        enlaces_activos = " | ".join(
            self.enlace(p.ticker, p.nota_activo) for p in positions
        ) or "Sin posiciones."

        cuerpo = f"""# 📰 Noticias Semanales de la Cartera: {fecha_str}
{aviso}
---

## 1. Resumen por Activo

{resultado.texto}

---

## 2. Fuentes Citadas

{fuentes_md}

---

## 🔗 Enlaces del Grafo

* MOC: [[04_Sentimiento_Y_Flujos]] | Cartera: [[Cartera_Real]]
* Activos: {enlaces_activos}
"""
        atomic_write_text(file_path, self.build_markdown(meta, cuerpo), encoding="utf-8")
        self._append_to_moc(
            "04_Sentimiento_Y_Flujos",
            "## 📰 Noticias Semanales",
            f"* 📰 [[{file_path.stem}]]",
        )
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
        atomic_write_text(moc_path, texto, encoding="utf-8")
