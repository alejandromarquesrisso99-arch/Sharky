"""
Configuración central de Sharky.

Fuente de verdad de los parámetros de supervivencia: los valores por defecto de
este módulo replican literalmente los axiomas de
`vault/00_Sistema/Reglas_De_Supervivencia.md` (v2.0). Si cambias uno aquí,
cambia también la nota, o el agente operará contra su propio mandato.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VAULT_DIR = BASE_DIR / "vault"
VAULT_PATH = Path(os.getenv("SHARKY_VAULT_PATH", DEFAULT_VAULT_DIR))

# --------------------------------------------------------------------------
# Divisa base
# --------------------------------------------------------------------------
# La cartera real está custodiada en Trade Republic y denominada en EUR.
# Todo NAV, PnL, coste base y límite de riesgo se expresa en esta divisa.
# Los activos que cotizan en otra divisa se convierten explícitamente vía
# `sharky.fx`, nunca por comparación directa de cifras.
#
# Fija a EUR, sin variable de entorno. Hasta 2026-09 existía
# SHARKY_BASE_CURRENCY, pero `FxProvider.FALLBACK_RATES_TO_EUR` está tabulada
# contra EUR pase lo que pase: cambiar la base sin reescribir esa tabla no
# convertía nada, sólo fingía hacerlo (con `base_currency="USD"`,
# `get_rate("EUR")` devolvía 1.0 en vez de la tasa real). Mismo criterio que
# ya se aplicó a SHARKY_EXECUTION_MODE y SHARKY_DD_CRITICO_PCT: se retira la
# opción en vez de dejarla viva sin proteger nada.
BASE_CURRENCY = "EUR"

# --------------------------------------------------------------------------
# Inteligencia artificial (Claude / Anthropic)
# --------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# Perfiles de razonamiento por cadencia. Cada nivel pide a Claude una cosa
# distinta y con un presupuesto distinto:
#
#   * Diario  -> sólo posiciones, precios, valor de mercado y cumplimiento de
#                las normas. Poco que deliberar: effort `low`.
#   * Semanal -> noticias de la cartera con el contexto de los últimos 7
#                controles diarios (ver NEWS_* más abajo): effort `medium`.
#   * Mensual -> estudio completo y reevaluación de posiciones con todo el
#                contexto del mes: effort `high`.
#
# claude-sonnet-5 piensa por defecto (adaptive thinking) y ese razonamiento
# sale del mismo `max_tokens` que el texto: con 4000 el log mostraba
# respuestas con sólo un bloque `thinking` y `stop_reason='max_tokens'`. El
# `effort` controla cuánto piensa; `max_tokens` es el techo de seguridad. Es
# un techo, no un gasto fijo: sólo se factura lo que se genera.
#
# `effort` vacío ("") no envía el parámetro, para modelos que no lo admiten.
# Por encima de ~21000 tokens el SDK rechaza peticiones sin streaming (estima
# más de 10 minutos): `ClaudeBrainClient._invocar` cambia a streaming solo.
MAX_TOKENS_DIARIO = int(os.getenv("SHARKY_MAX_TOKENS_DIARIO", "8000"))
EFFORT_DIARIO = os.getenv("SHARKY_EFFORT_DIARIO", "low").strip()

MAX_TOKENS_MENSUAL = int(os.getenv("SHARKY_MAX_TOKENS_MENSUAL", "32000"))
EFFORT_MENSUAL = os.getenv("SHARKY_EFFORT_MENSUAL", "high").strip()

# Resolución del CIO (`sharky committee`, a demanda). Misma profundidad que
# el estudio mensual, pero con un dossier más corto.
MAX_TOKENS_COMITE = int(os.getenv("SHARKY_MAX_TOKENS_COMITE", "16000"))

# Variación del precio de una posición desde el último control diario a
# partir de la cual el diario la marca "a vigilar": el escaneo semanal de
# noticias la investiga primero. Sin esto, un desplome a mitad de semana
# no se buscaría hasta el domingo como una posición más.
UMBRAL_MOVIMIENTO_VIGILANCIA_PCT = float(os.getenv("SHARKY_UMBRAL_MOVIMIENTO_PCT", "7"))

# Placeholders que NO cuentan como una API key válida.
API_KEY_PLACEHOLDERS = {
    "",
    "tu_api_key_aqui",
    "TU_ANTHROPIC_API_KEY_AQUI",
    "sk-ant-api03-...",
}

# --------------------------------------------------------------------------
# Escaneo semanal de noticias
# --------------------------------------------------------------------------
# Modelo para el escaneo semanal de noticias de los activos en cartera (usa
# la tool de búsqueda web de la API de Claude, ver `sharky/news_scanner.py`).
# Por defecto el mismo que el resto de la inteligencia de Sharky; se separa
# en su propia variable porque buscar en la web y sintetizar el informe
# diario no tienen por qué pedir la misma capacidad.
NEWS_MODEL = os.getenv("SHARKY_NEWS_MODEL", CLAUDE_MODEL)

# Día de la semana en el que toca el escaneo (0=lunes ... 6=domingo, como
# `date.weekday()`). Domingo por defecto: cierra la semana de mercado y dado
# que Sharky no corre como servicio permanente -- se lanza al encender el
# ordenador, ver `cmd_startup` en `cli.py` -- deja el contexto de noticias
# listo antes de que abra Wall Street el lunes. Si el ordenador no se
# enciende ese día, `SharkyAgent.noticias_semanales_pendiente` actúa de red
# de seguridad y lanza igualmente el escaneo en cuanto pasan 7 días desde el
# último, para que nunca quede huérfano indefinidamente -- mismo criterio
# que ya usa `BREACH_ESCALATION_DAYS` para no dejar pasar un incumplimiento
# sólo porque nadie volvió a mirar.
NEWS_SCAN_WEEKDAY = int(os.getenv("SHARKY_NEWS_SCAN_WEEKDAY", "6"))

# Búsquedas web máximas por activo en cartera dentro de un mismo escaneo
# semanal. Limita el gasto en carteras grandes: la tool de búsqueda web se
# factura por búsqueda además del coste de tokens habitual.
NEWS_MAX_BUSQUEDAS_POR_ACTIVO = int(os.getenv("SHARKY_NEWS_MAX_BUSQUEDAS_POR_ACTIVO", "3"))

# Techo absoluto de búsquedas del escaneo semanal, independiente del número de
# posiciones: sin él, `NEWS_MAX_BUSQUEDAS_POR_ACTIVO * len(posiciones)` escala
# sin límite con el tamaño de la cartera (ver INFRA-6).
NEWS_MAX_BUSQUEDAS_TOTAL = int(os.getenv("SHARKY_NEWS_MAX_BUSQUEDAS_TOTAL", "30"))

# Presupuesto del escaneo semanal de noticias (perfil semanal, ver arriba).
# Además del razonamiento, el modelo piensa entre búsquedas y redacta una
# síntesis de toda la cartera con citas.
NEWS_MAX_TOKENS_INFORME = int(os.getenv("SHARKY_NEWS_MAX_TOKENS_INFORME", "16000"))
NEWS_EFFORT = os.getenv("SHARKY_NEWS_EFFORT", "medium").strip()

# --------------------------------------------------------------------------
# Explorador de mercado (radar de oportunidades a demanda)
# --------------------------------------------------------------------------
# El detector determinista (`sharky/opportunity_detector.py`) sólo confirma o
# descarta los nombres de `UNIVERSO_CONVICCION`, que es una lista escrita a
# mano: nunca puede encontrar una idea que no esté ya en ella. El explorador
# es la pieza que cierra ese hueco -- busca en la web candidatos NUEVOS -- y
# por eso usa el modelo más capaz disponible: proponer una tesis de inversión
# desde cero es el razonamiento más exigente de toda la cadencia, muy por
# encima de resumir noticias o repasar posiciones.
#
# El reparto de responsabilidades NO cambia: Claude aporta la convicción
# cualitativa (qué vigilar y por qué), y la confirmación sigue saliendo de
# precios reales en el mismo filtro de siempre. El explorador no fija
# precios, stops ni objetivos.
EXPLORER_MODEL = os.getenv("SHARKY_EXPLORER_MODEL", "claude-opus-5")

# Presupuesto del explorador. Es el más alto de la casa porque el modelo
# piensa entre búsquedas, cruza sectores y redacta una tesis por candidato.
# Es un techo, no un gasto fijo: sólo se factura lo generado. Por encima de
# ~20000 la petición va por streaming (ver `MAX_TOKENS_SIN_STREAMING`).
EXPLORER_MAX_TOKENS = int(os.getenv("SHARKY_EXPLORER_MAX_TOKENS", "32000"))
EXPLORER_EFFORT = os.getenv("SHARKY_EXPLORER_EFFORT", "high").strip()

# Búsquedas web máximas por exploración. La tool de búsqueda se factura por
# búsqueda además de los tokens, igual que en el escaneo semanal.
EXPLORER_MAX_BUSQUEDAS = int(os.getenv("SHARKY_EXPLORER_MAX_BUSQUEDAS", "20"))

# Candidatos máximos que se aceptan de una exploración. Un radar que propone
# treinta nombres no es un radar: el límite obliga a priorizar.
EXPLORER_MAX_CANDIDATOS = int(os.getenv("SHARKY_EXPLORER_MAX_CANDIDATOS", "8"))

# --------------------------------------------------------------------------
# Vigencia de las alertas de oportunidad
# --------------------------------------------------------------------------
# Una alerta es una fotografía: mide la asimetría con la estructura de precios
# de un día concreto. Hasta 2026-09 ninguna caducaba nunca -- `AlertStatus`
# definía EXPIRADA desde el principio pero nada la asignaba -- y eso tenía dos
# efectos silenciosos: el ticker quedaba vetado para siempre en
# `has_active_alert`, y la alerta seguía entrando cada mes en el rebalanceo con
# su stop y su target congelados mientras el motor tomaba precio fresco.
# Mezclar niveles de hace dos meses con el precio de hoy no es conservador: es
# dimensionar el riesgo con la vara equivocada.
ALERTA_VIGENCIA_DIAS = int(os.getenv("SHARKY_ALERTA_VIGENCIA_DIAS", "30"))

# --------------------------------------------------------------------------
# Revisión mensual de tesis (`sharky.thesis_review`)
# --------------------------------------------------------------------------
# Hasta 2026-09 una tesis se escribía una vez y no se volvía a tocar nunca:
# el estudio mensual dictaba MANTENER/REDUCIR/CERRAR posición a posición pero
# ese veredicto moría en la nota del estudio, mientras el frontmatter de la
# tesis -- que sí mueve maquinaria viva (`stop_loss` lo lee `level_watch`,
# `conviccion` lo lee el motor de rebalanceo) -- envejecía sin que nadie lo
# revisara. Esto cierra ese lazo.
#
# Dos decisiones de diseño que NO son negociables desde estas variables:
#
#   1. La revisión **añade, nunca sobrescribe.** Lo que pensabas en agosto se
#      conserva; encima se apila lo que piensas hoy. Una tesis reescrita cada
#      mes acaba explicando lo que el precio ya hizo, y es peor que una tesis
#      obsoleta porque *parece* vigente.
#   2. La revisión **no toca un solo número.** El stop es la única salida
#      obligatoria del mandato: si pudiera renegociarse cada mes, una posición
#      que se acerca a su stop recibiría uno más bajo con una justificación
#      impecable. Los cambios de nivel o de convicción se escriben como
#      PROPUESTA y los aplicas tú, igual que ya ocurre con el take-profit.
#
# Se revisan sólo las tesis que tienen algo que decir (movimiento del mes,
# nivel alcanzado, incumplimiento abierto, noticias) para no generar prosa
# sobre posiciones donde no pasó nada -- que es donde nace la deriva
# narrativa. La red de seguridad de abajo impide que una tesis tranquila
# quede olvidada para siempre.
REVIEW_MODEL = os.getenv("SHARKY_REVIEW_MODEL", CLAUDE_MODEL)
REVIEW_MAX_TOKENS = int(os.getenv("SHARKY_REVIEW_MAX_TOKENS", "24000"))
REVIEW_EFFORT = os.getenv("SHARKY_REVIEW_EFFORT", "high").strip()

# Meses que una tesis puede pasar sin que nadie la mire, aunque no se haya
# movido. Mismo criterio que `BREACH_ESCALATION_DAYS` y que la red de
# seguridad del escaneo semanal: nada queda huérfano indefinidamente sólo
# porque no haya llamado la atención. Se cuenta desde `fecha_revision` o, si
# nunca se revisó, desde `fecha_apertura`: una tesis escrita ayer no necesita
# revisión hoy.
REVIEW_MESES_MAX = int(os.getenv("SHARKY_REVIEW_MESES_MAX", "3"))

# Variación del precio a lo largo del mes que basta para revisar una tesis.
# Es un umbral mensual, no diario: una posición que se desliza un 18% en tres
# semanas sin un solo día de -7% no la marca `UMBRAL_MOVIMIENTO_VIGILANCIA_PCT`
# y es justo la que hay que releer.
REVIEW_UMBRAL_MOVIMIENTO_PCT = float(os.getenv("SHARKY_REVIEW_UMBRAL_MOVIMIENTO_PCT", "15"))

# Tope de tesis por ejecución. Las que no entran no se pierden: quedan en la
# traza con el motivo y vuelven a seleccionarse el mes siguiente.
REVIEW_MAX_TESIS = int(os.getenv("SHARKY_REVIEW_MAX_TESIS", "12"))

# --------------------------------------------------------------------------
# Axiomas de dimensionamiento (Reglas_De_Supervivencia.md §2)
# --------------------------------------------------------------------------
MAX_POSITION_SIZE_PCT = float(os.getenv("SHARKY_MAX_POS_PCT", "10.0"))
# En estado ALERTA el mandato reduce el tope por activo al 5%.
MAX_POSITION_SIZE_ALERTA_PCT = float(os.getenv("SHARKY_MAX_POS_ALERTA_PCT", "5.0"))
MAX_SECTOR_SIZE_PCT = float(os.getenv("SHARKY_MAX_SECTOR_PCT", "25.0"))
MIN_CASH_PCT = float(os.getenv("SHARKY_MIN_CASH_PCT", "15.0"))
MAX_CASH_PCT = float(os.getenv("SHARKY_MAX_CASH_PCT", "30.0"))
MAX_RISK_PER_TRADE_PCT = float(os.getenv("SHARKY_MAX_RISK_PCT", "1.5"))
MIN_RISK_REWARD_RATIO = float(os.getenv("SHARKY_MIN_RR_RATIO", "2.0"))

# --------------------------------------------------------------------------
# Vigilancia de niveles: stop-loss y take-profit (ver `sharky.level_watch`)
# --------------------------------------------------------------------------
# El stop-loss es una salida obligatoria del mandato. El target NO lo es: al
# alcanzarlo, Sharky avisa y propone subir el stop, pero no ordena liquidar
# -- cortar toda posición ganadora en su primer objetivo es la forma más
# eficiente de quedarse fuera de las tendencias que pagan la cartera.
#
# El stop propuesto es el mayor de dos criterios deterministas:
#   * break-even: el precio de entrada de la tesis (principal protegido);
#   * trailing:   precio actual menos el riesgo inicial de la tesis
#                 (entrada - stop), manteniendo constante el riesgo abierto.
# Si la tesis no declara entrada o stop, no hay riesgo inicial que replicar y
# el trailing cae al porcentaje de abajo.
TRAILING_STOP_PCT = float(os.getenv("SHARKY_TRAILING_STOP_PCT", "8.0"))

# Fichero donde el ciclo diario deja los niveles alcanzados para que el aviso
# emergente de Windows (scripts/avisar_niveles_windows.ps1) los muestre sin
# volver a llamar al mercado. Vive en logs/, que está fuera de git: contiene
# posiciones y valores reales de la cartera.
ALERTAS_NIVELES_PATH = Path(
    os.getenv("SHARKY_ALERTAS_NIVELES_PATH", str(BASE_DIR / "logs" / "alertas_niveles.json"))
)

# --------------------------------------------------------------------------
# Umbrales de estado vital (Reglas_De_Supervivencia.md §3)
# --------------------------------------------------------------------------
# Medidos como drawdown desde el máximo histórico del NAV (high-water mark),
# NO como caída desde el capital inicial.
DRAWDOWN_OPTIMO_MAX_PCT = float(os.getenv("SHARKY_DD_OPTIMO_PCT", "3.0"))
DRAWDOWN_ALERTA_MAX_PCT = float(os.getenv("SHARKY_DD_ALERTA_PCT", "8.0"))
# Cuidados Intensivos cubre 8-20% de un tirón (ver Reglas_De_Supervivencia.md
# v2.1): no existe un cuarto umbral "Crítico" independiente. Una versión
# anterior definía SHARKY_DD_CRITICO_PCT como frontera en el 15%, pero
# `RiskGovernor.clasificar_estado` nunca la usó, dejando la franja 15-20% sin
# clasificar. Se retiró la variable en lugar de dejarla viva sin efecto.
DEATH_DRAWDOWN_PCT = float(os.getenv("SHARKY_DEATH_DRAWDOWN_PCT", "20.0"))

# Días que un incumplimiento del mandato puede seguir abierto antes de que
# `VaultManager` lo marque como ESCALADO en Estado_Vital.md (ver auditoría de
# 2026-09: el motor de riesgo detectaba bien las brechas, pero nada obligaba
# a revisitarlas si el ciclo diario simplemente las volvía a listar cada vez
# sin destacar su antigüedad).
BREACH_ESCALATION_DAYS = int(os.getenv("SHARKY_BREACH_ESCALATION_DAYS", "7"))

# --------------------------------------------------------------------------
# Memoria: cuánto diario reciente se relee antes de cada informe de IA
# --------------------------------------------------------------------------
# Hasta 2026-09, `ClaudeBrainClient` razonaba cada día en un vacío total: el
# prompt sólo llevaba los datos de HOY, nunca lo que el propio diario de
# `05_Diario_Reflexion` ya había registrado ayer o la semana pasada. La
# carpeta `06_Lecciones_Aprendidas` se crea al inicializar la bóveda pero
# nada la escribe ni la lee -- la intención de "aprender" estaba en la
# estructura de carpetas, no en el código. Esto empieza a cerrar esa
# brecha por el lado más barato: releer el propio diario como contexto.
#
# El control diario ya no relee el diario: razona sólo sobre el estado de
# hoy. El escaneo semanal de noticias recibe los controles de la última
# semana, y el estudio mensual los del mes completo más los escaneos
# semanales del mes. Cada nivel pasa al siguiente sólo su conclusión, no la
# nota entera, para que el contexto no crezca sin límite.
DIAS_CONTEXTO_SEMANAL = int(os.getenv("SHARKY_DIAS_CONTEXTO_SEMANAL", "7"))
DIAS_CONTEXTO_MENSUAL = int(os.getenv("SHARKY_DIAS_CONTEXTO_MENSUAL", "31"))

# --------------------------------------------------------------------------
# Modo de ejecución
# --------------------------------------------------------------------------
# Sharky no tiene modo simulación: NUNCA envía órdenes a un broker, sólo
# propone y registra lo que tú ya ejecutaste en Trade Republic -- toda
# operación registrada con `trade` es real. Hasta 2026-09 existía una
# variable SHARKY_EXECUTION_MODE (PAPER/REAL, por defecto PAPER) que sólo
# cambiaba una etiqueta en la nota de la operación: no había ningún camino
# en la CLI para marcar una operación como simulada, así que toda operación
# real acababa etiquetada `PAPER_TRADING` por el valor por defecto (ver la
# corrección de 2026-09-05 en las notas de 04_Operaciones_Bitacora, donde se
# quitó la etiqueta errónea). Se retiró la variable en vez de dejar viva una
# distinción que no protegía nada y sólo generaba etiquetas engañosas.

# Si es False, un fallo de la API de Claude propaga el error en lugar de
# devolver prosa simulada que podría confundirse con análisis real.
ALLOW_SIMULATED_INTELLIGENCE = os.getenv(
    "SHARKY_ALLOW_SIMULATED_INTELLIGENCE", "true"
).lower() in ("true", "1", "yes")

# Antigüedad máxima de una cotización en caché antes de considerarla obsoleta.
PRICE_CACHE_TTL_SECONDS = int(os.getenv("SHARKY_PRICE_CACHE_TTL", "900"))

# --------------------------------------------------------------------------
# Universo de vigilancia
# --------------------------------------------------------------------------
DEFAULT_WATCHLIST = ["NVDA", "ASML", "MSFT", "AAPL", "GOOGL", "TSM"]


def has_live_api_key() -> bool:
    """True si hay una API key de Anthropic real configurada."""
    return ANTHROPIC_API_KEY.strip() not in API_KEY_PLACEHOLDERS
