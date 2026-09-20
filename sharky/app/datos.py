"""
Datos que sirve la app: panel de control, listado de informes y notas.

Todo sale de las mismas piezas que usa la CLI (`SharkyAgent`,
`VaultManager`, `level_watch`): la app no tiene lógica de negocio propia,
sólo compone y serializa. Las funciones devuelven estructuras JSON-ables
(fechas en ISO) para que el servidor no tenga que saber nada de modelos.
"""

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from markdown_it import MarkdownIt

from sharky import level_watch
from sharky.config import (
    CLAUDE_MODEL,
    DEATH_DRAWDOWN_PCT,
    DRAWDOWN_ALERTA_MAX_PCT,
    DRAWDOWN_OPTIMO_MAX_PCT,
    EFFORT_DIARIO,
    EFFORT_MENSUAL,
    MAX_CASH_PCT,
    MAX_SECTOR_SIZE_PCT,
    MAX_TOKENS_COMITE,
    MAX_TOKENS_DIARIO,
    MAX_TOKENS_MENSUAL,
    MIN_CASH_PCT,
    NEWS_EFFORT,
    NEWS_MAX_TOKENS_INFORME,
    NEWS_MODEL,
    UMBRAL_MOVIMIENTO_VIGILANCIA_PCT,
    has_live_api_key,
)

# --------------------------------------------------------------------------
# Informes de la bóveda
# --------------------------------------------------------------------------
# tipo -> (carpeta relativa a la bóveda, patrón, título legible)
TIPOS_INFORME: Dict[str, tuple] = {
    "diario": ("05_Diario_Reflexion", "*_Cierre_Mercado.md", "Controles diarios"),
    "noticias": (
        "04_Sentimiento_Y_Flujos/Noticias_Semanales", "*_Noticias_Semanales.md", "Noticias semanales",
    ),
    "estudios": ("08_Rebalanceos_Mensuales", "*_Estudio_Mensual.md", "Estudios mensuales"),
    "rebalanceos": ("08_Rebalanceos_Mensuales", "*_Rebalanceo_*.md", "Planes de rebalanceo"),
    "operaciones": ("04_Operaciones_Bitacora", "*.md", "Operaciones"),
    "tesis": ("01_Tesis_Activas", "*.md", "Tesis activas"),
    "alertas": ("09_Alertas_Oportunidades", "*.md", "Alertas de oportunidad"),
}

_MD = MarkdownIt("commonmark", {"html": False, "typographer": False}).enable(["table", "strikethrough"])

# [[Destino]], [[Destino|Alias]], [[Destino\|Alias]] (escapado dentro de
# tablas) y [[Destino#Sección|Alias]]. Se aplica sobre el HTML ya generado:
# markdown-it escapa el texto, así que no hay que volver a escaparlo.
_WIKILINK = re.compile(r"\[\[([^\[\]|#]+?)(?:#[^\[\]|]*)?(?:\\?\|([^\[\]]+?))?\]\]")
_CALLOUT = re.compile(r"<blockquote>\s*<p>\[!(\w+)\]\s*")
# La CSP de la app bloquea `style=""`: la alineación de columnas de las
# tablas Markdown pasa a clases.
_ALINEACION = re.compile(r' style="text-align:(left|right|center)"')


def renderizar_markdown(texto: str) -> str:
    """Markdown de Obsidian -> HTML seguro (sin HTML crudo del documento)."""
    salida = _ALINEACION.sub(r' class="al-\1"', _MD.render(texto or ""))
    salida = _CALLOUT.sub(
        lambda m: f'<blockquote class="callout callout-{m.group(1).lower()}"><p>', salida
    )
    return _WIKILINK.sub(
        lambda m: (
            f'<a href="#" class="wikilink" data-nota="{m.group(1).strip()}">'
            f"{(m.group(2) or m.group(1)).strip()}</a>"
        ),
        salida,
    )


def _es_moc(ruta: Path) -> bool:
    """El MOC de cada carpeta se llama como la carpeta: no es un informe."""
    return ruta.stem == ruta.parent.name


def _titulo(meta: Dict[str, Any], cuerpo: str, ruta: Path) -> str:
    for linea in cuerpo.splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return str(meta.get("titulo") or ruta.stem.replace("_", " "))


