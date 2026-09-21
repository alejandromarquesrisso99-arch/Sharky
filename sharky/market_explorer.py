"""
Explorador de mercado: búsqueda activa de oportunidades asimétricas nuevas.

El detector de oportunidades (`sharky.opportunity_detector`) es una puerta,
no una red: confirma o descarta con datos reales los nombres de
`UNIVERSO_CONVICCION`, que es una lista escrita a mano. Nunca puede encontrar
una idea que no esté ya en esa lista. Este módulo es la red que faltaba --
sale a buscar candidatos nuevos en la web -- y es lo único de Sharky que
propone activos que nadie había escrito antes.

Por eso usa el modelo más capaz disponible (`EXPLORER_MODEL`, Claude Opus 5
por defecto) con el presupuesto más alto de la casa: redactar una tesis de
inversión desde cero, cruzando sectores y geopolítica, es el razonamiento más
exigente de toda la cadencia. Resumir noticias de posiciones que ya tienes
(el escaneo semanal) es bastante más barato en todos los sentidos.

**El reparto de responsabilidades no se mueve.** Claude aporta exactamente lo
mismo que aporta `UNIVERSO_CONVICCION`: convicción cualitativa -- qué vigilar,
por qué hay foso, qué lo rompería. Los números siguen saliendo de precios
reales, en el mismo filtro de siempre (`OpportunityDetector.scan_universe`):
caída desde el máximo anual, tendencia sobre la media de 200 sesiones, stop
por volatilidad realizada y R:R mínimo. El prompt prohíbe explícitamente que
el modelo proponga precios, stops u objetivos, porque un nivel inventado por
un modelo tiene exactamente el mismo aspecto que uno medido y ninguna de sus
garantías.

Consecuencia deliberada: una exploración puede terminar con ocho candidatos
interesantes y **cero alertas**. Eso no es un fallo, es el filtro haciendo su
trabajo -- la empresa puede ser excelente y su precio no ofrecer asimetría
hoy. El informe guarda el veredicto de cada candidato para que se vea.

Como el escaneo semanal, se apoya en la tool de búsqueda web nativa de la API
y no tiene modo simulado: sin clave en vivo no explora nada y lo declara.
"""

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from sharky.claude_client import CONCLUSION_EXPLORACION
from sharky.config import (
    ANTHROPIC_API_KEY,
    API_KEY_PLACEHOLDERS,
    EXPLORER_EFFORT,
    EXPLORER_MAX_BUSQUEDAS,
    EXPLORER_MAX_CANDIDATOS,
    EXPLORER_MAX_TOKENS,
    EXPLORER_MODEL,
    MAX_POSITION_SIZE_PCT,
    has_live_api_key,
)
from sharky.opportunity_detector import (
    CAIDA_MAXIMA_PCT,
    CAIDA_MINIMA_PCT,
    CONVICCION_MINIMA,
    RR_MINIMO,
)

# Por encima de este `max_tokens` el SDK exige streaming (estima que la
# petición tardaría más de 10 minutos). Mismo umbral que `claude_client`.
MAX_TOKENS_SIN_STREAMING = 20000

# La variante con filtrado dinámico sólo existe en los modelos recientes; un
# modelo anterior la rechaza. Como `EXPLORER_MODEL` es configurable, el tipo
# de tool se deriva del modelo en vez de fijarse a ciegas.
WEB_SEARCH_DINAMICO = "web_search_20260209"
WEB_SEARCH_BASICO = "web_search_20250305"
_FAMILIAS_CON_BUSQUEDA_DINAMICA = (
    "opus-5", "opus-4-8", "opus-4-7", "opus-4-6",
    "sonnet-5", "sonnet-4-6",
    "fable-5", "mythos-5",
)

# La API corta un turno con muchas búsquedas en `stop_reason='pause_turn'`;
# se reanuda reenviando lo ya generado. Tope para no encadenar sin fin.
MAX_REANUDACIONES = 3

# Bloque ```json ... ``` del final del informe. Se toma el último: si el
# modelo enseña un ejemplo a mitad de texto, el que manda es el de cierre.
_BLOQUE_JSON = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)


