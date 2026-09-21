"""
Revisión mensual de las tesis activas.

Hasta 2026-09 una tesis se escribía una vez y no se volvía a tocar. El
estudio mensual sí dictaba MANTENER / REDUCIR / CERRAR posición a posición,
pero ese veredicto moría en la nota del estudio: nada volvía al fichero de la
tesis. Mientras tanto el frontmatter seguía moviendo maquinaria viva --
`level_watch` compara cada día el precio real contra `stop_loss`, y el motor
de rebalanceo ordena sus candidatos por `conviccion` -- con cifras que nadie
había vuelto a mirar. Este módulo cierra ese lazo.

Tres reglas gobiernan el módulo, y las tres existen para resistir la misma
tentación:

  1. **Añade, nunca sobrescribe.** Cada revisión apila una sección fechada
     encima de lo anterior. Lo que pensabas en agosto se conserva intacto,
     porque la única pregunta que enseña algo es *¿tenía razón mi tesis de
     agosto?* -- y no se puede responder si la tesis de agosto ya no existe.
     Una nota reescrita cada mes acaba explicando lo que el precio ya hizo, y
     eso es peor que una tesis obsoleta porque *parece* vigente.

  2. **No toca un solo número.** El stop-loss es la única salida obligatoria
     del mandato. Si pudiera renegociarse cada mes, una posición que se acerca
     a su stop recibiría uno más bajo con una justificación impecable: "la
     tesis sigue intacta". Eso no es revisar, es rationalizar. Los cambios de
     nivel o de convicción se escriben como PROPUESTA y los aplica una
     persona, exactamente igual que el stop dinámico que ya propone
     `level_watch` al alcanzar un target.

  3. **Sólo revisa lo que tiene algo que decir.** Generar prosa sobre una
     posición donde no pasó nada es justamente donde nace la deriva
     narrativa. `seleccionar` es determinista y no gasta API: decide a partir
     de movimiento del mes, niveles alcanzados, incumplimientos abiertos y
     noticias. La red de seguridad (`REVIEW_MESES_MAX`) impide que una tesis
     tranquila quede olvidada para siempre.

Como el escaneo de noticias y el explorador, no tiene modo simulado: sin
clave en vivo no se revisa nada y se declara.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, field_validator

from sharky.config import (
    ANTHROPIC_API_KEY,
    API_KEY_PLACEHOLDERS,
    REVIEW_EFFORT,
    REVIEW_MAX_TESIS,
    REVIEW_MAX_TOKENS,
    REVIEW_MESES_MAX,
    REVIEW_MODEL,
    REVIEW_UMBRAL_MOVIMIENTO_PCT,
    has_live_api_key,
)
from sharky.models import InvestmentThesis, LevelAlert, PortfolioValuation, RiskBreach

# Por encima de este `max_tokens` el SDK exige streaming. Mismo umbral que el
# resto de clientes de la casa.
MAX_TOKENS_SIN_STREAMING = 20000

VEREDICTOS = ("MANTENER", "AMPLIAR", "REDUCIR", "CERRAR")

_BLOQUE_JSON = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)


# --------------------------------------------------------------------------
# Selección: determinista, sin API
# --------------------------------------------------------------------------
@dataclass
class Seleccion:
    """Una tesis y por qué entra (o no entra) en la revisión de este mes."""

    ruta: Path
    tesis: InvestmentThesis
    motivos: List[str] = field(default_factory=list)
    # Sólo en las omitidas: por qué se queda fuera.
    descarte: str = ""

    @property
    def ticker(self) -> str:
        return self.tesis.ticker


def _fecha(valor: Any) -> Optional[date]:
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _meses_entre(desde: date, hasta: date) -> int:
    return (hasta.year - desde.year) * 12 + (hasta.month - desde.month)


def movimiento_del_mes(memoria: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """% de variación de cada activo entre el primer y el último control.

    Deliberadamente mensual y no diario: una posición que se desliza un 18%
    en tres semanas sin un solo día de -7% nunca aparece en
    `posiciones_a_vigilar`, y es exactamente la que hay que releer.

    Los controles diarios sólo empezaron a registrar `precios_eur` en
    2026-09, así que esto devuelve `{}` mientras no haya al menos dos
    entradas con precios. No es un problema: es una señal más entre varias, y
    la red de seguridad cubre lo que ninguna señal alcance.
    """
    con_precios = [m for m in memoria if m.get("precios_eur")]
    if len(con_precios) < 2:
        return {}
    primeros = con_precios[0]["precios_eur"] or {}
    ultimos = con_precios[-1]["precios_eur"] or {}
    variaciones: Dict[str, float] = {}
    for ticker, ultimo in ultimos.items():
        primero = primeros.get(ticker)
        try:
            if not primero or float(primero) <= 0:
                continue
            variaciones[str(ticker).upper()] = round(
                (float(ultimo) / float(primero) - 1.0) * 100.0, 2
            )
        except (TypeError, ValueError):
            continue
    return variaciones


def _tickers_en_noticias(noticias: Sequence[Dict[str, Any]]) -> set:
    """Tickers con sección propia en algún escaneo semanal del mes.

    El escaneo escribe `## {TICKER}` por activo, así que se busca el
    encabezado y no la simple aparición del texto: `MP` como palabra suelta
    aparece en cualquier prosa, `## MP` no.
    """
    vistos = set()
    for escaneo in noticias:
        if not escaneo.get("disponible", True):
            continue
        for linea in str(escaneo.get("resumen") or "").splitlines():
            if linea.startswith("#"):
                cabecera = linea.lstrip("#").strip()
                # "## NVDA" o "## NVDA — NVIDIA Corporation"
                vistos.add(re.split(r"[\s—\-–:|]", cabecera)[0].strip().upper())
    return {v for v in vistos if v}


def seleccionar(
    tesis: Sequence[Tuple[Path, InvestmentThesis]],
    memoria: Optional[Sequence[Dict[str, Any]]] = None,
    noticias: Optional[Sequence[Dict[str, Any]]] = None,
    incumplimientos: Optional[Sequence[RiskBreach]] = None,
    niveles: Optional[Sequence[LevelAlert]] = None,
    revisadas: Optional[Dict[str, Any]] = None,
    hoy: Optional[date] = None,
    meses_max: int = REVIEW_MESES_MAX,
    umbral_movimiento_pct: float = REVIEW_UMBRAL_MOVIMIENTO_PCT,
    tope: int = REVIEW_MAX_TESIS,
) -> Tuple[List[Seleccion], List[Seleccion]]:
    """Decide qué tesis se revisan este mes. Determinista, sin API.

    Devuelve `(a_revisar, omitidas)`. Las omitidas llevan escrito por qué,
    igual que el diagnóstico del detector de oportunidades: un proceso que no
    selecciona nada tiene que poder explicarse.

    `revisadas` mapea ticker -> fecha de la última revisión (lo que el
    frontmatter guarda en `fecha_revision`). Si una tesis nunca se revisó, la
    red de seguridad cuenta desde `fecha_apertura`: una tesis escrita ayer no
    necesita revisión hoy.
    """
    hoy = hoy or date.today()
    revisadas = revisadas or {}
    variaciones = movimiento_del_mes(memoria or [])
    con_noticias = _tickers_en_noticias(noticias or [])
    sujetos_incumplidos = {
        str(b.sujeto).upper() for b in (incumplimientos or []) if b.sujeto
    }
    niveles_accionables = {
        a.ticker.upper() for a in (niveles or []) if a.es_accionable
    }
    marcadas_a_vigilar = {
        str(t).upper()
        for m in (memoria or [])
        for t in (m.get("posiciones_a_vigilar") or [])
    }

    candidatas: List[Seleccion] = []
    omitidas: List[Seleccion] = []

    for ruta, t in tesis:
        clave = (t.ticker or "").upper()
        if not clave:
            continue
        motivos: List[str] = []

        variacion = variaciones.get(clave)
        if variacion is not None and abs(variacion) >= umbral_movimiento_pct:
            motivos.append(f"movimiento del mes {variacion:+.1f}%")
        if clave in niveles_accionables:
            motivos.append("nivel alcanzado")
        elif clave in marcadas_a_vigilar:
            motivos.append("marcada a vigilar durante el mes")
        if clave in sujetos_incumplidos:
            motivos.append("incumplimiento del mandato abierto")
        if clave in con_noticias:
            motivos.append("noticias del mes")

        ultima = _fecha(revisadas.get(clave)) or _fecha(t.fecha_apertura)
        if ultima is None:
            motivos.append("sin fecha de revisión ni de apertura")
        else:
            meses = _meses_entre(ultima, hoy)
            if meses >= meses_max:
                motivos.append(
                    f"{meses} mes(es) sin revisar (red de seguridad: {meses_max})"
                )

        seleccion = Seleccion(ruta=ruta, tesis=t, motivos=motivos)
        if motivos:
            candidatas.append(seleccion)
        else:
            seleccion.descarte = (
                "sin movimiento, niveles, incumplimientos ni noticias este mes"
            )
            omitidas.append(seleccion)

    # Más motivos = más razones para releerla. A igualdad, primero la de mayor
    # convicción: es la que más pesa si resulta estar equivocada.
    candidatas.sort(key=lambda s: (-len(s.motivos), -s.tesis.conviccion, s.ticker))

    if tope > 0 and len(candidatas) > tope:
        for sobrante in candidatas[tope:]:
            sobrante.descarte = (
                f"supera el tope de {tope} tesis por ejecución; "
                "vuelve a seleccionarse el mes que viene"
            )
        omitidas.extend(candidatas[tope:])
        candidatas = candidatas[:tope]

    return candidatas, omitidas


# --------------------------------------------------------------------------
# Revisión: la llamada a Claude
# --------------------------------------------------------------------------
class ThesisVerdict(BaseModel):
    """El veredicto sobre una tesis. Sin un solo número aplicable.

    `propuesta_stop` y `propuesta_conviccion` son texto, no cifras que nadie
    vaya a escribir en el frontmatter: se redactan en la nota para que las
    valore una persona. Si algún día alguien los convierte en `float` y los
    asienta, habrá dejado que un modelo renegocie la única salida obligatoria
    del mandato.
    """

    ticker: str
    veredicto: str = "MANTENER"
    que_ha_cambiado: str = ""
    que_sigue_en_pie: str = ""
    que_la_invalidaria: str = ""
    propuesta_niveles: str = ""

    @field_validator("ticker")
    @classmethod
    def _limpiar(cls, v: str) -> str:
        return str(v or "").strip().upper()

    @field_validator("veredicto")
    @classmethod
    def _acotar(cls, v: str) -> str:
        clave = str(v or "").strip().upper()
        return clave if clave in VEREDICTOS else "MANTENER"


class ThesisReviewResult(BaseModel):
    disponible: bool = True
    texto: str = ""
    veredictos: List[ThesisVerdict] = Field(default_factory=list)
    modelo: str = ""
    error: Optional[str] = None
    aviso_parseo: Optional[str] = None


class ThesisReviewer:
    def __init__(self, api_key: Optional[str] = None, model: str = REVIEW_MODEL):
        self.api_key = api_key if api_key is not None else ANTHROPIC_API_KEY
        self.model = model
        self.client = None
        self.is_live = False

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
                print("[ThesisReviewer] SDK `anthropic` no instalado. Revisión no disponible.")
            except Exception as exc:
                print(f"[ThesisReviewer] No se pudo instanciar el SDK ({exc}). Revisión no disponible.")

    # ------------------------------------------------------------------
    @staticmethod
    def _bloque_tesis(
        seleccionadas: Sequence[Seleccion],
        valuation: Optional[PortfolioValuation] = None,
    ) -> str:
        """Una ficha por tesis, con el racional COMPLETO.

        El estudio mensual recibe sólo los primeros 300 caracteres del
        racional de cada tesis, que en esta bóveda es el 12% de lo escrito:
        revisa posiciones contra un resumen. Aquí no -- si la pregunta es si
        la tesis sigue en pie, hay que leerla entera.
        """
        por_ticker = {
            p.ticker.upper(): p for p in (valuation.posiciones if valuation else [])
        }
        fichas = []
        for s in seleccionadas:
            t = s.tesis
            pos = por_ticker.get(t.ticker.upper())
            estado_pos = (
                f"{pos.valor_mercado_eur:,.2f} EUR ({pos.peso_pct:.2f}% del NAV), "
                f"cotiza a {pos.precio_cotizacion:,.2f} {pos.divisa_cotizacion}, "
                f"PnL {pos.pnl_eur:+,.2f} EUR ({pos.pnl_pct:+.2f}%)"
                if pos
                else "SIN POSICION ABIERTA (tesis en radar)"
            )
            fichas.append(
                f"""### {t.ticker} — {t.empresa}

