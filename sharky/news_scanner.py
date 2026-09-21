"""
Escaneo semanal de noticias relevantes para los activos en cartera.

Nivel semanal de la cadencia de razonamiento (ver `claude_client.py`): no
analiza precios ni riesgo por sí mismo, busca en la web qué se ha publicado
esta semana sobre cada posición (resultados, M&A, cambios regulatorios,
movimientos de analistas, contexto sectorial/geopolítico) y deja una nota
fechada en la bóveda, con las fuentes citadas.

Recibe como contexto las conclusiones de los controles diarios de los
últimos 7 días y las posiciones que esos controles marcaron "a vigilar"
(movimientos fuertes): así busca primero lo que de verdad se movió, en vez
de repasar la cartera a ciegas. Termina con `## Conclusión de la semana`,
que es lo que relee el estudio mensual.

Se apoya en la tool de búsqueda web nativa de la API de Claude
(`web_search_20250305`): sin ella, Claude no tiene forma de saber qué ha
pasado esta semana. A diferencia de `ClaudeBrainClient`, aquí no hay "modo
simulado" con sentido -- no existe una prosa de plantilla determinista que
resuma noticias reales que nunca se buscaron, así que sin clave de API en
vivo el escaneo simplemente no se ejecuta y lo declara.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # el SDK se importa en perezoso (ver __init__); aquí sólo tipos
    from anthropic.types import MessageParam

from sharky.claude_client import CONCLUSION_SEMANA
from sharky.config import (
    ANTHROPIC_API_KEY,
    API_KEY_PLACEHOLDERS,
    NEWS_EFFORT,
    NEWS_MAX_BUSQUEDAS_POR_ACTIVO,
    NEWS_MAX_BUSQUEDAS_TOTAL,
    NEWS_MAX_TOKENS_INFORME,
    NEWS_MODEL,
    has_live_api_key,
)
from sharky.models import Position

WEB_SEARCH_TOOL_TYPE = "web_search_20250305"

# La API corta un turno con muchas búsquedas en `stop_reason='pause_turn'`;
# se reanuda reenviando lo ya generado. Tope para no encadenar sin fin.
MAX_REANUDACIONES = 3


class NewsScanResult(BaseModel):
    disponible: bool = True
    texto: str = ""
    fuentes: List[str] = Field(default_factory=list)
    modelo: str = ""
    error: Optional[str] = None
    busquedas_realizadas: int = 0


class NewsScanner:
    def __init__(self, api_key: Optional[str] = None, model: str = NEWS_MODEL):
        self.api_key = api_key if api_key is not None else ANTHROPIC_API_KEY
        self.model = model
        self.client = None
        self.is_live = False

        # Una clave explícita (aunque sea vacía) manda sobre la del `.env`,
        # igual que en `ClaudeBrainClient`.
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
                print("[NewsScanner] SDK `anthropic` no instalado. Escaneo de noticias no disponible.")
            except Exception as exc:
                print(f"[NewsScanner] No se pudo instanciar el SDK ({exc}). Escaneo de noticias no disponible.")

    # ------------------------------------------------------------------
    @staticmethod
    def _listado_activos(positions: List[Position]) -> str:
        return "\n".join(
            f"- {p.ticker} — {p.nombre} (sector: {p.sector or 'sin clasificar'})"
            for p in positions
        )

    @staticmethod
    def _prompt(
        positions: List[Position],
        contexto_semana: str = "",
        prioritarios: Optional[List[str]] = None,
    ) -> str:
        listado = NewsScanner._listado_activos(positions)
        en_cartera = {p.ticker for p in positions}
        prioritarios = [t for t in (prioritarios or []) if t in en_cartera]
        bloque_prioritarios = (
            "\n".join(f"- {t}" for t in prioritarios)
            if prioritarios
            else "- Ninguna: ningún control diario marcó movimientos fuertes."
        )
        return f"""Eres el analista de noticias de un family office. Busca en la web
noticias RELEVANTES Y RECIENTES (de esta última semana; si de verdad no hay
nada de estos últimos 7 días, la noticia relevante más reciente que
encuentres) sobre cada uno de estos activos en cartera:

{listado}

CONTEXTO DE LOS ÚLTIMOS 7 DÍAS (conclusiones de tus propios controles
diarios de la cartera: precios, movimientos y cumplimiento del mandato):
{contexto_semana.strip() or "- Sin controles diarios esta semana."}

POSICIONES A INVESTIGAR PRIMERO (se movieron con fuerza o incumplen algo):
{bloque_prioritarios}

Para cada activo, busca específicamente: resultados o guidance financiero,
fusiones/adquisiciones, cambios regulatorios o sancionadores, movimientos de
analistas (subidas/bajadas de precio objetivo o recomendación), contratos o
pedidos relevantes, y contexto sectorial/geopolítico que le afecte
directamente. Si el contexto de arriba muestra un movimiento fuerte en una
posición, busca qué lo explica.

