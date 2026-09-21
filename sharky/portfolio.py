"""
Libro de posiciones y valoración de cartera.

Este módulo es la ÚNICA fuente de verdad de la cartera. El NAV, el PnL y todos
los límites de riesgo se derivan de aquí, no de las notas de tesis: una tesis es
una opinión, una posición es un hecho contable.

El libro vive en `vault/00_Sistema/Cartera_Real.md` para que siga siendo
legible y editable desde Obsidian.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math

import yaml

from sharky.atomic_io import atomic_write_text
from sharky.config import VAULT_PATH, BASE_CURRENCY
from sharky.fx import FxProvider
from sharky.market_data import MarketDataProvider
from sharky.models import (
    AssetClass,
    Portfolio,
    PortfolioValuation,
    Position,
    PositionValuation,
    PriceSource,
)

LEDGER_RELATIVE_PATH = Path("00_Sistema") / "Cartera_Real.md"


class PortfolioStore:
    """Lee y escribe el libro de posiciones en la bóveda."""

    def __init__(self, vault_path: Path = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self.ledger_path = self.vault_path / LEDGER_RELATIVE_PATH

    def exists(self) -> bool:
        return self.ledger_path.exists()

    def load(self) -> Portfolio:
        if not self.ledger_path.exists():
            raise FileNotFoundError(
                f"No existe el libro de posiciones en {self.ledger_path}. "
                f"Ejecuta `python -m sharky.cli init` para crearlo."
            )

        contenido = self.ledger_path.read_text(encoding="utf-8")
        meta = _parse_frontmatter(contenido)

        posiciones: List[Position] = []
        for cruda in meta.get("posiciones") or []:
            try:
                posiciones.append(_position_from_dict(cruda))
            except Exception as exc:
                raise ValueError(
                    f"Posición inválida en {self.ledger_path.name}: {cruda!r} -> {exc}"
                ) from exc

        return Portfolio(
            custodio=str(meta.get("custodio", "Trade Republic Bank GmbH")),
            divisa_base=str(meta.get("divisa_base", BASE_CURRENCY)),
            fecha_actualizacion=str(meta.get("fecha_actualizacion", "")),
            efectivo_eur=float(meta.get("efectivo_eur", 0.0)),
            posiciones=posiciones,
        )

    def save(self, portfolio: Portfolio) -> Path:
        """Persiste el libro regenerando frontmatter y tabla legible."""
        portfolio.fecha_actualizacion = datetime.now().strftime("%Y-%m-%d")

        meta = {
            "tipo": "libro_posiciones",
            "custodio": portfolio.custodio,
            "divisa_base": portfolio.divisa_base,
            "fecha_actualizacion": portfolio.fecha_actualizacion,
            "efectivo_eur": round(portfolio.efectivo_eur, 2),
            "numero_posiciones": len(portfolio.posiciones),
            "coste_total_eur": portfolio.coste_total_eur,
            "posiciones": [_position_to_dict(p) for p in portfolio.posiciones],
        }

        filas = []
        for p in sorted(portfolio.posiciones, key=lambda x: x.coste_total_eur, reverse=True):
            cotiza = p.ticker_cotizacion or "*sin cotización*"
            nota = _wikilink(p)
            # El `|` del alias de Obsidian es el mismo carácter que separa
            # columnas en Markdown: sin escapar, `[[Rheinmetall|RHM]]` parte la
            # celda en dos y desplaza el resto de la fila una columna a la
            # derecha. Mismo criterio que `VaultManager.enlace`.
            enlace = f"[[{nota}\\|{p.ticker}]]" if nota != p.ticker else f"[[{p.ticker}]]"
            filas.append(
                f"| {enlace} | {p.nombre} | {p.clase.value} | `{cotiza}` | "
                f"{p.divisa_cotizacion} | {p.unidades:,.6f} | {p.coste_unitario_eur:,.2f} € | "
                f"{p.coste_total_eur:,.2f} € | {p.sector} |"
            )

        sin_cotizacion = [p.ticker for p in portfolio.posiciones if not p.ticker_cotizacion]
        aviso_pendientes = ""
        if sin_cotizacion:
            aviso_pendientes = (
                "\n> [!WARNING]\n"
                "> **Posiciones sin símbolo de cotización:** "
                + ", ".join(f"`{t}`" for t in sin_cotizacion)
                + ".\n> Estas posiciones se valoran a **coste de adquisición**, no a mercado.\n"
                "> Completa `ticker_cotizacion` y `divisa_cotizacion` en el frontmatter para\n"
                "> incorporarlas al NAV real. Ayuda: `python -m sharky.cli resolve-isin`.\n"
            )

        cuerpo = f"""# 📒 LIBRO DE POSICIONES (Fuente de Verdad)