- Estado actual: {estado_pos}
- Niveles declarados en la tesis: entrada {t.precio_entrada:,.2f} {t.divisa}, """
                f"""stop {t.stop_loss:,.2f}, target {t.target_precio:,.2f}, convicción {t.conviccion}/10
- Abierta el {t.fecha_apertura} | Sectores: {t.sectores or 'sin clasificar'}
- Seleccionada para revisión porque: {', '.join(s.motivos)}

Racional vigente (completo, tal cual está escrito en la bóveda):

{(t.racional or '').strip() or '_La nota no tiene racional escrito._'}
"""
            )
        return "\n---\n\n".join(fichas)

    @staticmethod
    def _prompt(
        bloque_tesis: str,
        mes: str,
        conclusion_estudio: str = "",
        contexto_noticias: str = "",
        contexto_diario: str = "",
    ) -> str:
        tickers = re.findall(r"^### (\S+) —", bloque_tesis, re.MULTILINE)
        listado = ", ".join(tickers) or "(ninguna)"
        return f"""Eres el CIO de un family office revisando sus propias tesis de
inversión al cierre de {mes}. No estás escribiendo tesis nuevas: estás
juzgando si las que ya tenías siguen en pie.

## Tesis a revisar

{bloque_tesis}

## Contexto del mes