def tipo_web_search(modelo: str) -> str:
    """Tipo de tool de búsqueda web admitido por `modelo`."""
    clave = (modelo or "").lower()
    return (
        WEB_SEARCH_DINAMICO
        if any(f in clave for f in _FAMILIAS_CON_BUSQUEDA_DINAMICA)
        else WEB_SEARCH_BASICO
    )


class OpportunityCandidate(BaseModel):
    """Un candidato propuesto por el explorador, sin un solo precio dentro.

    Es deliberado que este modelo no tenga `precio`, `stop_loss` ni
    `target_precio`: el explorador no los emite y el filtro cuantitativo los
    calcula después con datos de mercado. Si algún día alguien añade esos
    campos aquí, habrá borrado la frontera que separa la convicción de la
    confirmación.
    """

    ticker: str
    simbolo: str = ""          # símbolo de Yahoo Finance, si difiere del ticker
    empresa: str = ""
    conviccion: int = CONVICCION_MINIMA
    max_cartera: float = 5.0
    tesis: str = ""
    catalizadores: List[str] = Field(default_factory=list)
    riesgos: List[str] = Field(default_factory=list)
    sector: str = ""

    @field_validator("ticker", "simbolo")
    @classmethod
    def _limpiar(cls, v: str) -> str:
        return str(v or "").strip().upper()

    @field_validator("conviccion")
    @classmethod
    def _acotar_conviccion(cls, v: int) -> int:
        return max(1, min(10, int(v)))

    @field_validator("max_cartera")
    @classmethod
    def _acotar_peso(cls, v: float) -> float:
        """Ningún candidato puede pedir más peso del que permite el mandato.

        El modelo escribe este número, así que se acota aquí y no sólo al
        dimensionar: una alerta que pidiera un 15% contradiría
        [[Reglas_De_Supervivencia]] desde el propio texto de la nota, aunque
        el `RiskGovernor` la recortara después.
        """
        return max(1.0, min(MAX_POSITION_SIZE_PCT, float(v)))

    def perfil(self) -> dict:
        """Forma que espera `OpportunityDetector.scan_universe`."""
        return {
            "empresa": self.empresa or self.ticker,
            "conviccion": self.conviccion,
            "max_cartera": self.max_cartera,
            "tesis": self.tesis,
            "catalizadores": list(self.catalizadores),
            "riesgos": list(self.riesgos),
        }


class MarketExplorationResult(BaseModel):
    disponible: bool = True
    texto: str = ""
    candidatos: List[OpportunityCandidate] = Field(default_factory=list)
    fuentes: List[str] = Field(default_factory=list)
    modelo: str = ""
    error: Optional[str] = None
    busquedas_realizadas: int = 0
    # Por qué no se pudo leer la lista de candidatos, cuando el informe sí
    # llegó. Se distingue de `error` (que significa "no hubo exploración").
    aviso_parseo: Optional[str] = None