Redacta la respuesta en Markdown y en español, con una sección `## {{TICKER}}`
por activo, en el mismo orden que la lista de arriba. Dentro de cada
sección: 2-4 líneas con lo más relevante encontrado y por qué le importa a
esta posición concreta. Si de verdad no encuentras nada relevante de la
semana, dilo explícitamente en vez de inventar o rellenar con
generalidades. No mezcles activos: cada sección habla solo de su propio
ticker.

Termina SIEMPRE con una sección `## {CONCLUSION_SEMANA}` de 2 a 5 viñetas:
qué ha cambiado esta semana para la cartera, cruzando las noticias con el
contexto de los controles diarios. La leerá el estudio mensual.
"""

    # ------------------------------------------------------------------
    def scan(
        self,
        positions: List[Position],
        contexto_semana: str = "",
        prioritarios: Optional[List[str]] = None,
    ) -> NewsScanResult:
        """Busca y sintetiza noticias recientes para cada posición dada.

        Una llamada única para toda la cartera (no una por activo): más
        barato y deja que el modelo relacione contexto compartido -- p.ej.
        un mismo evento geopolítico que afecta a dos posiciones del mismo
        sector -- en vez de redescubrirlo por separado en cada llamada.

        `contexto_semana` son las conclusiones de los controles diarios de
        la semana ya formateadas (`ClaudeBrainClient._formatear_memoria`), y
        `prioritarios` los tickers que esos controles marcaron a vigilar.
        """
        if not positions:
            return NewsScanResult(texto="_Sin posiciones en cartera: nada que buscar._")

        if not (self.is_live and self.client):
            return NewsScanResult(
                disponible=False,
                texto=(
                    "_No hay clave de Claude en vivo (`ANTHROPIC_API_KEY`): no se pudo "
                    "buscar noticias reales esta semana._"
                ),
                error="sin API en vivo",
            )

        # Techo absoluto además del escalado por activo: sin él, una cartera
        # grande dispara un número de búsquedas sin límite (ver INFRA-6).
        max_busquedas = min(
            NEWS_MAX_BUSQUEDAS_TOTAL, len(positions) * NEWS_MAX_BUSQUEDAS_POR_ACTIVO
        )

        mensajes: "List[MessageParam]" = [
            {"role": "user", "content": self._prompt(positions, contexto_semana, prioritarios)}
        ]
        parametros: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": NEWS_MAX_TOKENS_INFORME,
            "tools": [
                {
                    "type": WEB_SEARCH_TOOL_TYPE,
                    "name": "web_search",
                    "max_uses": max_busquedas,
                }
            ],
        }
        if NEWS_EFFORT:
            parametros["output_config"] = {"effort": NEWS_EFFORT}

        bloques: List[Any] = []
        try:
            respuesta = self.client.messages.create(messages=mensajes, **parametros)
            bloques.extend(respuesta.content)
            reanudaciones = 0
            while (
                getattr(respuesta, "stop_reason", None) == "pause_turn"
                and reanudaciones < MAX_REANUDACIONES
            ):
                # Reanudar el mismo turno: se reenvía lo generado tal cual y
                # la API continúa donde lo dejó.
                mensajes = mensajes + [{"role": "assistant", "content": respuesta.content}]
                respuesta = self.client.messages.create(messages=mensajes, **parametros)
                bloques.extend(respuesta.content)
                reanudaciones += 1
        except Exception as exc:
            return NewsScanResult(disponible=False, modelo=self.model, error=str(exc))

        texto_partes: List[str] = []
        fuentes: List[str] = []
        vistas = set()
        busquedas = 0

        for bloque in bloques:
            tipo = getattr(bloque, "type", "")
            if tipo == "text":
                texto_partes.append(bloque.text)
                for cita in getattr(bloque, "citations", None) or []:
                    url = getattr(cita, "url", None)
                    if not url or url in vistas:
                        continue
                    vistas.add(url)
                    titulo = getattr(cita, "title", None) or url
                    fuentes.append(f"[{titulo}]({url})")
            elif tipo == "server_tool_use" and getattr(bloque, "name", "") == "web_search":
                busquedas += 1

        texto = "".join(texto_partes).strip()
        if not texto:
            return NewsScanResult(
                disponible=False,
                modelo=self.model,
                error=(
                    "la respuesta de la API no contenía texto "
                    f"(stop_reason={getattr(respuesta, 'stop_reason', None)!r}); si es "
                    "'max_tokens', sube SHARKY_NEWS_MAX_TOKENS_INFORME o baja SHARKY_NEWS_EFFORT"
                ),
                busquedas_realizadas=busquedas,
            )

        return NewsScanResult(
            texto=texto,
            fuentes=fuentes,
            modelo=self.model,
            busquedas_realizadas=busquedas,
        )