CONCLUSIÓN DEL ESTUDIO MENSUAL QUE ACABAS DE ESCRIBIR:
{conclusion_estudio.strip() or "- Sin estudio mensual este mes."}

CONTROLES DIARIOS DEL MES:
{contexto_diario.strip() or "- Sin controles diarios registrados."}

ESCANEOS SEMANALES DE NOTICIAS DEL MES:
{contexto_noticias.strip() or "- Sin escaneos de noticias este mes."}

## Qué tienes que hacer

Para CADA una de estas tesis ({listado}), responde a cuatro preguntas, con
los datos de arriba y sin inventar ninguno:

1. **Veredicto**: MANTENER, AMPLIAR, REDUCIR o CERRAR.
2. **Qué ha cambiado** desde que escribiste la tesis: hechos concretos del
   mes, no impresiones. Si no ha cambiado nada relevante, dilo así de claro.
3. **Qué sigue en pie**: qué parte del foso económico original se ha
   confirmado o al menos no se ha deteriorado.
4. **Qué la invalidaría ahora**: el criterio de invalidez actualizado. Puede
   ser el mismo que escribiste al abrirla; si ha cambiado, di por qué.

Sé honesto cuando la tesis se haya roto. Una tesis que se mantiene sólo
porque la posición está en pérdidas es la forma más cara de equivocarse, y el
mandato de esta casa antepone la preservación del capital a tener razón.

