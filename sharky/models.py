"""
Modelos de datos y estructuras de estado para Sharky.

Invariantes de este módulo:
  * Todo importe cuyo nombre termina en `_eur` está expresado en la divisa base
    (EUR). Los precios de cotización viven en `divisa_cotizacion` y sólo se
    convierten a EUR de forma explícita a través de `sharky.fx`.
  * Toda cotización arrastra su procedencia (`PriceSource`). Un informe que
    contiene precios no fiables está obligado a declararlo.
"""

from enum import Enum
from typing import Optional, List, Dict
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


class AssetClass(str, Enum):
    ACCION = "ACCION"
    ETF = "ETF"
    ETC = "ETC"
    CRIPTO = "CRIPTO"


class PriceSource(str, Enum):
    """Procedencia de una cotización. Determina si el dato es publicable."""

    MERCADO = "MERCADO"      # cotización obtenida del proveedor en esta llamada
    CACHE = "CACHE"          # cotización reciente reutilizada (dentro del TTL)
    COSTE = "COSTE"          # sin símbolo de cotización: valorado a coste base
    SIMULADO = "SIMULADO"    # precio de referencia fijo (demo y tests)

    @property
    def es_fiable(self) -> bool:
        return self in (PriceSource.MERCADO, PriceSource.CACHE)


# --------------------------------------------------------------------------
# Cotizaciones
# --------------------------------------------------------------------------
class MarketSnapshot(BaseModel):
    ticker: str
    precio_actual: float                 # expresado en `divisa`
    divisa: str = "USD"
    cambio_diario_pct: float = 0.0
    volumen: int = 0
    pe_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    fuente: PriceSource = PriceSource.MERCADO
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def es_fiable(self) -> bool:
        return self.fuente.es_fiable


class FxRate(BaseModel):
    par: str                             # p.ej. "USD/EUR"
    tasa: float                          # 1 unidad de origen -> `tasa` de destino
    fuente: PriceSource = PriceSource.MERCADO
    timestamp: datetime = Field(default_factory=datetime.now)


# --------------------------------------------------------------------------
# Libro de posiciones (fuente de verdad de la cartera)
# --------------------------------------------------------------------------
class Position(BaseModel):
    """Una tenencia real en el custodio, con su coste base en EUR."""

    ticker: str                          # clave interna y nombre de la ficha
    nombre: str
    isin: Optional[str] = None
    # Símbolo del proveedor de datos. None => no hay cotización disponible y la
    # posición se valora a coste, señalizándolo en el informe.
    ticker_cotizacion: Optional[str] = None
    divisa_cotizacion: str = "EUR"
    clase: AssetClass = AssetClass.ACCION
    unidades: float = Field(gt=0)
    coste_unitario_eur: float = Field(gt=0)
    sector: str = ""
    nota_activo: str = ""

    @property
    def coste_total_eur(self) -> float:
        return round(self.unidades * self.coste_unitario_eur, 2)


class Portfolio(BaseModel):
    custodio: str = "Trade Republic Bank GmbH"
    divisa_base: str = "EUR"
    fecha_actualizacion: str = ""
    efectivo_eur: float = 0.0
    posiciones: List[Position] = Field(default_factory=list)

    @property
    def coste_total_eur(self) -> float:
        return round(sum(p.coste_total_eur for p in self.posiciones), 2)

    def get(self, ticker: str) -> Optional[Position]:
        clave = ticker.upper().strip()
        for p in self.posiciones:
            if p.ticker.upper() == clave:
                return p
        return None


class PositionValuation(BaseModel):
    ticker: str
    nombre: str
    # Wikilink a la ficha canónica del activo en Obsidian. Puede diferir del
    # ticker: la nota de Rheinmetall se llama `Rheinmetall`, no `RHM`.
    nota_activo: str = ""
    sector: str = ""
    unidades: float
    precio_cotizacion: float
    divisa_cotizacion: str
    tipo_cambio_a_eur: float = 1.0
    precio_unitario_eur: float
    valor_mercado_eur: float
    coste_total_eur: float
    pnl_eur: float
    pnl_pct: float
    peso_pct: float = 0.0
    fuente_precio: PriceSource = PriceSource.MERCADO


class PortfolioValuation(BaseModel):
    fecha: datetime = Field(default_factory=datetime.now)
    divisa_base: str = "EUR"
    posiciones: List[PositionValuation] = Field(default_factory=list)
    efectivo_eur: float = 0.0
    nav_eur: float = 0.0
    coste_total_eur: float = 0.0
    pnl_total_eur: float = 0.0
    pnl_total_pct: float = 0.0
    peso_efectivo_pct: float = 0.0
    exposicion_sectorial_pct: Dict[str, float] = Field(default_factory=dict)
    # Porcentaje del NAV respaldado por una cotización fiable (MERCADO/CACHE).
    cobertura_mercado_pct: float = 100.0
    posiciones_sin_cotizacion: List[str] = Field(default_factory=list)
    advertencias: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Estado vital
