"""
Vigilancia de niveles: stop-loss y take-profit de las tesis abiertas.

Por qué es un módulo aparte: hasta 2026-09 esta comprobación vivía dentro de
`SharkyAgent._revisar_stop_loss` y devolvía una lista de cadenas ya
formateadas. Eso bastaba mientras el único consumidor era el diario, pero un
aviso que sólo existe como prosa no se puede contar, ordenar por gravedad,
serializar para el aviso emergente de Windows ni distinguir "no saltó" de "no
se pudo comprobar". Aquí la comprobación produce datos (`LevelAlert`) y el
formato se decide en cada destino.

Dos asimetrías deliberadas gobiernan el módulo:

  1. **El stop-loss obliga; el target no.** Cruzar el stop es la única
     excepción operativa intrames del mandato: se liquida. Alcanzar el target
     es una noticia, no una orden -- liquidar toda posición ganadora en su
     primer objetivo es la forma más eficiente de quedarse fuera de las
     tendencias que pagan la cartera. Por eso el take-profit no manda vender:
     propone subir el stop.

  2. **Todo se compara en EUR.** Una tesis declara sus niveles en la divisa de
     su frontmatter (`divisa`), que no tiene por qué ser la de cotización: el
     stop de MSFT vino del extracto en euros mientras la acción cotiza en
     dólares. Comparar ambos números sin convertirlos es el mismo error de
     unidades que fabricaba el PnL de la versión anterior.
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Protocol, Sequence, Tuple

from sharky.config import ALERTAS_NIVELES_PATH, TRAILING_STOP_PCT
from sharky.models import (
    FxRate,
    InvestmentThesis,
    LevelAlert,
    LevelKind,
    PortfolioValuation,
    PositionValuation,
)


class _FxLike(Protocol):
    """Lo único que este módulo necesita de `sharky.fx.FxProvider`.

    Declararlo como Protocol en vez de importar `FxProvider` mantiene la
    vigilancia de niveles comprobable con un doble de tres líneas.
    """

    def get_rate(self, from_currency: str) -> "FxRate": ...  # pragma: no cover


def revisar_niveles(
    tesis: Iterable[Tuple[object, InvestmentThesis]],
    valuation: PortfolioValuation,
    fx: _FxLike,
) -> List[LevelAlert]:
    """Comprueba stop-loss y take-profit de cada tesis con posición abierta.

    Devuelve los stops alcanzados primero, después los targets y por último
    las tesis que no se pudieron verificar: el orden es el de urgencia con el
    que hay que leerlos, y lo respetan tanto la consola como la bóveda.
    """
    stops: List[LevelAlert] = []
    targets: List[LevelAlert] = []
    mudos: List[LevelAlert] = []

    por_ticker = {p.ticker.upper(): p for p in valuation.posiciones}

    for _, t in tesis:
        if not t.ticker:
            continue
        vigila_stop = t.stop_loss > 0
        vigila_target = t.target_precio > 0
        if not (vigila_stop or vigila_target):
            continue  # Tesis en radar sin niveles declarados: nada que vigilar.

        pos = por_ticker.get(t.ticker.upper())
        if pos is None:
            continue  # Tesis sin posición abierta.

        if not pos.fuente_precio.es_fiable:
            mudos.append(
                _no_verificable(t, pos, "no hay cotización fiable del activo")
            )
            continue

        try:
            tasa = fx.get_rate(t.divisa).tasa
        except ValueError as exc:
            mudos.append(_no_verificable(t, pos, str(exc)))
            continue

        if tasa <= 0:
            mudos.append(
                _no_verificable(t, pos, f"tipo de cambio no válido para {t.divisa}")
            )
            continue

        # Precio de mercado expresado en la divisa en la que la tesis declara
        # sus niveles, para que la comparación y el stop propuesto vivan en
        # las mismas unidades que el resto del frontmatter de la nota.
        precio_tesis = pos.precio_unitario_eur / tasa

        stop_eur = t.stop_loss * tasa
        target_eur = t.target_precio * tasa

        # El stop tiene prioridad: si un frontmatter incoherente dejara ambos
        # niveles cruzados a la vez, la salida obligatoria manda.
        if vigila_stop and pos.precio_unitario_eur <= stop_eur:
            stops.append(
                LevelAlert(
                    tipo=LevelKind.STOP_LOSS,
                    ticker=t.ticker,
                    nota_activo=pos.nota_activo,
                    precio_eur=round(pos.precio_unitario_eur, 4),
                    precio_cotizacion=pos.precio_cotizacion,
                    divisa_cotizacion=pos.divisa_cotizacion,
                    nivel=t.stop_loss,
                    nivel_eur=round(stop_eur, 4),
                    divisa_nivel=t.divisa,
                    valor_posicion_eur=pos.valor_mercado_eur,
                    pnl_eur=pos.pnl_eur,
                    pnl_pct=pos.pnl_pct,
                    stop_actual=t.stop_loss,
                )
            )
            continue

        if vigila_target and pos.precio_unitario_eur >= target_eur:
            sugerido, criterio = _stop_dinamico(t, precio_tesis)
            targets.append(
                LevelAlert(
                    tipo=LevelKind.TAKE_PROFIT,
                    ticker=t.ticker,
                    nota_activo=pos.nota_activo,
                    precio_eur=round(pos.precio_unitario_eur, 4),
                    precio_cotizacion=pos.precio_cotizacion,
                    divisa_cotizacion=pos.divisa_cotizacion,
                    nivel=t.target_precio,
                    nivel_eur=round(target_eur, 4),
                    divisa_nivel=t.divisa,
                    valor_posicion_eur=pos.valor_mercado_eur,
                    pnl_eur=pos.pnl_eur,
                    pnl_pct=pos.pnl_pct,
                    stop_actual=t.stop_loss,
                    stop_sugerido=sugerido,
                    stop_sugerido_eur=round(sugerido * tasa, 4),
                    criterio_stop=criterio,
                )
            )

    return stops + targets + mudos


def _no_verificable(
    t: InvestmentThesis, pos: PositionValuation, motivo: str
) -> LevelAlert:
    return LevelAlert(
        tipo=LevelKind.NO_VERIFICABLE,
        ticker=t.ticker,
        nota_activo=pos.nota_activo,
        precio_eur=round(pos.precio_unitario_eur, 4),
        precio_cotizacion=pos.precio_cotizacion,
        divisa_cotizacion=pos.divisa_cotizacion,
        divisa_nivel=t.divisa,
        nivel=t.stop_loss,
        valor_posicion_eur=pos.valor_mercado_eur,
        stop_actual=t.stop_loss,
        motivo=motivo,
    )


def _stop_dinamico(t: InvestmentThesis, precio_tesis: float) -> Tuple[float, str]:
    """Propone un stop al alcanzar el target, en la divisa de la tesis.

    Dos criterios deterministas, y gana el más alto:

      * **break-even**: el precio de entrada. Protege el principal: a partir
        de ahí la operación no puede terminar en pérdida.
      * **trailing**: el precio actual menos el riesgo inicial de la tesis
        (`entrada - stop`). Mantiene constante el riesgo abierto que el
        `RiskGovernor` ya aprobó al abrir la posición, en vez de inventar un
        porcentaje nuevo. Si la tesis no declara entrada o stop no hay riesgo
        inicial que replicar, y el trailing cae a `TRAILING_STOP_PCT`.

    El resultado nunca queda por debajo del stop vigente: un take-profit no
    puede empeorar la protección de una posición.
    """
    entrada = t.precio_entrada if t.precio_entrada > 0 else 0.0
    stop_vigente = t.stop_loss if t.stop_loss > 0 else 0.0

    riesgo_inicial = entrada - stop_vigente if entrada > 0 and stop_vigente > 0 else 0.0
    if riesgo_inicial > 0:
        trailing = precio_tesis - riesgo_inicial
    else:
        trailing = precio_tesis * (1.0 - TRAILING_STOP_PCT / 100.0)

    candidatos: List[Tuple[float, str]] = [(trailing, "trailing")]
    if entrada > 0:
        candidatos.append((entrada, "break-even"))

    sugerido, criterio = max(candidatos, key=lambda c: c[0])

    if sugerido <= stop_vigente:
        # El stop vigente ya es mejor que cualquiera de los dos criterios.
        return round(stop_vigente, 4), "sin cambio"

    return round(sugerido, 4), criterio


# --------------------------------------------------------------------------
# Formato
# --------------------------------------------------------------------------
def texto(alerta: LevelAlert, enlace: Optional[Callable[[str, str], str]] = None) -> str:
    """Renderiza un aviso.

    `enlace` convierte (ticker, nota_activo) en un wikilink de Obsidian; sin
    él el nombre se escribe en crudo, que es lo que quiere la consola.
    """
    nombre = enlace(alerta.ticker, alerta.nota_activo) if enlace else alerta.ticker
    marca = "**" if enlace else ""
    precio = (
        f"{alerta.precio_eur:,.2f} € por título "
        f"({alerta.precio_cotizacion:,.2f} {alerta.divisa_cotizacion})"
    )

    if alerta.tipo is LevelKind.STOP_LOSS:
        return (
            f"🛑 {marca}STOP-LOSS ALCANZADO en {nombre}{marca}: cotiza a {precio} frente a "
            f"un stop de {alerta.nivel:,.2f} {alerta.divisa_nivel} "
            f"({alerta.nivel_eur:,.2f} €). El mandato exige liquidar de inmediato: "
            f"{alerta.valor_posicion_eur:,.2f} € en riesgo."
        )

    if alerta.tipo is LevelKind.TAKE_PROFIT:
        if alerta.criterio_stop == "sin cambio":
            accion = (
                f"El stop vigente ({alerta.stop_actual:,.2f} {alerta.divisa_nivel}) ya "
                "protege la posición: decide si tomas beneficios o dejas correr."
            )
        else:
            accion = (
                f"Sube el stop a {alerta.stop_sugerido:,.2f} {alerta.divisa_nivel} "
                f"({alerta.stop_sugerido_eur:,.2f} €, criterio {alerta.criterio_stop}) "
                f"desde {alerta.stop_actual:,.2f} {alerta.divisa_nivel}, o toma "
                "beneficios. El mandato no obliga a vender."
            )
        return (
            f"🎯 {marca}TARGET ALCANZADO en {nombre}{marca}: cotiza a {precio} frente a "
            f"un target de {alerta.nivel:,.2f} {alerta.divisa_nivel} "
            f"({alerta.nivel_eur:,.2f} €). Posición: {alerta.valor_posicion_eur:,.2f} € "
            f"({alerta.pnl_eur:+,.2f} €, {alerta.pnl_pct:+.2f}%). {accion}"
        )

    return (
        f"⚠️ {marca}{nombre}{marca}: no se pueden verificar sus niveles "
        f"({alerta.motivo})."
    )


def resumen(alertas: Sequence[LevelAlert]) -> str:
    """Una línea con el recuento por tipo, para logs y cabeceras."""
    stops = sum(1 for a in alertas if a.tipo is LevelKind.STOP_LOSS)
    targets = sum(1 for a in alertas if a.tipo is LevelKind.TAKE_PROFIT)
    mudos = sum(1 for a in alertas if a.tipo is LevelKind.NO_VERIFICABLE)
    partes = []
    if stops:
        partes.append(f"{stops} stop-loss")
    if targets:
        partes.append(f"{targets} target")
    if mudos:
        partes.append(f"{mudos} sin verificar")
    return ", ".join(partes) if partes else "ningún nivel alcanzado"


# --------------------------------------------------------------------------
# Persistencia para el aviso emergente
# --------------------------------------------------------------------------
def guardar(alertas: Sequence[LevelAlert], path: Optional[Path] = None) -> Path:
    """Deja los niveles alcanzados en disco para el aviso de Windows.

    El aviso emergente (`scripts/avisar_niveles_windows.ps1`) corre después
    del ciclo, en otro proceso: sin este fichero tendría que volver a valorar
    la cartera -- otra llamada al mercado y, peor, la posibilidad de enseñar
    números distintos a los que acaba de escribir el diario.

    El destino vive en `logs/`, fuera de git: contiene posiciones y valores
    reales de la cartera.
    """
    destino = Path(path) if path else ALERTAS_NIVELES_PATH
    destino.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "fecha": date.today().isoformat(),
        "resumen": resumen(alertas),
        "accionables": sum(1 for a in alertas if a.es_accionable),
        "alertas": [
            {
                "tipo": a.tipo.value,
                "ticker": a.ticker,
                "texto": texto(a),
                **a.model_dump(mode="json"),
            }
            for a in alertas
        ],
    }
    destino.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destino


def cargar(path: Optional[Path] = None) -> List[LevelAlert]:
    """Recarga los niveles que `guardar` dejó escritos hoy, si los hay.

    La usa `TradeRecorder` para no perder de `Estado_Vital.md` los avisos de
    nivel del día al reescribirlo tras una operación: sin esto, registrar la
    venta que un stop exige borraba del cuadro de mandos el aviso de ese mismo
    stop. Devuelve `[]` si no hay fichero, es ilegible, o es de un día
    anterior (los niveles de ayer no deben reinyectarse hoy).
    """
    origen = Path(path) if path else ALERTAS_NIVELES_PATH
    if not origen.exists():
        return []
    try:
        payload = json.loads(origen.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if payload.get("fecha") != date.today().isoformat():
        return []
    alertas: List[LevelAlert] = []
    for cruda in payload.get("alertas", []):
        try:
            alertas.append(LevelAlert(**cruda))
        except (TypeError, ValueError):
            continue
    return alertas