## Lo que NO debes hacer

**No propongas cambiar el stop-loss ni la convicción como si fueras a
aplicarlos.** No puedes: el stop-loss es la única salida obligatoria del
mandato, y renegociarlo cada mes con la excusa de que "la tesis sigue
intacta" es exactamente cómo una posición perdedora sobrevive a su propia
invalidación. Si de verdad crees que un nivel debería moverse, escríbelo en
`propuesta_niveles` como una PROPUESTA razonada dirigida a una persona, que
decidirá. Deja ese campo vacío si no propones nada.

**No reescribas la tesis original.** Lo que se escribió en su día se conserva
tal cual; tú añades una capa fechada encima. No intentes corregir, resumir ni
sustituir el racional vigente.

## Formato de la respuesta

Escribe en español. Primero una síntesis breve en Markdown (3-6 viñetas): qué
patrón ves en el conjunto de las tesis revisadas, cuál te preocupa más y por
qué.

Después, un bloque de código `json` con un veredicto por tesis, en este
formato exacto y con una entrada por cada ticker de la lista de arriba:

```json
{{
  "veredictos": [
    {{
      "ticker": "XYZ",
      "veredicto": "MANTENER",
      "que_ha_cambiado": "Dos o tres frases con hechos del mes.",
      "que_sigue_en_pie": "Qué parte del foso se ha confirmado.",
      "que_la_invalidaria": "El criterio de invalidez vigente.",
      "propuesta_niveles": ""
    }}
  ]
}}
```

