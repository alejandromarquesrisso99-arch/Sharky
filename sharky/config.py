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
BASE_CURRENCY = os.getenv("SHARKY_BASE_CURRENCY", "EUR").upper()

# --------------------------------------------------------------------------
# Inteligencia artificial (Claude / Anthropic)
# --------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# Presupuesto de tokens de cada informe que genera la IA. Si el modelo
# configurado gasta parte del presupuesto en razonamiento antes de emitir
# texto visible, una respuesta puede llegar a `stop_reason='max_tokens'` sin
# haber producido ni un bloque de texto -- ver el diagnóstico que
# `ClaudeBrainClient._invocar` añade en ese caso. Configurable para poder
# subirlo sin tocar código si eso es lo que está pasando.
MAX_TOKENS_INFORME = int(os.getenv("SHARKY_MAX_TOKENS_INFORME", "2000"))

# Placeholders que NO cuentan como una API key válida.
API_KEY_PLACEHOLDERS = {
    "",
    "tu_api_key_aqui",
    "TU_ANTHROPIC_API_KEY_AQUI",
    "sk-ant-api03-...",
}

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
# Días 2-31 usan la ventana corta (semana reciente); el día 1 -- que cierra
# el ciclo mensual y da el tono del siguiente -- usa el mes completo.
DIAS_CONTEXTO_DIARIO = int(os.getenv("SHARKY_DIAS_CONTEXTO_DIARIO", "7"))
DIAS_CONTEXTO_MENSUAL = int(os.getenv("SHARKY_DIAS_CONTEXTO_MENSUAL", "30"))

# --------------------------------------------------------------------------
# Modo de ejecución
# --------------------------------------------------------------------------
# PAPER : las operaciones registradas se marcan como simuladas.
# REAL  : las operaciones registradas reflejan ejecuciones hechas en el broker.
# En ambos casos Sharky NUNCA envía órdenes a un broker: sólo propone y registra.
EXECUTION_MODE = os.getenv("SHARKY_EXECUTION_MODE", "PAPER").upper()

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
