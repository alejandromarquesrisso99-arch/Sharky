"""
Configuración central de Sharky.
Gestiona variables de entorno, rutas a la bóveda de Obsidian y parámetros de riesgo.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Rutas del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VAULT_DIR = BASE_DIR / "vault"

# Ruta de la Bóveda de Obsidian (configurable por variable de entorno)
VAULT_PATH = Path(os.getenv("SHARKY_VAULT_PATH", DEFAULT_VAULT_DIR))

# Configuración de Inteligencia Artificial (Claude / Anthropic)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-20250219")

# Parámetros Financieros y de Supervivencia
INITIAL_CAPITAL = float(os.getenv("SHARKY_INITIAL_CAPITAL", "10000.00"))
MAX_POSITION_SIZE_PCT = float(os.getenv("SHARKY_MAX_POS_PCT", "10.0"))  # % máx por activo
MAX_RISK_PER_TRADE_PCT = float(os.getenv("SHARKY_MAX_RISK_PCT", "1.5"))  # % máx de pérdida por operación
MIN_RISK_REWARD_RATIO = float(os.getenv("SHARKY_MIN_RR_RATIO", "2.0"))  # Ratio R:R mínimo
DEATH_DRAWDOWN_PCT = float(os.getenv("SHARKY_DEATH_DRAWDOWN_PCT", "20.0"))  # % drawdown para muerte del cerebro

# Modos de ejecución
EXECUTION_MODE = os.getenv("SHARKY_EXECUTION_MODE", "PAPER")  # "PAPER" o "REAL"
MOCK_CLAUDE_IF_NO_KEY = os.getenv("SHARKY_MOCK_IF_NO_KEY", "true").lower() in ("true", "1", "yes")

# Tickers vigilados por defecto en el radar inicial
DEFAULT_WATCHLIST = ["NVDA", "ASML", "MSFT", "AAPL", "GOOGL", "TSM"]