> [!IMPORTANT]
> Este archivo es la **única fuente de verdad** de la cartera. El NAV, el PnL, el
> drawdown y todos los límites de riesgo se calculan a partir de aquí.
> Las notas de [[01_Tesis_Activas]] expresan convicción, **no** tenencias.

**Custodio:** {portfolio.custodio}
**Divisa base:** {portfolio.divisa_base}
**Última actualización:** {portfolio.fecha_actualizacion}
**Efectivo:** `{portfolio.efectivo_eur:,.2f} €`
**Coste total de las posiciones:** `{portfolio.coste_total_eur:,.2f} €`
{aviso_pendientes}
---

## Posiciones ({len(portfolio.posiciones)})

| Activo | Nombre | Clase | Símbolo | Divisa | Unidades | Coste unitario | Coste total | Sector |
| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- |
{chr(10).join(filas) if filas else "| - | *Sin posiciones registradas* | - | - | - | - | - | - | - |"}

---

## Cómo se actualiza

* **Alta o ampliación de posición:** `python -m sharky.cli trade` (pasa por el
  cortafuegos del [[Politica_Control_Riesgo|RiskGovernor]] antes de escribirse).
* **Corrección manual:** edita el frontmatter `posiciones` de esta nota.
* `coste_unitario_eur` es el **coste medio de adquisición en EUR**, no la
  cotización actual. No lo sobrescribas con precios de mercado.

---

## 🔗 Enlaces Bidireccionales del Grafo