class MarketExplorer:
    def __init__(self, api_key: Optional[str] = None, model: str = EXPLORER_MODEL):
        self.api_key = api_key if api_key is not None else ANTHROPIC_API_KEY
        self.model = model
        self.client = None
        self.is_live = False

        # Una clave explícita (aunque sea vacía) manda sobre la del `.env`,
        # igual que en `ClaudeBrainClient` y `NewsScanner`.
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
                print("[MarketExplorer] SDK `anthropic` no instalado. Exploración no disponible.")
            except Exception as exc:
                print(f"[MarketExplorer] No se pudo instanciar el SDK ({exc}). Exploración no disponible.")

    # ------------------------------------------------------------------
    @staticmethod
    def _prompt(
        ya_cubierto: List[str],
        sectores: Optional[Dict[str, float]] = None,
        estado_vital: str = "",
        efectivo_pct: float = 0.0,
        contexto_noticias: str = "",
        max_candidatos: int = EXPLORER_MAX_CANDIDATOS,
    ) -> str:
        bloque_cubierto = ", ".join(ya_cubierto) if ya_cubierto else "(nada todavía)"
        bloque_sectores = (
            "\n".join(f"- {s}: {w:.1f}% del NAV" for s, w in sorted(
                (sectores or {}).items(), key=lambda kv: -kv[1]
            ))
            or "- Cartera sin exposición sectorial registrada."
        )
        return f"""Eres el analista de ideas nuevas de un family office europeo. Tu
encargo de hoy NO es repasar la cartera: es salir a buscar en el mercado
oportunidades asimétricas que esta firma todavía no está vigilando.

## Lo que ya está cubierto (NO lo propongas)

Estos activos ya están en cartera, ya tienen tesis abierta, ya tienen una
alerta viva o ya forman parte del universo de vigilancia permanente. Proponer
cualquiera de ellos es trabajo perdido:

{bloque_cubierto}

## Contexto de la firma

- Estado vital: {estado_vital or "sin registrar"}
- Liquidez disponible: {efectivo_pct:.1f}% del NAV
- Exposición sectorial actual:
{bloque_sectores}

La cartera está denominada en EUR y se custodia en un bróker europeo
minorista: prioriza instrumentos realmente accesibles desde Europa (acciones
de mercados USA y europeos, ETF UCITS). Evita microcaps sin liquidez,
mercados exóticos y derivados.

{contexto_noticias}

## Qué buscar

Busca en la web, con datos de las últimas semanas, empresas o temas donde
exista una **asimetría real**: un negocio con foso económico defendible cuyo
precio haya retrocedido por una razón identificable y temporal, no por
deterioro estructural. Fíjate en:

- cambios regulatorios, geopolíticos o de política industrial que crean
  ganadores estructurales todavía no descontados;
- cuellos de botella físicos (energía, materiales, capacidad industrial)
  donde la oferta no puede responder rápido a la demanda;
- líderes de su nicho castigados por un problema puntual (un trimestre malo,
  un susto regulatorio, una rotación sectorial) con la tesis intacta;
- huecos evidentes en la exposición sectorial de arriba, si los ves.

Propón **como máximo {max_candidatos} candidatos**, y sólo aquellos en los que
tu convicción sea de {CONVICCION_MINIMA}/10 o superior. Menos candidatos bien
fundados valen más que una lista larga: si sólo hay dos ideas de verdad, propón
dos. Si de verdad no encuentras ninguna que supere ese listón, dilo
explícitamente y no rellenes.

## Lo que NO debes hacer

**No propongas precios de entrada, stop-loss, objetivos ni ratios
riesgo/beneficio.** No es tu tarea y no tienes los datos para hacerlo bien.
Sharky calcula esos niveles después, con la estructura real de precios de cada
candidato: distancia al máximo de 52 semanas (exige entre {CAIDA_MINIMA_PCT:.0f}%
y {CAIDA_MAXIMA_PCT:.0f}%), posición frente a la media de 200 sesiones, stop
derivado de la volatilidad realizada y un R:R mínimo de {RR_MINIMO:.1f}:1.
Varios de tus candidatos NO pasarán ese filtro, y eso es correcto y esperado:
tu trabajo es que la tesis cualitativa sea sólida, no adivinar si hoy el precio
acompaña.

Tampoco afirmes cifras concretas (resultados, contratos, múltiplos) sin haberlas
encontrado en una fuente: cita lo que encuentres y no rellenes lo que no.

## Formato de la respuesta

Escribe en español y en Markdown.

1. Una sección `## {{TICKER}} — {{Nombre de la empresa}}` por candidato, con
   3-6 líneas: qué hace, dónde está el foso, qué ha pasado recientemente que
   abre la oportunidad y qué la invalidaría.
2. Una sección `## {CONCLUSION_EXPLORACION}` con 2 a 5 viñetas: qué tema de
   fondo has visto repetirse, qué candidato te parece el más sólido y por qué,
   y qué descartaste y por qué lo descartaste.
3. Por último, un bloque de código `json` con la lista estructurada de tus
   candidatos, en este formato exacto:

```json
{{
  "candidatos": [
    {{
      "ticker": "XYZ",
      "simbolo_yahoo": "XYZ",
      "empresa": "Nombre completo S.A.",
      "sector": "Sector principal",
      "conviccion": 8,
      "max_cartera": 5.0,
      "tesis": "Dos o tres frases con el foso económico y por qué hay asimetría.",
      "catalizadores": ["Catalizador 1", "Catalizador 2", "Catalizador 3"],
      "riesgos": ["Riesgo 1", "Riesgo 2", "Riesgo 3"]
    }}
  ]
}}
```

`simbolo_yahoo` debe ser el símbolo EXACTO con el que ese activo cotiza en
Yahoo Finance, con su sufijo de mercado si lo necesita (por ejemplo `RHM.DE`
para Rheinmetall en XETRA, `AIR.PA` para Airbus en París). Sharky pedirá la
cotización con ese símbolo: si está mal, el candidato se descarta por falta de
datos. Si el activo cotiza en varios mercados, da el que tenga más liquidez y
sea accesible desde Europa.

`max_cartera` es el peso máximo que asignarías a ese activo, en % del NAV,
nunca por encima de {MAX_POSITION_SIZE_PCT:.0f}%.

Ese bloque `json` debe ser lo último de tu respuesta, y debe ser JSON válido.
"""

    # ------------------------------------------------------------------
    def explore(
        self,
        ya_cubierto: Optional[List[str]] = None,
        sectores: Optional[Dict[str, float]] = None,
        estado_vital: str = "",
        efectivo_pct: float = 0.0,
        contexto_noticias: str = "",
        max_candidatos: int = EXPLORER_MAX_CANDIDATOS,
    ) -> MarketExplorationResult:
        """Busca candidatos nuevos y devuelve informe + lista estructurada.

        No toca la bóveda ni emite alertas: eso es responsabilidad de
        `SharkyAgent.run_market_exploration`, que pasa cada candidato por el
        filtro cuantitativo antes de escribir nada.
        """
        if not (self.is_live and self.client):
            return MarketExplorationResult(
                disponible=False,
                texto=(
                    "_No hay clave de Claude en vivo (`ANTHROPIC_API_KEY`): no se pudo "
                    "explorar el mercado._"
                ),
                error="sin API en vivo",
            )

        prompt = self._prompt(
            ya_cubierto=sorted(ya_cubierto or []),
            sectores=sectores,
            estado_vital=estado_vital,
            efectivo_pct=efectivo_pct,
            contexto_noticias=contexto_noticias,
            max_candidatos=max_candidatos,
        )

        # Al reanudar un `pause_turn` esta lista lleva ademas bloques de
        # contenido del SDK, no solo dicts: de ahi el `Any`.
        mensajes: List[Any] = [{"role": "user", "content": prompt}]
        parametros: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": EXPLORER_MAX_TOKENS,
            "tools": [
                {
                    "type": tipo_web_search(self.model),
                    "name": "web_search",
                    "max_uses": EXPLORER_MAX_BUSQUEDAS,
                }
            ],
        }
        if EXPLORER_EFFORT:
            parametros["output_config"] = {"effort": EXPLORER_EFFORT}

        bloques: List[Any] = []
        try:
            respuesta = self._invocar(mensajes, parametros)
            bloques.extend(respuesta.content)
            reanudaciones = 0
            while (
                getattr(respuesta, "stop_reason", None) == "pause_turn"
                and reanudaciones < MAX_REANUDACIONES
            ):
                # Reanudar el mismo turno: se reenvía lo generado tal cual y
                # la API continúa donde lo dejó.
                mensajes = mensajes + [{"role": "assistant", "content": respuesta.content}]
                respuesta = self._invocar(mensajes, parametros)
                bloques.extend(respuesta.content)
                reanudaciones += 1
        except Exception as exc:
            return MarketExplorationResult(disponible=False, modelo=self.model, error=str(exc))

        texto, fuentes, busquedas = self._desglosar(bloques)

        if not texto:
            return MarketExplorationResult(
                disponible=False,
                modelo=self.model,
                error=(
                    "la respuesta de la API no contenía texto "
                    f"(stop_reason={getattr(respuesta, 'stop_reason', None)!r}); si es "
                    "'max_tokens', sube SHARKY_EXPLORER_MAX_TOKENS o baja "
                    "SHARKY_EXPLORER_EFFORT"
                ),
                busquedas_realizadas=busquedas,
            )

        candidatos, aviso = self._extraer_candidatos(texto, max_candidatos)
        return MarketExplorationResult(
            texto=self._sin_bloque_json(texto),
            candidatos=candidatos,
            fuentes=fuentes,
            modelo=self.model,
            busquedas_realizadas=busquedas,
            aviso_parseo=aviso,
        )

    def _invocar(self, mensajes: List[Any], parametros: Dict[str, Any]):
        """Una llamada a la API, por streaming si el presupuesto lo exige.

        Con `max_tokens` alto el SDK rechaza la petición sin streaming porque
        estima más de diez minutos. El explorador es precisamente el perfil
        con el presupuesto más alto, así que este camino es el normal, no el
        excepcional.
        """
        cliente = self.client
        if cliente is None:  # `explore` ya lo comprobo; esto es para el tipador
            raise RuntimeError("explorador sin cliente de la API")

        if parametros["max_tokens"] > MAX_TOKENS_SIN_STREAMING:
            with cliente.messages.stream(messages=mensajes, **parametros) as stream:
                return stream.get_final_message()
        return cliente.messages.create(messages=mensajes, **parametros)

    # ------------------------------------------------------------------
    @staticmethod
    def _desglosar(bloques: List[Any]):
        """Separa texto, fuentes citadas y número de búsquedas realizadas."""
        partes: List[str] = []
        fuentes: List[str] = []
        vistas = set()
        busquedas = 0

        for bloque in bloques:
            tipo = getattr(bloque, "type", "")
            if tipo == "text":
                partes.append(bloque.text)
                for cita in getattr(bloque, "citations", None) or []:
                    url = getattr(cita, "url", None)
                    if not url or url in vistas:
                        continue
                    vistas.add(url)
                    titulo = getattr(cita, "title", None) or url
                    fuentes.append(f"[{titulo}]({url})")
            elif tipo == "server_tool_use" and getattr(bloque, "name", "") == "web_search":
                busquedas += 1

        return "".join(partes).strip(), fuentes, busquedas

    @staticmethod
    def _sin_bloque_json(texto: str) -> str:
        """El informe legible, sin el bloque de datos del final.

        El JSON ya viaja como `candidatos`: dejarlo además en la nota de la
        bóveda sería enseñar dos veces lo mismo, y la segunda en crudo.
        """
        return _BLOQUE_JSON.sub("", texto).strip()

    @staticmethod
    def _extraer_candidatos(texto: str, max_candidatos: int):
        """Lee la lista estructurada del bloque `json` final.

        Devuelve `(candidatos, aviso)`. Que el bloque falte o esté mal formado
        no invalida el informe -- la prosa sigue siendo útil y se guarda --
        pero sí impide emitir alertas, y eso se dice en la nota en vez de
        quedar como un silencio.
        """
        coincidencias = _BLOQUE_JSON.findall(texto or "")
        if not coincidencias:
            return [], "el informe no incluía el bloque `json` de candidatos"

        try:
            datos = json.loads(coincidencias[-1])
        except ValueError as exc:
            return [], f"el bloque `json` de candidatos no era JSON válido ({exc})"

        crudos = datos.get("candidatos") if isinstance(datos, dict) else datos
        if not isinstance(crudos, list):
            return [], "el bloque `json` no contenía una lista de candidatos"

        candidatos: List[OpportunityCandidate] = []
        vistos = set()
        for crudo in crudos:
            if not isinstance(crudo, dict):
                continue
            ticker = str(crudo.get("ticker", "")).strip().upper()
            if not ticker or ticker in vistos:
                continue
            try:
                candidato = OpportunityCandidate(
                    ticker=ticker,
                    simbolo=str(crudo.get("simbolo_yahoo") or crudo.get("simbolo") or ticker),
                    empresa=str(crudo.get("empresa") or ticker),
                    sector=str(crudo.get("sector") or ""),
                    conviccion=int(crudo.get("conviccion") or CONVICCION_MINIMA),
                    max_cartera=float(crudo.get("max_cartera") or 5.0),
                    tesis=str(crudo.get("tesis") or ""),
                    catalizadores=[str(c) for c in (crudo.get("catalizadores") or [])],
                    riesgos=[str(r) for r in (crudo.get("riesgos") or [])],
                )
            except (TypeError, ValueError):
                continue
            vistos.add(ticker)
            candidatos.append(candidato)
            if len(candidatos) >= max_candidatos:
                break

        if not candidatos:
            return [], "el bloque `json` no contenía ningún candidato legible"
        return candidatos, None
