"""
Modelos de datos y estructuras de estado para Sharky.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class VitalState(str, Enum):
    OPTIMO = "OPTIMO"
    ALERTA = "ALERTA"
    CUIDADOS_INTENSIVOS = "CUIDADOS_INTENSIVOS"
    MUERTE = "MUERTE"


class OrderType(str, Enum):
    COMPRA = "COMPRA"
    VENTA = "VENTA"


class RebalanceAction(str, Enum):
    COMPRAR = "COMPRAR"
    VENDER = "VENDER"
    MANTENER = "MANTENER"
    REDUCIR = "REDUCIR"
    INCREMENTAR = "INCREMENTAR"


class AlertStatus(str, Enum):
    ACTIVA = "ACTIVA"
    EJECUTADA = "EJECUTADA"
    DESCARTADA = "DESCARTADA"
    EXPIRADA = "EXPIRADA"


class OrderStatus(str, Enum):
    ABIERTA = "ABIERTA"
    CERRADA = "CERRADA"
    CANCELADA = "CANCELADA"


class ExecutionMode(str, Enum):
    PAPER_TRADING = "PAPER_TRADING"
    REAL = "REAL"


class HealthStatus(BaseModel):
    estado_vital: VitalState = VitalState.OPTIMO
    salud_porcentaje: float = Field(default=100.0, ge=0.0, le=100.0)
    energia_actual: float = Field(default=100.0, ge=0.0, le=100.0)
    capital_inicial: float = 10000.0
    capital_actual: float = 10000.0
    pnl_total_usd: float = 0.0
    pnl_total_pct: float = 0.0
    drawdown_maximo_pct: float = 0.0
    operaciones_ganadoras: int = 0
    operaciones_perdedoras: int = 0
    win_rate_pct: float = 0.0
    alertas_activas_count: int = 0
    ultima_actualizacion: datetime = Field(default_factory=datetime.now)


class OpportunityAlert(BaseModel):
    id_alerta: str
    ticker: str
    empresa: str
    fecha_deteccion: str
    conviccion: int = Field(default=8, ge=1, le=10)
    precio_actual: float
    entrada_sugerida: float
    stop_loss: float
    target_precio: float
    ratio_rr: float
    potencial_ganancia_pct: float
    riesgo_maximo_pct: float
    descripcion_oportunidad: str
    catalizadores: List[str] = Field(default_factory=list)
    riesgos: List[str] = Field(default_factory=list)
    pct_max_cartera: float = 8.0
    estado: AlertStatus = AlertStatus.ACTIVA


class InvestmentThesis(BaseModel):
    ticker: str
    empresa: str
    tipo: str = "Largo"
    estado: str = "Activa"
    precio_entrada: float
    stop_loss: float
    target_precio: float
    conviccion: int = Field(default=7, ge=1, le=10)
    capital_asignado: float
    ratio_rr: float
    fecha_apertura: str
    sectores: str
    empresa_nota: str
    racional: Optional[str] = ""
    catalizadores: List[str] = Field(default_factory=list)
    riesgos: List[str] = Field(default_factory=list)


class TradeOrder(BaseModel):
    id_operacion: str
    modo: ExecutionMode = ExecutionMode.PAPER_TRADING
    ticker: str
    tipo_orden: OrderType = OrderType.COMPRA
    cantidad_acciones: float
    precio_ejecutado: float
    total_invertido_usd: float
    stop_loss: float
    target_precio: float
    estado: OrderStatus = OrderStatus.ABIERTA
    fecha_ejecucion: datetime = Field(default_factory=datetime.now)
    tesis_referencia: str
    justificacion: Optional[str] = ""


class MarketSnapshot(BaseModel):
    ticker: str
    precio_actual: float
    cambio_diario_pct: float
    volumen: int = 0
    pe_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class AllocationProposal(BaseModel):
    ticker: str
    sector: str
    accion: RebalanceAction
    peso_actual_pct: float = 0.0
    peso_objetivo_pct: float
    capital_asignado_usd: float
    precio_estimado: float
    acciones_estimadas: float
    stop_loss_sugerido: float
    target_sugerido: float
    conviccion: int = Field(default=8, ge=1, le=10)
    motivo: str


class MonthlyRebalanceReport(BaseModel):
    mes_ano: str
    fecha: str
    propuestas: List[AllocationProposal]
    peso_cash_pct: float = 20.0
    cash_usd: float = 2000.0
    capital_total_usd: float = 10000.0
    regimen_macro: str = "Expansión Tardía / Tipos Neutral-Restrictivos"
    geopolitica_resumen: str = "Tensión en semiconductores y rutas marítimas"
    sentimiento_resumen: str = "Codicia moderada con amplitud concentrada en Big Tech"