* Sistema: [[00_Sistema]], [[Estado_Vital]], [[Metricas_Riesgo]]
* Mandato y límites: [[Reglas_De_Supervivencia]], [[Politica_Control_Riesgo]]
* Auditoría de origen: [[Auditoria_Cartera_Inicial_Real]]
* Operaciones registradas: [[04_Operaciones_Bitacora]]
"""

        yaml_str = yaml.dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False).strip()
        atomic_write_text(
            self.ledger_path, f"---\n{yaml_str}\n---\n\n{cuerpo.strip()}\n", encoding="utf-8"
        )
        return self.ledger_path


class PortfolioValuator:
    """Valora el libro de posiciones en la divisa base."""

    def __init__(
        self,
        market: Optional[MarketDataProvider] = None,
        fx: Optional[FxProvider] = None,
    ):
        self.market = market or MarketDataProvider()
        self.fx = fx or FxProvider()

    def value(self, portfolio: Portfolio) -> PortfolioValuation:
        valoraciones: List[PositionValuation] = []
        advertencias: List[str] = []
        sin_cotizacion: List[str] = []

        for pos in portfolio.posiciones:
            val, aviso = self._value_position(pos)
            valoraciones.append(val)
            if val.fuente_precio == PriceSource.COSTE:
                sin_cotizacion.append(pos.ticker)
            if aviso:
                advertencias.append(aviso)

        valor_posiciones = round(sum(v.valor_mercado_eur for v in valoraciones), 2)
        nav = round(valor_posiciones + portfolio.efectivo_eur, 2)
        coste_total = portfolio.coste_total_eur
        pnl = round(nav - portfolio.efectivo_eur - coste_total, 2)
        pnl_pct = round((pnl / coste_total * 100.0), 2) if coste_total > 0 else 0.0

        # Pesos y exposición sectorial sobre el NAV total (efectivo incluido).
        exposicion: Dict[str, float] = {}
        for v in valoraciones:
            v.peso_pct = round((v.valor_mercado_eur / nav * 100.0), 2) if nav > 0 else 0.0
            sector = v.sector or "Sin Clasificar"
            exposicion[sector] = round(exposicion.get(sector, 0.0) + v.peso_pct, 2)

        # El efectivo es una certeza contable, así que cuenta como cubierto.
        valor_fiable = portfolio.efectivo_eur + sum(
            v.valor_mercado_eur for v in valoraciones if v.fuente_precio.es_fiable
        )
        cobertura = round((valor_fiable / nav * 100.0), 2) if nav > 0 else 100.0

        if sin_cotizacion:
            advertencias.append(
                f"{len(sin_cotizacion)} posición(es) valorada(s) a coste por falta de "
                f"símbolo de cotización: {', '.join(sin_cotizacion)}."
            )
        if cobertura < 100.0:
            advertencias.append(
                f"Sólo el {cobertura:.1f}% del NAV está respaldado por cotizaciones "
                f"fiables. Trata el PnL como una estimación parcial."
            )
        advertencias.extend(self.market.discrepancias_divisa)

        return PortfolioValuation(
            fecha=datetime.now(),
            divisa_base=portfolio.divisa_base,
            posiciones=valoraciones,
            efectivo_eur=round(portfolio.efectivo_eur, 2),
            nav_eur=nav,
            coste_total_eur=coste_total,
            pnl_total_eur=pnl,
            pnl_total_pct=pnl_pct,
            peso_efectivo_pct=round((portfolio.efectivo_eur / nav * 100.0), 2) if nav > 0 else 0.0,
            exposicion_sectorial_pct=exposicion,
            cobertura_mercado_pct=cobertura,
            posiciones_sin_cotizacion=sin_cotizacion,
            advertencias=advertencias,
        )

    def _value_position(self, pos: Position) -> Tuple[PositionValuation, Optional[str]]:
        coste_total = pos.coste_total_eur

        def a_coste(motivo: Optional[str]) -> Tuple[PositionValuation, Optional[str]]:
            return (
                PositionValuation(
                    ticker=pos.ticker,
                    nombre=pos.nombre,
                    nota_activo=_wikilink(pos),
                    sector=pos.sector,
                    unidades=pos.unidades,
                    precio_cotizacion=pos.coste_unitario_eur,
                    divisa_cotizacion=BASE_CURRENCY,
                    tipo_cambio_a_eur=1.0,
                    precio_unitario_eur=pos.coste_unitario_eur,
                    valor_mercado_eur=coste_total,
                    coste_total_eur=coste_total,
                    pnl_eur=0.0,
                    pnl_pct=0.0,
                    fuente_precio=PriceSource.COSTE,
                ),
                motivo,
            )

        if not pos.ticker_cotizacion:
            return a_coste(None)

        snap = self.market.get_snapshot(
            pos.ticker, symbol=pos.ticker_cotizacion, divisa=pos.divisa_cotizacion
        )
        if snap.fuente == PriceSource.COSTE or snap.precio_actual <= 0 or math.isnan(snap.precio_actual):
            return a_coste(
                f"{pos.ticker}: sin cotización utilizable para `{pos.ticker_cotizacion}`. "
                f"Valorada a coste."
            )

        try:
            fx = self.fx.get_rate(snap.divisa)
        except ValueError as exc:
            return a_coste(f"{pos.ticker}: {exc}")

        precio_eur = round(snap.precio_actual * fx.tasa, 6)
        valor_mercado = round(pos.unidades * precio_eur, 2)
        pnl = round(valor_mercado - coste_total, 2)
        pnl_pct = round((pnl / coste_total * 100.0), 2) if coste_total > 0 else 0.0

        # La fiabilidad de la valoración es la del eslabón más débil.
        fuente = snap.fuente
        if not fx.fuente.es_fiable:
            fuente = PriceSource.SIMULADO

        aviso = None
        if fuente == PriceSource.SIMULADO:
            aviso = (
                f"{pos.ticker}: valorada con precio o tipo de cambio de referencia, "
                f"no con datos de mercado."
            )

        return (
            PositionValuation(
                ticker=pos.ticker,
                nombre=pos.nombre,
                nota_activo=_wikilink(pos),
                sector=pos.sector,
                unidades=pos.unidades,
                precio_cotizacion=round(snap.precio_actual, 4),
                divisa_cotizacion=snap.divisa,
                tipo_cambio_a_eur=round(fx.tasa, 6),
                precio_unitario_eur=precio_eur,
                valor_mercado_eur=valor_mercado,
                coste_total_eur=coste_total,
                pnl_eur=pnl,
                pnl_pct=pnl_pct,
                fuente_precio=fuente,
            ),
            aviso,
        )


# ----------------------------------------------------------------------
# Utilidades internas
# ----------------------------------------------------------------------
def _wikilink(pos: Position) -> str:
    """Nombre de la ficha del activo en Obsidian, sin los corchetes.

    El ticker no siempre coincide con el nombre de la nota: la ficha de
    Rheinmetall se llama `Rheinmetall`, no `RHM`. Se respeta `nota_activo` y se
    cae al ticker sólo si no está declarado.
    """
    bruto = (pos.nota_activo or "").strip()
    if bruto.startswith("[[") and bruto.endswith("]]"):
        bruto = bruto[2:-2].strip()
    return bruto or pos.ticker


def _parse_frontmatter(contenido: str) -> dict:
    if not contenido.startswith("---"):
        return {}
    partes = contenido.split("---", 2)
    if len(partes) < 3:
        return {}
    try:
        return yaml.safe_load(partes[1]) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Frontmatter YAML inválido en el libro de posiciones: {exc}") from exc


def _position_from_dict(cruda: dict) -> Position:
    simbolo = cruda.get("ticker_cotizacion")
    if isinstance(simbolo, str) and not simbolo.strip():
        simbolo = None
    return Position(
        # Se preserva la capitalización original: el ticker es también el nombre
        # de la ficha en Obsidian (`[[Physical_Gold]]`), y forzarlo a mayúsculas
        # rompería los enlaces del grafo.
        ticker=str(cruda["ticker"]).strip(),
        nombre=str(cruda.get("nombre", cruda["ticker"])),
        isin=(str(cruda["isin"]).strip() if cruda.get("isin") else None),
        ticker_cotizacion=(str(simbolo).strip() if simbolo else None),
        divisa_cotizacion=str(cruda.get("divisa_cotizacion", BASE_CURRENCY)).strip(),
        clase=AssetClass(str(cruda.get("clase", "ACCION")).upper()),
        unidades=float(cruda["unidades"]),
        coste_unitario_eur=float(cruda["coste_unitario_eur"]),
        sector=str(cruda.get("sector", "")),
        nota_activo=str(cruda.get("nota_activo", "")),
    )


def _position_to_dict(pos: Position) -> dict:
    return {
        "ticker": pos.ticker,
        "nombre": pos.nombre,
        "isin": pos.isin,
        "ticker_cotizacion": pos.ticker_cotizacion,
        "divisa_cotizacion": pos.divisa_cotizacion,
        "clase": pos.clase.value,
        "unidades": round(pos.unidades, 8),
        "coste_unitario_eur": round(pos.coste_unitario_eur, 4),
        "sector": pos.sector,
        "nota_activo": pos.nota_activo,
    }