Ese bloque `json` debe ser lo último de tu respuesta y debe ser JSON válido.
"""

    # ------------------------------------------------------------------
    def review(
        self,
        seleccionadas: Sequence[Seleccion],
        mes: str,
        valuation: Optional[PortfolioValuation] = None,
        conclusion_estudio: str = "",
        contexto_noticias: str = "",
        contexto_diario: str = "",
    ) -> ThesisReviewResult:
        """Revisa las tesis seleccionadas. No escribe nada en la bóveda."""
        if not seleccionadas:
            return ThesisReviewResult(
                texto="_Ninguna tesis necesitaba revisión este mes._"
            )

        if not (self.is_live and self.client):
            return ThesisReviewResult(
                disponible=False,
                texto=(
                    "_No hay clave de Claude en vivo (`ANTHROPIC_API_KEY`): las tesis "
                    "no se han revisado este mes._"
                ),
                error="sin API en vivo",
            )

        prompt = self._prompt(
            self._bloque_tesis(seleccionadas, valuation),
            mes=mes,
            conclusion_estudio=conclusion_estudio,
            contexto_noticias=contexto_noticias,
            contexto_diario=contexto_diario,
        )

        parametros: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": REVIEW_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if REVIEW_EFFORT:
            parametros["output_config"] = {"effort": REVIEW_EFFORT}

        try:
            respuesta = self._invocar(parametros)
        except Exception as exc:
            return ThesisReviewResult(disponible=False, modelo=self.model, error=str(exc))

        texto = "".join(
            b.text for b in respuesta.content if getattr(b, "type", "") == "text"
        ).strip()
        if not texto:
            return ThesisReviewResult(
                disponible=False,
                modelo=self.model,
                error=(
                    "la respuesta de la API no contenía texto "
                    f"(stop_reason={getattr(respuesta, 'stop_reason', None)!r}); si es "
                    "'max_tokens', sube SHARKY_REVIEW_MAX_TOKENS o baja SHARKY_REVIEW_EFFORT"
                ),
            )

        esperados = [s.ticker.upper() for s in seleccionadas]
        veredictos, aviso = self._extraer_veredictos(texto, esperados)
        return ThesisReviewResult(
            texto=_BLOQUE_JSON.sub("", texto).strip(),
            veredictos=veredictos,
            modelo=self.model,
            aviso_parseo=aviso,
        )

    def _invocar(self, parametros: Dict[str, Any]):
        cliente = self.client
        if cliente is None:  # `review` ya lo comprobo; esto es para el tipador
            raise RuntimeError("revisor sin cliente de la API")
        if parametros["max_tokens"] > MAX_TOKENS_SIN_STREAMING:
            with cliente.messages.stream(**parametros) as stream:
                return stream.get_final_message()
        return cliente.messages.create(**parametros)

    # ------------------------------------------------------------------
    @staticmethod
    def _extraer_veredictos(texto: str, esperados: Sequence[str]):
        """Lee el bloque `json` final y lo filtra a las tesis que se pidieron.

        Un veredicto sobre un ticker que no estaba en la selección se
        descarta: el revisor no puede anotar una tesis que no ha leído.
        """
        coincidencias = _BLOQUE_JSON.findall(texto or "")
        if not coincidencias:
            return [], "la revisión no incluía el bloque `json` de veredictos"

        try:
            datos = json.loads(coincidencias[-1])
        except ValueError as exc:
            return [], f"el bloque `json` de veredictos no era JSON válido ({exc})"

        crudos = datos.get("veredictos") if isinstance(datos, dict) else datos
        if not isinstance(crudos, list):
            return [], "el bloque `json` no contenía una lista de veredictos"

        permitidos = {t.upper() for t in esperados}
        veredictos: List[ThesisVerdict] = []
        vistos = set()
        for crudo in crudos:
            if not isinstance(crudo, dict):
                continue
            ticker = str(crudo.get("ticker", "")).strip().upper()
            if ticker not in permitidos or ticker in vistos:
                continue
            try:
                veredictos.append(ThesisVerdict(
                    ticker=ticker,
                    veredicto=str(crudo.get("veredicto") or "MANTENER"),
                    que_ha_cambiado=str(crudo.get("que_ha_cambiado") or ""),
                    que_sigue_en_pie=str(crudo.get("que_sigue_en_pie") or ""),
                    que_la_invalidaria=str(crudo.get("que_la_invalidaria") or ""),
                    propuesta_niveles=str(crudo.get("propuesta_niveles") or ""),
                ))
            except (TypeError, ValueError):
                continue
            vistos.add(ticker)

        if not veredictos:
            return [], "el bloque `json` no contenía ningún veredicto legible"

        faltan = sorted(permitidos - vistos)
        aviso = (
            f"la revisión no devolvió veredicto para: {', '.join(faltan)}"
            if faltan else None
        )
        return veredictos, aviso