# --------------------------------------------------------------------------
class HealthStatus(BaseModel):
    estado_vital: VitalState = VitalState.OPTIMO
    salud_porcentaje: float = Field(default=100.0, ge=0.0, le=100.0)
    energia_actual: float = Field(default=100.0, ge=0.0, le=100.0)
    capital_inicial_eur: float = 0.0
    nav_actual_eur: float = 0.0
    # High-water mark: máximo NAV alcanzado. Base real del cálculo de drawdown.
    nav_maximo_historico_eur: float = 0.0
    pnl_total_eur: float = 0.0
    pnl_total_pct: float = 0.0
    drawdown_actual_pct: float = 0.0
    drawdown_maximo_pct: float = 0.0
    operaciones_ganadoras: int = 0
    operaciones_perdedoras: int = 0
    win_rate_pct: float = 0.0
    alertas_activas_count: int = 0
    # Fiabilidad del NAV que sustenta estas métricas.
    cobertura_datos_pct: float = 100.0
    ultima_actualizacion: datetime = Field(default_factory=datetime.now)


class RiskBreach(BaseModel):
    """Incumplimiento concreto de un axioma de Reglas_De_Supervivencia.md."""

    regla: str
    severidad: str = "ALTA"          # ALTA | MEDIA
    sujeto: str = ""                 # ticker o sector afectado
    valor_actual_pct: float = 0.0
    limite_pct: float = 0.0
    mensaje: str = ""
    accion_correctiva: str = ""


# --------------------------------------------------------------------------
# Tesis, alertas y operaciones
# --------------------------------------------------------------------------
class OpportunityAlert(BaseModel):
    id_alerta: str
    ticker: str
    empresa: str
    fecha_deteccion: str
    conviccion: int = Field(default=8, ge=1, le=10)
    precio_actual: float
    divisa: str = "USD"
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
    fuente_precio: PriceSource = PriceSource.MERCADO


class InvestmentThesis(BaseModel):
    ticker: str
    empresa: str
    tipo: str = "Largo"
    estado: str = "Activa"
    precio_entrada: float = 0.0
    divisa: str = "EUR"
    stop_loss: float = 0.0
    target_precio: float
    conviccion: int = Field(default=7, ge=1, le=10)
    ratio_rr: float = 0.0
    fecha_apertura: str = ""
    sectores: str = ""
    empresa_nota: str = ""
    racional: Optional[str] = ""
    catalizadores: List[str] = Field(default_factory=list)
    riesgos: List[str] = Field(default_factory=list)
    # Una tesis puede existir sin posición abierta (candidata en radar).
    # El NAV NUNCA se deriva de aquí: su fuente es el libro de posiciones.
    tiene_posicion: bool = False


class TradeOrder(BaseModel):
    id_operacion: str
    modo: ExecutionMode = ExecutionMode.PAPER_TRADING
    ticker: str
    tipo_orden: OrderType = OrderType.COMPRA
    cantidad_acciones: float
    precio_ejecutado: float              # en `divisa_ejecucion`
    divisa_ejecucion: str = "EUR"
    tipo_cambio_a_eur: float = 1.0
    total_invertido_eur: float
    comision_eur: float = 0.0
    stop_loss: float = 0.0
    target_precio: float = 0.0
    estado: OrderStatus = OrderStatus.ABIERTA
    fecha_ejecucion: datetime = Field(default_factory=datetime.now)
    tesis_referencia: str = ""
    justificacion: Optional[str] = ""


# --------------------------------------------------------------------------
# Rebalanceo
# --------------------------------------------------------------------------
class AllocationProposal(BaseModel):
    ticker: str
    nota_activo: str = ""
    sector: str
    accion: RebalanceAction
    peso_actual_pct: float = 0.0
    peso_objetivo_pct: float
    capital_objetivo_eur: float
    delta_eur: float = 0.0               # >0 comprar, <0 vender
    precio_estimado: float = 0.0
    divisa_precio: str = "EUR"
    acciones_estimadas: float = 0.0
    stop_loss_sugerido: float = 0.0
    target_sugerido: float = 0.0
    conviccion: int = Field(default=8, ge=1, le=10)
    motivo: str = ""
    fuente_precio: PriceSource = PriceSource.MERCADO


class MonthlyRebalanceReport(BaseModel):
    mes_ano: str
    fecha: str
    propuestas: List[AllocationProposal] = Field(default_factory=list)
    peso_cash_objetivo_pct: float = 20.0
    cash_objetivo_eur: float = 0.0
    nav_total_eur: float = 0.0
    incumplimientos: List[RiskBreach] = Field(default_factory=list)
    cobertura_datos_pct: float = 100.0
    advertencias: List[str] = Field(default_factory=list)
    regimen_macro: str = ""
    geopolitica_resumen: str = ""
    sentimiento_resumen: str = ""