def _etiquetas(tipo: str, meta: Dict[str, Any]) -> List[Dict[str, str]]:
    """Chips del listado: lo mínimo para decidir qué abrir."""
    chips: List[Dict[str, str]] = []

    def chip(texto: Any, tono: str = "neutro") -> None:
        if texto not in (None, ""):
            chips.append({"texto": str(texto), "tono": tono})

    if meta.get("inteligencia_simulada"):
        chip("Sin Claude", "aviso")
    if tipo == "diario":
        chip(meta.get("estado_vital"))
        if meta.get("nav_eur") is not None:
            chip(f"NAV {float(meta['nav_eur']):,.0f} €".replace(",", "."))
        if meta.get("posiciones_a_vigilar"):
            chip(f"Vigilar: {', '.join(map(str, meta['posiciones_a_vigilar']))}", "aviso")
    elif tipo == "noticias":
        if meta.get("disponible") is False:
            chip("No disponible", "aviso")
        elif meta.get("busquedas_realizadas") is not None:
            chip(f"{meta['busquedas_realizadas']} búsquedas")
    elif tipo == "operaciones":
        orden = str(meta.get("tipo_orden") or "")
        chip(orden, "positivo" if orden == "COMPRA" else "negativo" if orden == "VENTA" else "neutro")
        chip(meta.get("ticker"))
        if meta.get("total_eur") is not None:
            chip(f"{float(meta['total_eur']):,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
    elif tipo in ("tesis", "alertas"):
        chip(meta.get("ticker"))
        chip(meta.get("estado"))
        if meta.get("conviccion"):
            chip(f"Convicción {meta['conviccion']}/10")
    return chips


def listar_informes(vault, tipo: str, limite: int = 300) -> List[Dict[str, Any]]:
    """Notas de un tipo, de la más reciente a la más antigua."""
    if tipo not in TIPOS_INFORME:
        raise KeyError(tipo)
    carpeta_rel, patron, _ = TIPOS_INFORME[tipo]
    carpeta = vault.vault_path / carpeta_rel
    if not carpeta.exists():
        return []
    archivos = sorted(
        (f for f in carpeta.glob(patron) if f.is_file() and not _es_moc(f)),
        key=lambda f: f.name,
        reverse=True,
    )[:limite]
    resultado = []
    for f in archivos:
        try:
            meta, cuerpo = vault.parse_markdown(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        meta = meta or {}
        resultado.append({
            "id": f.relative_to(vault.vault_path).as_posix(),
            "titulo": _titulo(meta, cuerpo, f),
            "fecha": str(meta.get("fecha") or meta.get("fecha_apertura") or f.name[:10]),
            "etiquetas": _etiquetas(tipo, meta),
        })
    return resultado


def _ruta_segura(vault, ruta_rel: str) -> Path:
    """Resuelve `ruta_rel` dentro de la bóveda o lanza ValueError.

    Impide leer nada fuera de la bóveda (`../.env`, rutas absolutas...) y
    cualquier cosa que no sea una nota Markdown.
    """
    base = vault.vault_path.resolve()
    ruta = (base / ruta_rel).resolve()
    if base not in ruta.parents or ruta.suffix.lower() != ".md" or ".obsidian" in ruta.parts:
        raise ValueError("ruta fuera de la bóveda")
    if not ruta.is_file():
        raise FileNotFoundError(ruta_rel)
    return ruta


def buscar_nota(vault, nombre: str) -> Optional[str]:
    """Id (ruta relativa) de la nota cuyo nombre coincide con un wikilink."""
    nombre = nombre.strip().removesuffix(".md")
    # Nada de rutas ni comodines de glob: sólo un nombre de nota.
    if not nombre or any(c in nombre for c in "/\\*?[]"):
        return None
    for f in vault.vault_path.rglob(f"{nombre}.md"):
        if ".obsidian" not in f.parts:
            return f.relative_to(vault.vault_path).as_posix()
    return None


def leer_nota(vault, ruta_rel: str) -> Dict[str, Any]:
    ruta = _ruta_segura(vault, ruta_rel)
    meta, cuerpo = vault.parse_markdown(ruta.read_text(encoding="utf-8"))
    meta = meta or {}
    return {
        "id": ruta.relative_to(vault.vault_path.resolve()).as_posix(),
        "titulo": _titulo(meta, cuerpo, ruta),
        "meta": {k: _json(v) for k, v in meta.items()},
        "html": renderizar_markdown(cuerpo),
    }


def _json(valor: Any) -> Any:
    """Frontmatter -> JSON (YAML puede devolver fechas)."""
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {str(k): _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return valor


# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------
def _iso(valor: Optional[datetime]) -> Optional[str]:
    if not valor or valor == datetime.min:
        return None
    return valor.isoformat(timespec="minutes")


def _proxima_fecha_noticias(agent, ultima: Optional[date]) -> str:
    """Primer día (desde hoy) en que el arranque lanzaría el escaneo."""
    hoy = date.today()
    for dias in range(0, 8):
        dia = hoy + timedelta(days=dias)
        if agent._toca_noticias_semanales(ultima, hoy=dia):
            return dia.isoformat()
    return (hoy + timedelta(days=7)).isoformat()


def _ultimo_estudio(vault) -> Dict[str, Any]:
    carpeta = vault.vault_path / "08_Rebalanceos_Mensuales"
    estudios = sorted(carpeta.glob("*_Estudio_Mensual.md")) if carpeta.exists() else []
    if not estudios:
        return {}
    meta = vault.leer_meta_estudio_mensual(estudios[-1].name[:7])
    return {
        "id": estudios[-1].relative_to(vault.vault_path).as_posix(),
        "mes": str(meta.get("mes", estudios[-1].name[:7])),
        "fecha": str(meta.get("fecha", "")),
        "simulado": bool(meta.get("inteligencia_simulada")),
        "conclusion": str(meta.get("conclusion_mes") or ""),
    }


def construir_panel(agent) -> Dict[str, Any]:
    """Foto completa para el panel: una sola valoración a mercado."""
    valuation, health, incumplimientos = agent.snapshot_estado()
    vault = agent.vault
    hoy = date.today()

    tesis = agent.vault.list_active_theses()
    tesis_por_ticker = {t.ticker: (ruta, t) for ruta, t in tesis if t.ticker}
    niveles = agent.revisar_niveles(tesis, valuation)
    variaciones = agent._variaciones_desde_ultimo_control(valuation, hoy.isoformat())
    estado = health.estado_vital

    posiciones = []
    for p in sorted(valuation.posiciones, key=lambda x: -x.valor_mercado_eur):
        ruta_tesis, t = tesis_por_ticker.get(p.ticker, (None, None))
        posiciones.append({
            "ticker": p.ticker,
            "nombre": p.nombre,
            "nota": p.nota_activo.strip("[]").split("|")[0] if p.nota_activo else "",
            "sector": p.sector or "Sin sector",
            "unidades": p.unidades,
            "precio": p.precio_cotizacion,
            "divisa": p.divisa_cotizacion,
            "valor_eur": p.valor_mercado_eur,
            "coste_eur": p.coste_total_eur,
            "peso_pct": p.peso_pct,
            "pnl_eur": p.pnl_eur,
            "pnl_pct": p.pnl_pct,
            "variacion_pct": variaciones.get(p.ticker),
            "fiable": p.fuente_precio.es_fiable,
            "fuente": p.fuente_precio.value,
            "tesis": {
                "id": ruta_tesis.relative_to(vault.vault_path).as_posix(),
                "stop": t.stop_loss,
                "target": t.target_precio,
                "divisa": t.divisa,
                "conviccion": t.conviccion,
            } if t else None,
        })

    alertas_niveles = [
        {
            "tipo": a.tipo.value,
            "ticker": a.ticker,
            "accionable": a.es_accionable,
            "texto": level_watch.texto(a),
        }
        for a in niveles
    ]

    memoria = vault.leer_memoria_diario(400)
    historial = [
        {
            "fecha": str(m.get("fecha")),
            "nav": m.get("nav_eur"),
            "drawdown": m.get("drawdown_actual_pct"),
            "estado": m.get("estado_vital"),
        }
        for m in memoria
        if m.get("nav_eur") is not None
    ]
    ultima_diaria = next(
        (m for m in reversed(memoria) if m.get("conclusion_ia") or m.get("eventos_clave")), None
    )
    semanales = vault.leer_noticias_semanales(31)
    ultima_semana = semanales[-1] if semanales else None
    ultima_fecha_noticias = vault.leer_ultima_fecha_noticias_semanales()

    alertas_oportunidad = [
        {
            "ticker": a.ticker,
            "empresa": a.empresa,
            "conviccion": a.conviccion,
            "ratio_rr": a.ratio_rr,
            "potencial_pct": a.potencial_ganancia_pct,
            "precio": a.precio_actual,
            "divisa": a.divisa,
            "stop": a.stop_loss,
            "target": a.target_precio,
            "fecha": a.fecha_deteccion,
        }
        for a in agent.get_active_alerts()
    ]

    return {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "salud": {
            "estado": estado.value,
            "salud_pct": health.salud_porcentaje,
            "energia": health.energia_actual,
            "nav": health.nav_actual_eur,
            "nav_maximo": health.nav_maximo_historico_eur,
            "drawdown_pct": health.drawdown_actual_pct,
            "drawdown_maximo_pct": health.drawdown_maximo_pct,
            "pnl_ref_eur": health.pnl_total_eur,
            "pnl_ref_pct": health.pnl_total_pct,
            "cobertura_pct": health.cobertura_datos_pct,
            "ultimo_ciclo": _iso(health.ultimo_ciclo_diario),
        },
        "cartera": {
            "nav": valuation.nav_eur,
            "efectivo": valuation.efectivo_eur,
            "efectivo_pct": valuation.peso_efectivo_pct,
            "pnl_latente_eur": valuation.pnl_total_eur,
            "pnl_latente_pct": valuation.pnl_total_pct,
            "cobertura_pct": valuation.cobertura_mercado_pct,
            "posiciones": posiciones,
            "sectores": [
                {"sector": s, "peso_pct": w}
                for s, w in sorted(valuation.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1])
            ],
            "advertencias": list(valuation.advertencias),
        },
        "limites": {
            "max_activo_pct": agent.risk.max_position_pct(estado),
            "max_sector_pct": MAX_SECTOR_SIZE_PCT,
            "min_caja_pct": MIN_CASH_PCT,
            "max_caja_pct": MAX_CASH_PCT,
            "caja_objetivo_pct": agent.risk.target_cash_pct(estado),
            "dd_optimo_pct": DRAWDOWN_OPTIMO_MAX_PCT,
            "dd_alerta_pct": DRAWDOWN_ALERTA_MAX_PCT,
            "dd_muerte_pct": DEATH_DRAWDOWN_PCT,
            "umbral_movimiento_pct": UMBRAL_MOVIMIENTO_VIGILANCIA_PCT,
        },
        "incumplimientos": [
            {
                "regla": b.regla,
                "severidad": b.severidad,
                "sujeto": b.sujeto,
                "valor_pct": b.valor_actual_pct,
                "limite_pct": b.limite_pct,
                "mensaje": b.mensaje,
                "accion": b.accion_correctiva,
            }
            for b in incumplimientos
        ],
        "niveles": alertas_niveles,
        "oportunidades": alertas_oportunidad,
        "historial": historial,
        "cadencia": {
            "diario": {
                "hecho_hoy": agent.ya_completo_ciclo_hoy(),
                "ultimo": _iso(health.ultimo_ciclo_diario),
                "conclusion": str(
                    (ultima_diaria or {}).get("conclusion_ia")
                    or (ultima_diaria or {}).get("eventos_clave")
                    or ""
                ),
                "fecha_conclusion": str((ultima_diaria or {}).get("fecha") or ""),
            },
            "semanal": {
                "pendiente": agent.noticias_semanales_pendiente(),
                "ultimo": ultima_fecha_noticias.isoformat() if ultima_fecha_noticias else None,
                "proximo": _proxima_fecha_noticias(agent, ultima_fecha_noticias),
                "conclusion": (ultima_semana or {}).get("conclusion", ""),
            },
            "mensual": {
                "pendiente": agent.estudio_mensual_pendiente(),
                "mes_actual": hoy.strftime("%Y-%m"),
                "ultimo": _ultimo_estudio(vault),
            },
        },
    }


def info_sistema(vault_path: Path) -> Dict[str, Any]:
    """Configuración de la IA y rutas, para la pantalla de sistema."""
    return {
        "modelo": CLAUDE_MODEL,
        "modelo_noticias": NEWS_MODEL,
        "api_conectada": has_live_api_key(),
        "boveda": str(vault_path),
        "perfiles": [
            {"nivel": "Diario", "effort": EFFORT_DIARIO or "—", "max_tokens": MAX_TOKENS_DIARIO,
             "que": "Posiciones, precios, valor de mercado y normas"},
            {"nivel": "Semanal", "effort": NEWS_EFFORT or "—", "max_tokens": NEWS_MAX_TOKENS_INFORME,
             "que": "Noticias + contexto de los últimos 7 controles"},
            {"nivel": "Mensual", "effort": EFFORT_MENSUAL or "—", "max_tokens": MAX_TOKENS_MENSUAL,
             "que": "Estudio completo y reevaluación de posiciones"},
            {"nivel": "Comité", "effort": EFFORT_MENSUAL or "—", "max_tokens": MAX_TOKENS_COMITE,
             "que": "Resolución del CIO a demanda"},
        ],
    }
