"""
Suite del núcleo de Sharky Capital Management.

Cubre los invariantes que la versión anterior violaba:
  * el PnL nunca mezcla divisas;
  * el drawdown se mide contra el máximo histórico;
  * los umbrales de estado vital son los del mandato escrito en la bóveda;
  * las ventas no se bloquean cuando la cartera está herida;
  * ninguna cifra procede de datos simulados sin declararlo.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from sharky.agent_loop import SharkyAgent
from sharky.claude_client import (
    CONCLUSION_DIA,
    CONCLUSION_MES,
    CONCLUSION_SEMANA,
    ClaudeBrainClient,
    IntelligenceResult,
    extraer_conclusion,
)
from sharky.config import (
    BREACH_ESCALATION_DAYS,
    EFFORT_DIARIO,
    EFFORT_MENSUAL,
    MAX_TOKENS_DIARIO,
    MAX_TOKENS_MENSUAL,
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
    NEWS_EFFORT,
    NEWS_SCAN_WEEKDAY,
    UMBRAL_MOVIMIENTO_VIGILANCIA_PCT,
)
from sharky.firm_committee import InvestmentCommittee
from sharky.fx import FxProvider
from sharky.level_watch import cargar, guardar, resumen, revisar_niveles, texto
from sharky.market_data import MarketDataProvider
from sharky.models import (
    AllocationProposal,
    AssetClass,
    HealthStatus,
    InvestmentThesis,
    LevelAlert,
    LevelKind,
    MonthlyRebalanceReport,
    OpportunityAlert,
    OrderType,
    Portfolio,
    PortfolioValuation,
    Position,
    PositionValuation,
    PriceSource,
    RebalanceAction,
    TradeOrder,
    VitalState,
)
from sharky.news_scanner import NewsScanner, NewsScanResult
from sharky.opportunity_detector import OpportunityDetector
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.rebalance_engine import UMBRAL_ACCION_PCT, MonthlyRebalanceEngine
from sharky.risk_governor import RiskGovernor
from sharky.trade_ledger import TradeRecorder
from sharky.vault_manager import VaultManager, _clave_incumplimiento

from conftest import FakeFx, FakeMarket


# ======================================================================
# Divisas
# ======================================================================
class TestDivisas:
    def test_pence_no_se_confunde_con_libras(self):
        """GBp son céntimos de GBP: confundirlos es un error de factor 100."""
        fx = FxProvider()
        fx._cache.clear()
        fx.has_yfinance = False  # fuerza el uso de las tasas de emergencia

        gbp = fx.get_rate("GBP")
        gbp_pence = fx.get_rate("GBp")

        assert gbp_pence.tasa == pytest.approx(gbp.tasa / 100.0)
        assert gbp_pence.fuente == PriceSource.SIMULADO

    def test_divisa_desconocida_falla_en_vez_de_inventar(self):
        fx = FxProvider()
        fx.has_yfinance = False
        with pytest.raises(ValueError):
            fx.get_rate("XYZ")

    def test_divisa_base_es_identidad(self):
        assert FxProvider().get_rate("EUR").tasa == 1.0

    def test_base_currency_es_fija_en_eur(self):
        """FX-3: SHARKY_BASE_CURRENCY se retiró -- no queda variable de
        entorno que pueda cambiar la divisa base."""
        from sharky import config

        assert config.BASE_CURRENCY == "EUR"


# ======================================================================
# Valoración de cartera
# ======================================================================
class TestValoracion:
    def test_pnl_no_mezcla_divisas(self, cartera_simple, valuator_simple):
        """Una posición en USD debe convertirse antes de compararse con su coste.

        BBB cotiza a 100 USD con USD/EUR = 0,90, así que vale 90 EUR por título.
        Frente a un coste de 80 EUR el PnL es +12,5%, no el +25% que saldría de
        restar 100 (USD) menos 80 (EUR).
        """
        v = valuator_simple.value(cartera_simple)
        bbb = next(p for p in v.posiciones if p.ticker == "BBB")

        assert bbb.precio_unitario_eur == pytest.approx(90.0)
        assert bbb.valor_mercado_eur == pytest.approx(900.0)
        assert bbb.pnl_eur == pytest.approx(100.0)
        assert bbb.pnl_pct == pytest.approx(12.5)

    def test_nav_incluye_efectivo_y_cuadra(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        # AAA 10x100 EUR = 1000 | BBB 10x90 EUR = 900 | CCC a coste 500 | caja 1000
        assert v.nav_eur == pytest.approx(3400.0)
        assert v.efectivo_eur == pytest.approx(1000.0)
        assert sum(p.peso_pct for p in v.posiciones) + v.peso_efectivo_pct == pytest.approx(100.0, abs=0.05)

    def test_posicion_sin_simbolo_se_valora_a_coste_y_se_declara(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        ccc = next(p for p in v.posiciones if p.ticker == "CCC")

        assert ccc.fuente_precio == PriceSource.COSTE
        assert ccc.valor_mercado_eur == pytest.approx(ccc.coste_total_eur)
        assert "CCC" in v.posiciones_sin_cotizacion
        assert v.cobertura_mercado_pct < 100.0
        assert any("CCC" in a for a in v.advertencias)

    def test_cobertura_es_100_cuando_todo_cotiza(self, valuator_simple):
        cartera = Portfolio(
            efectivo_eur=100.0,
            posiciones=[
                Position(
                    ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA",
                    divisa_cotizacion="EUR", unidades=1.0, coste_unitario_eur=100.0,
                )
            ],
        )
        v = valuator_simple.value(cartera)
        assert v.cobertura_mercado_pct == pytest.approx(100.0)
        assert v.posiciones_sin_cotizacion == []

    def test_tipo_de_cambio_simulado_degrada_la_fiabilidad(self, cartera_simple, market_simple):
        """Si el FX no es fiable, la valoración tampoco lo es."""
        valuator = PortfolioValuator(
            market=market_simple, fx=FakeFx(fuente=PriceSource.SIMULADO)
        )
        v = valuator.value(cartera_simple)
        bbb = next(p for p in v.posiciones if p.ticker == "BBB")
        assert bbb.fuente_precio == PriceSource.SIMULADO
        assert v.cobertura_mercado_pct < 100.0

    def test_exposicion_sectorial_agrega(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        # BBB (900) y CCC (500) son Defensa sobre un NAV de 3400.
        assert v.exposicion_sectorial_pct["Defensa"] == pytest.approx(41.18, abs=0.05)

    def test_sin_cotizacion_real_se_valora_a_coste_no_simulado(self, cartera_simple):
        """DATOS-1: en producción, sin cotización de mercado disponible, la
        posición se valora a coste (COSTE) en vez de con un precio de
        referencia inventado (SIMULADO), que contaminaría el NAV real."""
        market = MarketDataProvider(allow_reference_prices=False)
        market.has_yfinance = False  # simula el proveedor caído, sin red
        valuator = PortfolioValuator(market=market, fx=FakeFx())

        v = valuator.value(cartera_simple)

        aaa = next(p for p in v.posiciones if p.ticker == "AAA")
        assert aaa.fuente_precio == PriceSource.COSTE
        assert v.cobertura_mercado_pct < 100.0


# ======================================================================
# Libro de posiciones
# ======================================================================
class TestLibroPosiciones:
    def test_ida_y_vuelta_conserva_los_datos(self, store_tmp, cartera_simple):
        recargada = store_tmp.load()
        assert len(recargada.posiciones) == len(cartera_simple.posiciones)
        assert recargada.efectivo_eur == pytest.approx(cartera_simple.efectivo_eur)
        original = {p.ticker: p for p in cartera_simple.posiciones}
        for pos in recargada.posiciones:
            assert pos.unidades == pytest.approx(original[pos.ticker].unidades)
            assert pos.coste_unitario_eur == pytest.approx(original[pos.ticker].coste_unitario_eur)
            assert pos.divisa_cotizacion == original[pos.ticker].divisa_cotizacion

    def test_conserva_la_capitalizacion_del_ticker(self, tmp_path):
        """Forzar mayúsculas rompería el enlace `[[Physical_Gold]]`."""
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(posiciones=[
            Position(ticker="Physical_Gold", nombre="Oro", unidades=1.0, coste_unitario_eur=70.0)
        ]))
        assert store.load().posiciones[0].ticker == "Physical_Gold"

    def test_tabla_escapa_el_pipe_del_alias_en_cada_fila(self, tmp_path):
        """El `|` del alias de Obsidian es el separador de columnas de Markdown.
        Sin escapar, la fila de Rheinmetall tiene 10 celdas en vez de 9 y todo
        lo que va detrás del enlace se lee una columna corrida."""
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(posiciones=[
            Position(ticker="RHM", nombre="Rheinmetall AG", ticker_cotizacion="RHM.DE",
                     divisa_cotizacion="EUR", unidades=2.0, coste_unitario_eur=100.0,
                     sector="Defensa", nota_activo="[[Rheinmetall]]"),
            Position(ticker="NIO", nombre="NIO Inc.", ticker_cotizacion="9866.HK",
                     divisa_cotizacion="HKD", unidades=10.0, coste_unitario_eur=5.0,
                     sector="Automocion_Electrica", nota_activo="[[NIO]]"),
        ]))
        filas = [
            linea for linea in store.ledger_path.read_text(encoding="utf-8").splitlines()
            if linea.startswith("| [[")
        ]
        assert len(filas) == 2
        for fila in filas:
            # 9 columnas => 10 separadores `|` sin escapar (inicial y final incluidos).
            assert fila.replace("\\|", "").count("|") == 10, fila
        assert "[[Rheinmetall\\|RHM]]" in filas[0]
        assert "[[NIO]]" in filas[1]  # sin alias, nada que escapar

    def test_libro_ausente_falla_con_mensaje_util(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="libro de posiciones"):
            PortfolioStore(tmp_path / "vacio").load()

    def test_busqueda_por_ticker_ignora_mayusculas(self, cartera_simple):
        assert cartera_simple.get("aaa") is not None
        assert cartera_simple.get("ZZZ") is None


# ======================================================================
# Estado vital y drawdown
# ======================================================================
class TestEstadoVital:
    def setup_method(self):
        self.g = RiskGovernor()

    @pytest.mark.parametrize(
        "drawdown, esperado",
        [
            (0.0, VitalState.OPTIMO),
            (2.9, VitalState.OPTIMO),
            (3.0, VitalState.ALERTA),
            (7.9, VitalState.ALERTA),
            (8.0, VitalState.CUIDADOS_INTENSIVOS),
            (15.0, VitalState.CUIDADOS_INTENSIVOS),
            (19.9, VitalState.CUIDADOS_INTENSIVOS),
            (20.0, VitalState.MUERTE),
            (20.1, VitalState.MUERTE),
        ],
    )
    def test_umbrales_coinciden_con_el_mandato(self, drawdown, esperado):
        """Los cortes son los de Reglas_De_Supervivencia.md §3, no otros."""
        assert self.g.clasificar_estado(drawdown) == esperado

    def test_drawdown_se_mide_contra_el_maximo_historico(self, cartera_simple, valuator_simple):
        """Una caída tras un máximo es drawdown, aunque siga habiendo beneficio.

        Es el error que hacía que el agente se declarara sano al 100% después de
        devolver una tercera parte de las ganancias.
        """
        v = valuator_simple.value(cartera_simple)   # NAV = 3400
        previa = HealthStatus(
            capital_inicial_eur=3000.0,
            nav_maximo_historico_eur=4000.0,
        )
        h = self.g.calculate_health(previa, v)

        assert h.nav_maximo_historico_eur == pytest.approx(4000.0)
        assert h.drawdown_actual_pct == pytest.approx(15.0)
        assert h.estado_vital == VitalState.CUIDADOS_INTENSIVOS
        # Y todo ello mientras el PnL sobre el capital inicial sigue en positivo.
        assert h.pnl_total_eur > 0

    def test_el_maximo_historico_sube_pero_no_baja(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)   # NAV = 3400
        h = self.g.calculate_health(
            HealthStatus(capital_inicial_eur=1000.0, nav_maximo_historico_eur=1000.0), v
        )
        assert h.nav_maximo_historico_eur == pytest.approx(3400.0)
        assert h.drawdown_actual_pct == 0.0

    def test_muerte_a_partir_del_umbral(self, valuator_simple):
        cartera = Portfolio(efectivo_eur=790.0)
        v = valuator_simple.value(cartera)
        h = self.g.calculate_health(
            HealthStatus(capital_inicial_eur=1000.0, nav_maximo_historico_eur=1000.0), v
        )
        assert h.drawdown_actual_pct == pytest.approx(21.0)
        assert h.estado_vital == VitalState.MUERTE
        assert h.salud_porcentaje == 0.0

    def test_energia_depende_de_los_dias_no_de_las_invocaciones(self, cartera_simple, valuator_simple):
        """Ejecutar la CLI diez veces en una hora no debe agotar al agente."""
        v = valuator_simple.value(cartera_simple)
        previa = HealthStatus(
            capital_inicial_eur=3400.0, nav_maximo_historico_eur=3400.0, energia_actual=50.0
        )
        sin_dias = self.g.calculate_health(previa, v, dias_transcurridos=0.0)
        un_dia = self.g.calculate_health(previa, v, dias_transcurridos=1.0)

        assert sin_dias.energia_actual == pytest.approx(50.0)
        assert un_dia.energia_actual == pytest.approx(48.0)

    def test_energia_congelada_cuando_se_pide(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        previa = HealthStatus(capital_inicial_eur=1.0, energia_actual=42.0)
        h = self.g.calculate_health(previa, v, dias_transcurridos=5.0, actualizar_energia=False)
        assert h.energia_actual == pytest.approx(42.0)

    def test_energia_usa_la_variacion_del_ciclo_no_el_pnl_acumulado(
        self, cartera_simple, valuator_simple
    ):
        """RISK-1: un PnL acumulado alto desde el inicio no debe reponer
        energía si el NAV no se ha movido desde el ciclo anterior."""
        v = valuator_simple.value(cartera_simple)  # NAV = 3400
        previa = HealthStatus(
            capital_inicial_eur=1000.0,       # +240% acumulado desde el inicio
            nav_maximo_historico_eur=3400.0,
            nav_actual_eur=3400.0,             # el ciclo anterior ya cerró aquí: plano
            energia_actual=50.0,
        )
        h = self.g.calculate_health(previa, v, dias_transcurridos=1.0)
        # Sólo desgaste (2/día), sin reposición fantasma por el PnL acumulado.
        assert h.energia_actual == pytest.approx(48.0)

    def test_cobertura_de_datos_se_propaga(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        h = self.g.calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        assert h.cobertura_datos_pct == pytest.approx(v.cobertura_mercado_pct)


# ======================================================================
# Auditoría del mandato
# ======================================================================
class TestAuditoriaMandato:
    def setup_method(self):
        self.g = RiskGovernor()

    def test_detecta_las_tres_infracciones(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        h = self.g.calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        reglas = {b.regla for b in self.g.audit_portfolio(v, h)}

        assert "Máximo por activo individual" in reglas   # AAA 29%, BBB 26%
        assert "Máximo por sector industrial" in reglas   # Defensa 41%
        assert "Integridad de los datos de valoración" in reglas  # CCC a coste

    def test_cartera_conforme_no_genera_incumplimientos(self, market_simple):
        """Cartera diversificada, líquida y totalmente cotizada."""
        posiciones = [
            Position(
                ticker=f"T{i}", nombre=f"Activo {i}", ticker_cotizacion="AAA",
                divisa_cotizacion="EUR", unidades=1.0, coste_unitario_eur=100.0,
                sector=f"Sector{i}",
            )
            for i in range(9)
        ]
        cartera = Portfolio(efectivo_eur=200.0, posiciones=posiciones)
        v = PortfolioValuator(market=market_simple, fx=FakeFx()).value(cartera)
        h = self.g.calculate_health(HealthStatus(capital_inicial_eur=v.nav_eur), v)

        assert v.peso_efectivo_pct >= MIN_CASH_PCT
        assert all(p.peso_pct <= MAX_POSITION_SIZE_PCT for p in v.posiciones)
        assert self.g.audit_portfolio(v, h) == []

    def test_caja_excesiva_es_incumplimiento_leve(self, market_simple):
        cartera = Portfolio(efectivo_eur=900.0, posiciones=[
            Position(ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=1.0, coste_unitario_eur=100.0)
        ])
        v = PortfolioValuator(market=market_simple, fx=FakeFx()).value(cartera)
        h = self.g.calculate_health(HealthStatus(capital_inicial_eur=1000.0), v)
        caja = [b for b in self.g.audit_portfolio(v, h) if b.sujeto == "Efectivo"]
        assert caja and caja[0].severidad == "MEDIA"

    def test_tope_por_activo_baja_al_5_en_alerta(self):
        assert self.g.max_position_pct(VitalState.OPTIMO) == MAX_POSITION_SIZE_PCT
        assert self.g.max_position_pct(VitalState.ALERTA) == 5.0
        assert self.g.max_position_pct(VitalState.CUIDADOS_INTENSIVOS) == 0.0


# ======================================================================
# Validación de órdenes
# ======================================================================
class TestValidacionOrdenes:
    def setup_method(self):
        self.g = RiskGovernor()
        self.health = HealthStatus(
            estado_vital=VitalState.OPTIMO,
            capital_inicial_eur=10000.0,
            nav_actual_eur=10000.0,
            nav_maximo_historico_eur=10000.0,
        )

    def _orden(self, **kwargs):
        base = dict(
            id_operacion="T-1", ticker="AAA", tipo_orden=OrderType.COMPRA,
            cantidad_acciones=5.0, precio_ejecutado=100.0, divisa_ejecucion="EUR",
            total_invertido_eur=500.0, stop_loss=95.0, target_precio=115.0,
        )
        base.update(kwargs)
        return TradeOrder(**base)

    def test_compra_conforme_se_aprueba(self):
        ok, motivo = self.g.validate_order(self._orden(), self.health)
        assert ok and "APROBADA" in motivo

    def test_compra_sin_stop_se_rechaza(self):
        ok, motivo = self.g.validate_order(self._orden(stop_loss=0.0), self.health)
        assert not ok and "stop_loss" in motivo.lower()

    def test_stop_por_encima_de_la_entrada_se_rechaza(self):
        ok, motivo = self.g.validate_order(self._orden(stop_loss=105.0), self.health)
        assert not ok and "por debajo" in motivo

    def test_ratio_insuficiente_se_rechaza(self):
        ok, motivo = self.g.validate_order(
            self._orden(stop_loss=90.0, target_precio=105.0), self.health
        )
        assert not ok and "R:R" in motivo

    def test_target_por_debajo_de_la_entrada_se_rechaza(self):
        ok, motivo = self.g.validate_order(self._orden(target_precio=90.0), self.health)
        assert not ok and "target" in motivo.lower()

    def test_posicion_excesiva_se_rechaza(self):
        ok, motivo = self.g.validate_order(
            self._orden(cantidad_acciones=20.0, total_invertido_eur=2000.0), self.health
        )
        assert not ok and "del NAV" in motivo

    def test_riesgo_por_operacion_acotado(self):
        """Riesgo hasta el stop: 40 EUR/título x 20 = 800 EUR = 8% del NAV."""
        ok, motivo = self.g.validate_order(
            self._orden(
                cantidad_acciones=20.0, precio_ejecutado=50.0, stop_loss=10.0,
                target_precio=200.0, total_invertido_eur=1000.0,
            ),
            self.health,
        )
        assert not ok and "Riesgo" in motivo or "riesgo" in motivo

    def test_venta_permitida_en_cuidados_intensivos(self):
        """El mandato exige poder ejecutar el stop-loss justo cuando duele.

        La versión anterior bloqueaba toda orden en estado crítico, incluidas
        las ventas, impidiendo la salida de emergencia.
        """
        herida = self.health.model_copy(update={"estado_vital": VitalState.CUIDADOS_INTENSIVOS})
        ok, motivo = self.g.validate_order(
            self._orden(tipo_orden=OrderType.VENTA, stop_loss=0.0, target_precio=0.0), herida
        )
        assert ok and "desinversión" in motivo

    def test_venta_permitida_incluso_en_muerte(self):
        muerto = self.health.model_copy(update={"estado_vital": VitalState.MUERTE})
        ok, _ = self.g.validate_order(
            self._orden(tipo_orden=OrderType.VENTA, stop_loss=0.0, target_precio=0.0), muerto
        )
        assert ok

    def test_compra_bloqueada_en_cuidados_intensivos(self):
        herida = self.health.model_copy(update={"estado_vital": VitalState.CUIDADOS_INTENSIVOS})
        ok, motivo = self.g.validate_order(self._orden(), herida)
        assert not ok and "CUIDADOS INTENSIVOS" in motivo

    def test_tope_sectorial_se_aplica_a_la_compra(self, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        health = self.health.model_copy(update={"nav_actual_eur": v.nav_eur})
        # Defensa ya pesa el 41%: cualquier compra adicional en ese sector sobra.
        ok, motivo = self.g.validate_order(
            self._orden(ticker="NUEVO", total_invertido_eur=100.0, cantidad_acciones=1.0,
                        precio_ejecutado=100.0, stop_loss=95.0, target_precio=115.0),
            health, valuation=v, sector="Defensa",
        )
        assert not ok and "sector" in motivo.lower()

    def test_suelo_de_liquidez_se_aplica_a_la_compra(self, market_simple):
        """Una compra dentro del tope por activo puede seguir rompiendo la caja."""
        cartera = Portfolio(efectivo_eur=2000.0, posiciones=[
            Position(ticker=f"T{i}", nombre=f"A{i}", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=8.0, coste_unitario_eur=100.0,
                     sector=f"S{i}")
            for i in range(10)
        ])
        v = PortfolioValuator(market=market_simple, fx=FakeFx()).value(cartera)
        health = self.health.model_copy(update={"nav_actual_eur": v.nav_eur})

        # NAV 10.000 con 2.000 de caja (20%). Invertir 900 son sólo el 9% del NAV
        # (dentro del tope del 10%), pero dejaría la caja al 11%: por debajo del 15%.
        ok, motivo = self.g.validate_order(
            self._orden(ticker="NUEVO", total_invertido_eur=900.0, cantidad_acciones=9.0,
                        precio_ejecutado=100.0, stop_loss=99.0, target_precio=103.0),
            health, valuation=v, sector="Nuevo",
        )
        assert v.peso_efectivo_pct == pytest.approx(20.0)
        assert not ok and "liquidez" in motivo.lower()

    def test_exposicion_previa_cuenta_para_el_tope(self, cartera_simple, valuator_simple):
        """Ampliar una posición ya grande debe rechazarse, no evaluarse en vacío."""
        v = valuator_simple.value(cartera_simple)
        health = self.health.model_copy(update={"nav_actual_eur": v.nav_eur})
        ok, motivo = self.g.validate_order(
            self._orden(ticker="AAA", total_invertido_eur=10.0, cantidad_acciones=0.1,
                        precio_ejecutado=100.0, stop_loss=95.0, target_precio=115.0),
            health, valuation=v,
        )
        assert not ok and "AAA" in motivo


# ======================================================================
# Registro de operaciones
# ======================================================================
class TestRegistroOperaciones:
    def _recorder(self, tmp_path, store, market):
        vault = VaultManager(tmp_path)
        valuator = PortfolioValuator(market=market, fx=FakeFx())
        return TradeRecorder(
            store=store, valuator=valuator, governor=RiskGovernor(),
            vault=vault, fx=FakeFx(), market=market,
        )

    def test_operacion_rechazada_no_toca_el_libro(self, tmp_path, store_tmp, market_simple):
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        antes = store_tmp.load()

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.COMPRA, unidades=100.0, precio=100.0,
            stop_loss=95.0, target_precio=115.0,
        )

        assert not res.aprobada
        despues = store_tmp.load()
        assert despues.efectivo_eur == pytest.approx(antes.efectivo_eur)
        assert despues.get("AAA").unidades == pytest.approx(antes.get("AAA").unidades)

    def test_forzar_registra_pese_a_incumplir_mandato(self, tmp_path, store_tmp, market_simple):
        """Con forzar=True, una orden que el RiskGovernor rechazaría se registra
        igualmente, con la operación marcada como incumplimiento del mandato."""
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        antes = store_tmp.load()

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.COMPRA, unidades=100.0, precio=100.0,
            stop_loss=95.0, target_precio=115.0, forzar=True,
        )

        assert res.aprobada
        assert res.motivo.startswith("⚠️")
        despues = store_tmp.load()
        assert despues.get("AAA").unidades == pytest.approx(antes.get("AAA").unidades + 100.0)

    def test_venta_reduce_posicion_y_repone_caja(self, tmp_path, store_tmp, market_simple):
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        antes = store_tmp.load()

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=4.0, precio=100.0,
        )

        assert res.aprobada
        despues = store_tmp.load()
        assert despues.get("AAA").unidades == pytest.approx(6.0)
        # 4 títulos a 100 EUR entran en caja.
        assert despues.efectivo_eur == pytest.approx(antes.efectivo_eur + 400.0)
        # Coste 90/título: se realizan 10 EUR por título vendido.
        assert res.pnl_realizado_eur == pytest.approx(40.0)

    def test_venta_total_cierra_la_posicion(self, tmp_path, store_tmp, market_simple):
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=10.0, precio=100.0,
        )
        assert res.aprobada
        assert store_tmp.load().get("AAA") is None

    def test_no_se_puede_vender_mas_de_lo_que_se_tiene(self, tmp_path, store_tmp, market_simple):
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=999.0, precio=100.0,
        )
        assert not res.aprobada and "sólo posees" in res.motivo

    def test_no_se_puede_vender_lo_que_no_se_posee(self, tmp_path, store_tmp, market_simple):
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        res = recorder.record(
            ticker="ZZZ", tipo_orden=OrderType.VENTA, unidades=1.0, precio=10.0,
        )
        assert not res.aprobada and "no hay posición" in res.motivo

    def test_compra_promedia_el_coste_unitario(self, tmp_path, market_simple):
        """Coste medio ponderado: 1 título a 90 más 1 a 110 dan 100 de media."""
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(efectivo_eur=5000.0, posiciones=[
            Position(ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=1.0, coste_unitario_eur=90.0,
                     sector="Tecnologia"),
        ]))
        recorder = self._recorder(tmp_path, store, market_simple)

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=110.0,
            stop_loss=100.0, target_precio=140.0,
        )

        assert res.aprobada, res.motivo
        pos = store.load().get("AAA")
        assert pos.unidades == pytest.approx(2.0)
        assert pos.coste_unitario_eur == pytest.approx(100.0)

    def test_comision_se_capitaliza_en_el_coste(self, tmp_path, market_simple):
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(efectivo_eur=5000.0, posiciones=[]))
        recorder = self._recorder(tmp_path, store, market_simple)

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.COMPRA, unidades=10.0, precio=10.0,
            comision_eur=5.0, stop_loss=9.0, target_precio=13.0,
            nombre="Alfa", sector="Tecnologia", ticker_cotizacion="AAA",
        )

        assert res.aprobada, res.motivo
        pos = store.load().get("AAA")
        # 100 EUR de principal más 5 de comisión repartidos entre 10 títulos.
        assert pos.coste_unitario_eur == pytest.approx(10.5)
        assert store.load().efectivo_eur == pytest.approx(4895.0)

    def test_conversion_de_divisa_en_el_asiento(self, tmp_path):
        """Una compra en USD debe descontar euros, no dólares, de la caja."""
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(efectivo_eur=5000.0, posiciones=[]))
        market = FakeMarket({"USTOCK": (100.0, "USD")})
        recorder = self._recorder(tmp_path, store, market)

        res = recorder.record(
            ticker="USTOCK", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=100.0,
            divisa="USD", stop_loss=90.0, target_precio=130.0,
            nombre="US Stock", sector="Tecnologia", ticker_cotizacion="USTOCK",
        )

        assert res.aprobada, res.motivo
        # 100 USD x 0,90 = 90 EUR.
        assert res.orden.total_invertido_eur == pytest.approx(90.0)
        assert store.load().efectivo_eur == pytest.approx(4910.0)

    def test_no_existe_modo_simulacion(self, tmp_path, store_tmp, market_simple):
        """Sharky no distingue papel/real: toda operación registrada es una
        compra o venta real que ya se ejecutó en el broker, y se asienta en
        el libro de posiciones sin ninguna vía para marcarla como simulada.
        """
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=1.0, precio=100.0,
        )
        assert res.aprobada, res.motivo
        assert not hasattr(res.orden, "modo")
        assert "PAPER_TRADING" not in res.nota_operacion

    def test_ticker_desconocido_sin_divisa_se_rechaza(self, tmp_path, market_simple):
        """FX-1: sin posición previa ni registro del ticker, no se asume USD:
        se exige --divisa explícita en vez de arriesgar el coste base."""
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(efectivo_eur=5000.0, posiciones=[]))
        recorder = self._recorder(tmp_path, store, market_simple)

        res = recorder.record(
            ticker="ZZZ", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=50.0,
            stop_loss=45.0, target_precio=65.0,
        )

        assert not res.aprobada
        assert "--divisa" in res.motivo
        assert store.load().get("ZZZ") is None

    def test_stop_y_target_se_convierten_si_vienen_en_otra_divisa(self, tmp_path):
        """FX-2: un stop/target dado en otra divisa que la de ejecución se
        convierte antes de compararlo, en vez de compararse en crudo."""
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(efectivo_eur=50000.0, posiciones=[]))
        market = FakeMarket({"MSFT": (442.0, "USD")})
        recorder = self._recorder(tmp_path, store, market)

        res = recorder.record(
            ticker="MSFT", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=442.0,
            divisa="USD", stop_loss=360.0, target_precio=540.0,
            divisa_niveles="EUR", nombre="Microsoft", sector="Tecnologia",
            ticker_cotizacion="MSFT",
        )

        assert res.aprobada, res.motivo
        # 360/540 EUR llevados a USD con la tasa fija de FakeFx (EUR=1.0,
        # USD=0.90): comparar los números crudos (360/540) contra un precio en
        # USD habría sido el error de unidades que describe FX-2.
        assert res.orden.stop_loss == pytest.approx(400.0)
        assert res.orden.target_precio == pytest.approx(600.0)

    def test_registrar_una_operacion_preserva_los_niveles_del_dia(
        self, tmp_path, store_tmp, market_simple, monkeypatch
    ):
        """CICLO-1: registrar una venta no debe borrar del cuadro de mandos un
        stop que el ciclo diario ya detectó hoy."""
        ruta_niveles = tmp_path / "logs" / "alertas_niveles.json"
        monkeypatch.setattr("sharky.level_watch.ALERTAS_NIVELES_PATH", ruta_niveles)

        niveles = _revisar(
            [_tesis(ticker="AAA", divisa="EUR", stop=95.0, target=300.0)],
            _valoracion(_pos(ticker="AAA", precio_eur=90.0, divisa_cot="EUR")),
        )
        guardar(niveles, ruta_niveles)

        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        res = recorder.record(ticker="AAA", tipo_orden=OrderType.VENTA, unidades=1.0, precio=100.0)
        assert res.aprobada, res.motivo

        texto_nota = VaultManager(tmp_path).health_path.read_text(encoding="utf-8")
        assert "## 🎯 Niveles Alcanzados" in texto_nota
        assert "stops_alcanzados: 1" in texto_nota

    def test_fallo_al_actualizar_estado_vital_no_deshace_el_asiento(
        self, tmp_path, store_tmp, market_simple
    ):
        """INFRA-3: el asiento contable ya es real (ya ocurrió en el broker);
        un fallo al escribir Estado_Vital.md después debe avisar en el
        resultado, no deshacer la operación ni fallar en silencio."""

        class _VaultQueFalla(VaultManager):
            def update_health_status(self, *args, **kwargs):
                raise OSError("disco lleno (simulado)")

        vault = _VaultQueFalla(tmp_path)
        valuator = PortfolioValuator(market=market_simple, fx=FakeFx())
        recorder = TradeRecorder(
            store=store_tmp, valuator=valuator, governor=RiskGovernor(),
            vault=vault, fx=FakeFx(), market=market_simple,
        )

        res = recorder.record(ticker="AAA", tipo_orden=OrderType.VENTA, unidades=1.0, precio=100.0)

        assert res.aprobada is True
        assert "no se pudo" in res.motivo
        assert store_tmp.load().get("AAA").unidades == pytest.approx(9.0)


# ======================================================================
# Detector de oportunidades
# ======================================================================
class TestDetector:
    TECNICOS_BUENOS = {
        # 25% por debajo del máximo, tendencia intacta, volatilidad baja:
        # stop del 6% frente a un recorrido del 33% da R:R > 5.
        "ASML": {
            "precio": 750.0, "max_52s": 1000.0, "min_52s": 700.0, "sma_200": 740.0,
            "vol_diaria": 0.008, "caida_desde_max_pct": 25.0, "sobre_sma200_pct": 1.35,
        }
    }

    def test_emite_alerta_con_asimetria_confirmada(self):
        market = FakeMarket({"ASML": (750.0, "USD")}, tecnicos=self.TECNICOS_BUENOS)
        detector = OpportunityDetector(market=market)
        alertas = detector.scan_for_opportunities(market.get_batch_snapshots(["ASML"]))

        assert len(alertas) == 1
        a = alertas[0]
        assert a.ticker == "ASML"
        assert a.ratio_rr >= 2.8
        assert a.stop_loss < a.precio_actual < a.target_precio
        assert a.target_precio == pytest.approx(1000.0)
        assert a.divisa == "USD"

    def test_no_reemite_una_alerta_ya_viva(self):
        """El duplicado de alertas llenó la bóveda de ASML repetidos."""
        market = FakeMarket({"ASML": (750.0, "USD")}, tecnicos=self.TECNICOS_BUENOS)
        detector = OpportunityDetector(market=market)
        alertas = detector.scan_for_opportunities(
            market.get_batch_snapshots(["ASML"]), ya_alertado=lambda t: t == "ASML"
        )
        assert alertas == []
        assert any(d["veredicto"] == "OMITIDO" for d in detector.ultimo_diagnostico)

    def test_omite_lo_que_ya_esta_en_cartera(self):
        market = FakeMarket({"ASML": (750.0, "USD")}, tecnicos=self.TECNICOS_BUENOS)
        detector = OpportunityDetector(market=market)
        assert detector.scan_for_opportunities(
            market.get_batch_snapshots(["ASML"]), existing_positions=["ASML"]
        ) == []

    def test_no_emite_con_precio_no_fiable(self):
        """Un precio de referencia no justifica una recomendación de compra."""
        market = FakeMarket(
            {"ASML": (750.0, "USD")}, tecnicos=self.TECNICOS_BUENOS,
            fuente=PriceSource.SIMULADO,
        )
        detector = OpportunityDetector(market=market)
        assert detector.scan_for_opportunities(market.get_batch_snapshots(["ASML"])) == []
        assert any(d["veredicto"] == "SIN DATOS" for d in detector.ultimo_diagnostico)

    def test_no_emite_sin_historico(self):
        market = FakeMarket({"ASML": (750.0, "USD")}, tecnicos={})
        detector = OpportunityDetector(market=market)
        assert detector.scan_for_opportunities(market.get_batch_snapshots(["ASML"])) == []

    def test_descarta_asimetria_insuficiente_y_lo_explica(self):
        tecnicos = {
            "ASML": {
                "precio": 950.0, "max_52s": 1000.0, "min_52s": 800.0, "sma_200": 900.0,
                "vol_diaria": 0.03, "caida_desde_max_pct": 5.0, "sobre_sma200_pct": 5.5,
            }
        }
        market = FakeMarket({"ASML": (950.0, "USD")}, tecnicos=tecnicos)
        detector = OpportunityDetector(market=market)
        assert detector.scan_for_opportunities(market.get_batch_snapshots(["ASML"])) == []
        diag = {d["ticker"]: d for d in detector.ultimo_diagnostico}
        assert diag["ASML"]["veredicto"] == "NO CUALIFICA"
        assert "descuento" in diag["ASML"]["detalle"]

    def test_descarta_tendencia_rota(self):
        tecnicos = {
            "ASML": {
                "precio": 500.0, "max_52s": 1000.0, "min_52s": 480.0, "sma_200": 800.0,
                "vol_diaria": 0.01, "caida_desde_max_pct": 50.0, "sobre_sma200_pct": -37.5,
            }
        }
        market = FakeMarket({"ASML": (500.0, "USD")}, tecnicos=tecnicos)
        detector = OpportunityDetector(market=market)
        assert detector.scan_for_opportunities(market.get_batch_snapshots(["ASML"])) == []


# ======================================================================
# Rebalanceo mensual
# ======================================================================
class TestRebalanceo:
    def _plan(self, cartera, market, estado=VitalState.OPTIMO):
        valuator = PortfolioValuator(market=market, fx=FakeFx())
        v = valuator.value(cartera)
        g = RiskGovernor()
        h = g.calculate_health(HealthStatus(capital_inicial_eur=v.nav_eur), v)
        h = h.model_copy(update={"estado_vital": estado})
        engine = MonthlyRebalanceEngine(market=market, governor=g, fx=FakeFx())
        return engine.generate_monthly_plan(health=h, valuation=v, incumplimientos=g.audit_portfolio(v, h)), v

    def test_restaura_el_suelo_de_liquidez(self, market_simple):
        """Cartera invertida al 99%: el plan debe liberar caja."""
        cartera = Portfolio(efectivo_eur=10.0, posiciones=[
            Position(ticker=f"T{i}", nombre=f"A{i}", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=1.0, coste_unitario_eur=100.0,
                     sector=f"S{i}")
            for i in range(10)
        ])
        plan, v = self._plan(cartera, market_simple)

        assert v.peso_efectivo_pct < MIN_CASH_PCT
        assert plan.peso_cash_objetivo_pct >= MIN_CASH_PCT
        assert sum(p.delta_eur for p in plan.propuestas if p.delta_eur < 0) < 0

    def test_recorta_toda_posicion_por_encima_del_tope(self, market_simple):
        cartera = Portfolio(efectivo_eur=1000.0, posiciones=[
            Position(ticker="GRANDE", nombre="Grande", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=50.0, coste_unitario_eur=100.0,
                     sector="Uno"),
            Position(ticker="PEQUE", nombre="Peque", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=20.0, coste_unitario_eur=100.0,
                     sector="Dos"),
        ])
        plan, _ = self._plan(cartera, market_simple)
        objetivos = {p.ticker: p for p in plan.propuestas}

        assert objetivos["GRANDE"].peso_objetivo_pct <= MAX_POSITION_SIZE_PCT
        assert objetivos["GRANDE"].accion in (RebalanceAction.REDUCIR, RebalanceAction.VENDER)

    def test_ninguna_posicion_en_incumplimiento_queda_en_mantener(self, market_simple):
        """Un exceso menor que la banda muerta seguía figurando como MANTENER."""
        # Sobrepasa el tope en apenas 0.26 puntos: menos que la banda muerta.
        cartera = Portfolio(efectivo_eur=1980.0, posiciones=[
            Position(ticker="JUSTO", nombre="Justo", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=10.31, coste_unitario_eur=100.0,
                     sector="Uno"),
        ] + [
            Position(ticker=f"R{i}", nombre=f"R{i}", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=8.0, coste_unitario_eur=100.0,
                     sector=f"S{i}")
            for i in range(9)
        ])
        plan, v = self._plan(cartera, market_simple)
        justo = next(p for p in plan.propuestas if p.ticker == "JUSTO")
        peso_inicial = next(x for x in v.posiciones if x.ticker == "JUSTO").peso_pct

        # El exceso cabe dentro de la banda muerta de ruido, que es exactamente
        # el caso que antes se colaba como MANTENER.
        assert peso_inicial > MAX_POSITION_SIZE_PCT
        assert peso_inicial - MAX_POSITION_SIZE_PCT < UMBRAL_ACCION_PCT
        assert justo.accion != RebalanceAction.MANTENER
        assert justo.peso_objetivo_pct <= MAX_POSITION_SIZE_PCT

    def test_mantener_implica_delta_cero(self, market_simple):
        cartera = Portfolio(efectivo_eur=2000.0, posiciones=[
            Position(ticker=f"T{i}", nombre=f"A{i}", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=8.0, coste_unitario_eur=100.0,
                     sector=f"S{i}")
            for i in range(10)
        ])
        plan, _ = self._plan(cartera, market_simple)
        for p in plan.propuestas:
            if p.accion == RebalanceAction.MANTENER:
                assert p.delta_eur == 0.0

    def test_liquida_las_posiciones_polvo(self, market_simple):
        cartera = Portfolio(efectivo_eur=2000.0, posiciones=[
            Position(ticker="CORE", nombre="Core", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=70.0, coste_unitario_eur=100.0,
                     sector="Uno"),
            Position(ticker="POLVO", nombre="Polvo", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=0.5, coste_unitario_eur=100.0,
                     sector="Dos"),
        ])
        plan, v = self._plan(cartera, market_simple)
        polvo = next(p for p in plan.propuestas if p.ticker == "POLVO")

        assert next(x for x in v.posiciones if x.ticker == "POLVO").peso_pct < 1.0
        assert polvo.accion == RebalanceAction.VENDER
        assert polvo.peso_objetivo_pct == 0.0

    def test_respeta_el_tope_sectorial(self, market_simple):
        cartera = Portfolio(efectivo_eur=2000.0, posiciones=[
            Position(ticker=f"D{i}", nombre=f"D{i}", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=10.0, coste_unitario_eur=100.0,
                     sector="Defensa")
            for i in range(5)
        ] + [
            Position(ticker="OTRO", nombre="Otro", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=10.0, coste_unitario_eur=100.0,
                     sector="Otro"),
        ])
        plan, _ = self._plan(cartera, market_simple)
        defensa = sum(p.peso_objetivo_pct for p in plan.propuestas if p.sector == "Defensa")
        assert defensa <= MAX_SECTOR_SIZE_PCT + 0.1

    def test_estado_critico_no_propone_compras(self, market_simple):
        cartera = Portfolio(efectivo_eur=5000.0, posiciones=[
            Position(ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=10.0, coste_unitario_eur=100.0,
                     sector="Uno"),
        ])
        plan, _ = self._plan(cartera, market_simple, estado=VitalState.CUIDADOS_INTENSIVOS)
        assert all(
            p.accion not in (RebalanceAction.COMPRAR, RebalanceAction.INCREMENTAR)
            for p in plan.propuestas
        )
        assert any("CUIDADOS_INTENSIVOS" in a for a in plan.advertencias)

    def test_los_pesos_objetivo_no_superan_el_100(self, market_simple):
        cartera = Portfolio(efectivo_eur=10.0, posiciones=[
            Position(ticker=f"T{i}", nombre=f"A{i}", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=5.0, coste_unitario_eur=100.0,
                     sector=f"S{i}")
            for i in range(20)
        ])
        plan, _ = self._plan(cartera, market_simple)
        assert sum(p.peso_objetivo_pct for p in plan.propuestas) <= 100.0
        assert plan.peso_cash_objetivo_pct >= 0.0


# ======================================================================
# Bóveda
# ======================================================================
class TestBoveda:
    def test_lee_el_esquema_antiguo_en_usd(self, vault_tmp):
        """Compatibilidad con los ficheros de la versión anterior."""
        vault_tmp.health_path.write_text(
            "---\n"
            "estado_vital: ALERTA\n"
            "capital_inicial: 8500.0\n"
            "capital_actual: 9000.0\n"
            "pnl_total_usd: 500.0\n"
            "---\n\n# Antiguo\n",
            encoding="utf-8",
        )
        h = vault_tmp.read_health_status()
        assert h.capital_inicial_eur == pytest.approx(8500.0)
        assert h.nav_actual_eur == pytest.approx(9000.0)
        assert h.pnl_total_eur == pytest.approx(500.0)
        # Sin HWM guardado, se siembra con el mayor valor conocido para no
        # fabricar un drawdown que nunca ocurrió.
        assert h.nav_maximo_historico_eur == pytest.approx(9000.0)

    def test_estado_ausente_devuelve_valores_neutros(self, vault_tmp):
        h = vault_tmp.read_health_status()
        assert h.estado_vital == VitalState.OPTIMO
        assert h.drawdown_actual_pct == 0.0

    def test_ida_y_vuelta_del_estado_vital(self, vault_tmp, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        g = RiskGovernor()
        h = g.calculate_health(
            HealthStatus(capital_inicial_eur=3000.0, nav_maximo_historico_eur=4000.0), v
        )
        vault_tmp.update_health_status(h, valuation=v, incumplimientos=g.audit_portfolio(v, h))

        leida = vault_tmp.read_health_status()
        assert leida.nav_maximo_historico_eur == pytest.approx(h.nav_maximo_historico_eur)
        assert leida.drawdown_actual_pct == pytest.approx(h.drawdown_actual_pct)
        assert leida.estado_vital == h.estado_vital

    def test_ultima_actualizacion_persiste_para_detectar_el_dia(
        self, vault_tmp, cartera_simple, valuator_simple
    ):
        """`ultima_actualizacion` se lee del fichero, no es siempre "ahora".

        De ella depende que `sharky.cli startup` sepa si el ciclo diario de
        hoy ya se ejecutó: si la lectura devolviera siempre el instante
        actual, el ciclo se creería "recién hecho" incluso el primer día, y la
        energía metabólica nunca se desgastaría con el paso de los días.
        """
        v = valuator_simple.value(cartera_simple)
        h = RiskGovernor().calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        vault_tmp.update_health_status(h, valuation=v)

        leida = vault_tmp.read_health_status()
        assert leida.ultima_actualizacion.date() == date.today()

    def test_boveda_nueva_no_cuenta_como_ejecutada_hoy(self, vault_tmp):
        """Sin `Estado_Vital.md`, no debe parecer que el ciclo ya corrió hoy."""
        h = vault_tmp.read_health_status()
        assert h.ultima_actualizacion == datetime.min

    def test_los_informes_se_denominan_en_euros(self, vault_tmp, cartera_simple, valuator_simple):
        """Ningún importe en EUR debe etiquetarse con el símbolo del dólar."""
        v = valuator_simple.value(cartera_simple)
        h = RiskGovernor().calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        ruta = vault_tmp.update_health_status(h, valuation=v)

        texto = ruta.read_text(encoding="utf-8")
        assert "€" in texto
        assert "$" not in texto

    def test_aviso_visible_si_la_cobertura_es_parcial(self, vault_tmp, cartera_simple, valuator_simple):
        v = valuator_simple.value(cartera_simple)
        h = RiskGovernor().calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        texto = vault_tmp.update_health_status(h, valuation=v).read_text(encoding="utf-8")

        assert v.cobertura_mercado_pct < 100.0
        assert "WARNING" in texto and "estimad" in texto

    def test_incumplimiento_nuevo_se_fecha_con_la_fecha_de_hoy(
        self, vault_tmp, cartera_simple, valuator_simple
    ):
        """La primera vez que se ve una brecha, se registra con la fecha de hoy."""
        v = valuator_simple.value(cartera_simple)
        g = RiskGovernor()
        h = g.calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        incumplimientos = g.audit_portfolio(v, h)
        assert incumplimientos, "la cartera de prueba debe violar el tope sectorial"

        vault_tmp.update_health_status(h, valuation=v, incumplimientos=incumplimientos)

        meta, _ = vault_tmp.parse_markdown(vault_tmp.health_path.read_text(encoding="utf-8"))
        clave = _clave_incumplimiento(incumplimientos[0])
        assert meta["incumplimientos_desde"][clave] == date.today().strftime("%Y-%m-%d")
        assert meta["incumplimientos_escalados"] == 0

    def test_incumplimiento_persistente_conserva_su_fecha_original(
        self, vault_tmp, cartera_simple, valuator_simple
    ):
        """Una brecha que sigue abierta no debe 're-fecharse' hoy en cada ciclo.

        Si `update_health_status` la refechara cada vez, la antigüedad real
        nunca podría superar un día y la escalada de la auditoría de 2026-09
        no serviría para nada.
        """
        v = valuator_simple.value(cartera_simple)
        g = RiskGovernor()
        h = g.calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)
        incumplimientos = g.audit_portfolio(v, h)
        clave = _clave_incumplimiento(incumplimientos[0])

        fecha_antigua = (date.today() - timedelta(days=BREACH_ESCALATION_DAYS + 3)).strftime("%Y-%m-%d")
        vault_tmp._ensure_structure()
        vault_tmp.health_path.write_text(
            vault_tmp.build_markdown(
                {"incumplimientos_desde": {clave: fecha_antigua}}, "# Semilla de prueba\n"
            ),
            encoding="utf-8",
        )

        vault_tmp.update_health_status(h, valuation=v, incumplimientos=incumplimientos)

        meta, _ = vault_tmp.parse_markdown(vault_tmp.health_path.read_text(encoding="utf-8"))
        assert meta["incumplimientos_desde"][clave] == fecha_antigua
        assert meta["incumplimientos_escalados"] >= 1

        texto = vault_tmp.health_path.read_text(encoding="utf-8")
        assert "ESCALADA" in texto or "Escalado por antigüedad" in texto

    def test_incumplimiento_resuelto_se_retira_del_registro_de_antiguedad(
        self, vault_tmp, cartera_simple, valuator_simple
    ):
        """Una brecha que ya no aparece no debe seguir arrastrando su fecha."""
        v = valuator_simple.value(cartera_simple)
        g = RiskGovernor()
        h = g.calculate_health(HealthStatus(capital_inicial_eur=3400.0), v)

        clave_resuelta = "Regla que ya no aplica|Fantasma"
        vault_tmp._ensure_structure()
        vault_tmp.health_path.write_text(
            vault_tmp.build_markdown(
                {"incumplimientos_desde": {clave_resuelta: "2026-01-01"}}, "# Semilla\n"
            ),
            encoding="utf-8",
        )

        # Cartera conforme: sin incumplimientos en este ciclo.
        vault_tmp.update_health_status(h, valuation=v, incumplimientos=[])

        meta, _ = vault_tmp.parse_markdown(vault_tmp.health_path.read_text(encoding="utf-8"))
        assert clave_resuelta not in meta["incumplimientos_desde"]

    def test_diario_marca_la_inteligencia_simulada(self, vault_tmp):
        ruta = vault_tmp.write_daily_journal(
            "2026-08-31", "Texto de plantilla.", HealthStatus(), inteligencia_simulada=True
        )
        texto = ruta.read_text(encoding="utf-8")
        assert "inteligencia_simulada: true" in texto
        assert "modo simulación" in texto

    def test_diario_no_avisa_cuando_el_analisis_es_real(self, vault_tmp):
        ruta = vault_tmp.write_daily_journal(
            "2026-08-31", "Análisis real.", HealthStatus(), inteligencia_simulada=False
        )
        assert "modo simulación" not in ruta.read_text(encoding="utf-8")

    def test_memoria_diario_respeta_la_ventana_de_dias(self, vault_tmp):
        """Sólo entra en la memoria lo que cae dentro de los últimos N días."""
        hoy = date.today()
        vault_tmp.write_daily_journal(
            (hoy - timedelta(days=2)).strftime("%Y-%m-%d"), "Dentro de la ventana.", HealthStatus(),
        )
        vault_tmp.write_daily_journal(
            (hoy - timedelta(days=40)).strftime("%Y-%m-%d"), "Fuera de la ventana.", HealthStatus(),
        )

        memoria = vault_tmp.leer_memoria_diario(dias=7)

        fechas = [m["fecha"] for m in memoria]
        assert (hoy - timedelta(days=2)).strftime("%Y-%m-%d") in fechas
        assert (hoy - timedelta(days=40)).strftime("%Y-%m-%d") not in fechas

    def test_memoria_diario_ordena_de_mas_antigua_a_mas_reciente(self, vault_tmp):
        hoy = date.today()
        vault_tmp.write_daily_journal(hoy.strftime("%Y-%m-%d"), "Hoy.", HealthStatus())
        vault_tmp.write_daily_journal(
            (hoy - timedelta(days=1)).strftime("%Y-%m-%d"), "Ayer.", HealthStatus()
        )

        memoria = vault_tmp.leer_memoria_diario(dias=7)

        assert [m["fecha"] for m in memoria] == [
            (hoy - timedelta(days=1)).strftime("%Y-%m-%d"),
            hoy.strftime("%Y-%m-%d"),
        ]

    def test_memoria_diario_vacia_sin_diario_previo(self, vault_tmp):
        assert vault_tmp.leer_memoria_diario(dias=7) == []

    def test_enlace_escapa_el_pipe_del_alias_para_no_romper_tablas(self, vault_tmp):
        """[[Rheinmetall|RHM]] sin escapar parte una celda de tabla Markdown
        en dos columnas para cualquier parser que no sea Obsidian -- bug
        real reportado en "Mayores Movimientos de la Cartera" (2026-09)."""
        assert vault_tmp.enlace("RHM", "[[Rheinmetall]]") == "[[Rheinmetall\\|RHM]]"

    def test_enlace_sin_alias_no_escapa_nada(self, vault_tmp):
        """Si el nombre de la nota coincide con el ticker, no hay alias que
        escapar: `[[NIO]]` a secas, no `[[NIO\\|NIO]]`."""
        assert vault_tmp.enlace("NIO", "[[NIO]]") == "[[NIO]]"
        assert vault_tmp.enlace("NIO") == "[[NIO]]"

    def test_memoria_diario_dias_cero_no_lee_nada(self, vault_tmp):
        """dias=0 (o negativo) debe devolver vacío, no "todo el diario"."""
        vault_tmp.write_daily_journal(date.today().strftime("%Y-%m-%d"), "Hoy.", HealthStatus())
        assert vault_tmp.leer_memoria_diario(dias=0) == []

    def test_solo_se_leen_las_tesis_activas(self, vault_tmp):
        carpeta = vault_tmp.vault_path / "01_Tesis_Activas"
        (carpeta / "Tesis_Viva.md").write_text(
            "---\nticker: AAA\nestado: Activa\nprecio_entrada: 10\n"
            "stop_loss: 9\ntarget_precio: 15\n---\n\nCuerpo.\n", encoding="utf-8"
        )
        (carpeta / "Tesis_Cerrada.md").write_text(
            "---\nticker: BBB\nestado: Cerrada\nprecio_entrada: 10\n"
            "stop_loss: 9\ntarget_precio: 15\n---\n\nCuerpo.\n", encoding="utf-8"
        )
        (carpeta / "Tesis_Stub.md").write_text(
            "---\nalias: otra\nticker: CCC\n---\n\nRedirección.\n", encoding="utf-8"
        )

        tickers = {t.ticker for _, t in vault_tmp.list_active_theses()}
        assert tickers == {"AAA"}

    def test_deteccion_de_alerta_activa(self, vault_tmp):
        carpeta = vault_tmp.vault_path / "09_Alertas_Oportunidades"
        (carpeta / "a.md").write_text(
            "---\nid_alerta: A1\nticker: ASML\nestado: ACTIVA\n---\n\nCuerpo.\n", encoding="utf-8"
        )
        (carpeta / "b.md").write_text(
            "---\nid_alerta: A2\nticker: TSM\nestado: EXPIRADA\n---\n\nCuerpo.\n", encoding="utf-8"
        )
        assert vault_tmp.has_active_alert("asml") is True
        assert vault_tmp.has_active_alert("TSM") is False

    def test_alerta_conserva_la_fuente_de_precio_al_releer(self, vault_tmp):
        """`fuente_precio` debe sobrevivir al viaje de ida y vuelta por disco.

        `write_opportunity_alert` la persiste en el frontmatter, pero
        `list_active_alerts` la ignoraba al reconstruir el objeto y siempre
        devolvía MERCADO por defecto, aunque la alerta se hubiera escrito como
        SIMULADO: la marca de fiabilidad que exige `sharky.models` se perdía
        silenciosamente en cuanto la alerta se releía de la bóveda.
        """
        alerta = OpportunityAlert(
            id_alerta="ALT-TEST-ASML",
            ticker="ASML",
            empresa="ASML Holding N.V.",
            fecha_deteccion="2026-08-31",
            precio_actual=800.0,
            entrada_sugerida=800.0,
            stop_loss=736.0,
            target_precio=950.0,
            ratio_rr=2.34,
            potencial_ganancia_pct=18.75,
            riesgo_maximo_pct=8.0,
            descripcion_oportunidad="Tesis de prueba.",
            fuente_precio=PriceSource.SIMULADO,
        )
        vault_tmp.write_opportunity_alert(alerta)

        releidas = {a.ticker: a for _, a in vault_tmp.list_active_alerts()}
        assert releidas["ASML"].fuente_precio == PriceSource.SIMULADO

    def test_moc_no_duplica_entradas(self, vault_tmp):
        moc = vault_tmp.vault_path / "05_Diario_Reflexion" / "05_Diario_Reflexion.md"
        moc.write_text("# MOC\n\n## 📋 Entradas del Diario\n", encoding="utf-8")

        for _ in range(3):
            vault_tmp.write_daily_journal("2026-08-31", "Resumen.", HealthStatus())

        assert moc.read_text(encoding="utf-8").count("2026-08-31_Cierre_Mercado") == 1


# ======================================================================
# Ciclo de arranque (`sharky.cli startup`)
# ======================================================================
class TestCicloDeArranque:
    """Al encender el ordenador varias veces el mismo día, Claude se llama
    como máximo una vez: `ya_completo_ciclo_hoy` depende de que
    `_dias_desde_ultimo_ciclo` cuente días naturales reales, no invocaciones."""

    def test_mismo_dia_es_cero_dias(self):
        h = HealthStatus(ultimo_ciclo_diario=datetime.now())
        assert SharkyAgent._dias_desde_ultimo_ciclo(h) == 0.0

    def test_ayer_es_un_dia(self):
        h = HealthStatus(ultimo_ciclo_diario=datetime.now() - timedelta(days=1))
        assert SharkyAgent._dias_desde_ultimo_ciclo(h) == pytest.approx(1.0)

    def test_una_bovedad_nunca_actualizada_no_cuenta_como_hoy(self):
        """`datetime.min` (bóveda nueva o esquema ilegible) no debe leerse
        como "hace cero días": bloquearía para siempre el primer ciclo."""
        h = HealthStatus(ultimo_ciclo_diario=datetime.min)
        assert SharkyAgent._dias_desde_ultimo_ciclo(h) > 0

    def test_registrar_una_operacion_no_completa_el_ciclo_diario(
        self, tmp_path, cartera_simple, market_simple
    ):
        """Registrar una operación no debe contar como "el ciclo de hoy ya se
        ejecutó": son responsabilidades distintas (ver CICLO-2)."""
        vault = VaultManager(tmp_path)
        store = PortfolioStore(tmp_path)
        store.save(cartera_simple)
        fx = FakeFx()
        valuator = PortfolioValuator(market=market_simple, fx=fx)
        recorder = TradeRecorder(
            store=store, valuator=valuator, governor=RiskGovernor(), vault=vault,
            fx=fx, market=market_simple,
        )

        resultado = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=1.0, precio=100.0,
        )
        assert resultado.aprobada is True

        agent = SharkyAgent.__new__(SharkyAgent)
        agent.vault = vault
        assert agent.ya_completo_ciclo_hoy() is False


class _ClaudeQueFalla:
    """Doble de `ClaudeBrainClient` que siempre falla (ver CICLO-3)."""

    def generate_daily_intelligence(self, **kwargs):
        raise RuntimeError("fallo simulado de la API de Claude")


class TestCicloDiarioPersisteNivelesAntesDeClaude:
    def test_fallo_de_claude_no_pierde_el_stop_del_dia(self, tmp_path, monkeypatch):
        """CICLO-3: si `generate_daily_intelligence` falla, el stop-loss ya
        detectado hoy debe quedar escrito en Estado_Vital.md y en
        logs/alertas_niveles.json antes de que la excepción se propague, no
        perderse porque falló la prosa."""
        ruta_niveles = tmp_path / "logs" / "alertas_niveles.json"
        monkeypatch.setattr("sharky.level_watch.ALERTAS_NIVELES_PATH", ruta_niveles)

        vault = VaultManager(tmp_path)
        (vault.vault_path / "01_Tesis_Activas" / "Tesis_AAA.md").write_text(
            "---\nticker: AAA\nestado: Activa\ndivisa: EUR\nprecio_entrada: 100\n"
            "stop_loss: 90\ntarget_precio: 200\n---\n\nCuerpo.\n", encoding="utf-8"
        )
        store = PortfolioStore(tmp_path)
        store.save(Portfolio(efectivo_eur=1000.0, posiciones=[
            Position(ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA",
                     divisa_cotizacion="EUR", unidades=10.0, coste_unitario_eur=100.0,
                     sector="Tecnologia", nota_activo="[[Alfa]]"),
        ]))
        market = FakeMarket({"AAA": (85.0, "EUR")})  # por debajo del stop de 90
        fx = FakeFx()

        agent = SharkyAgent.__new__(SharkyAgent)
        agent.vault = vault
        agent.market = market
        agent.fx = fx
        agent.store = store
        agent.valuator = PortfolioValuator(market=market, fx=fx)
        agent.risk = RiskGovernor()
        agent.claude = _ClaudeQueFalla()
        agent.detector = OpportunityDetector(market=market)

        with pytest.raises(RuntimeError):
            agent.run_daily_cycle(watchlist=["AAA"])

        assert ruta_niveles.exists()
        datos_niveles = json.loads(ruta_niveles.read_text(encoding="utf-8"))
        assert datos_niveles["accionables"] == 1

        texto_estado = vault.health_path.read_text(encoding="utf-8")
        assert "stops_alcanzados: 1" in texto_estado
        assert "## 🎯 Niveles Alcanzados" in texto_estado


# ======================================================================
# Cliente de Claude: diagnóstico cuando la API responde sin texto
# ======================================================================
class _BloqueFalso:
    def __init__(self, tipo: str, texto: str = ""):
        self.type = tipo
        self.text = texto


class _RespuestaFalsa:
    def __init__(self, bloques, stop_reason="end_turn"):
        self.content = bloques
        self.stop_reason = stop_reason


class _MessagesFalso:
    def __init__(self, respuesta):
        self._respuesta = respuesta

    def create(self, **kwargs):
        return self._respuesta


class _ClienteAnthropicFalso:
    def __init__(self, respuesta):
        self.messages = _MessagesFalso(respuesta)


class TestClaudeBrainClient:
    """`_invocar` nunca deja pasar una respuesta sin texto como si fuera un
    análisis real -- cae al generador simulado y lo declara. Lo que estos
    tests cubren es que el motivo del fallo quede diagnosticable en el log,
    en vez de un "no contenía texto" sin más contexto (ver conversación de
    soporte de 2026-09: el log real no decía por qué la API no daba texto)."""

    def _cliente_con_respuesta_falsa(self, respuesta) -> ClaudeBrainClient:
        cliente = ClaudeBrainClient(api_key="sk-ant-test")
        cliente.is_live = True
        cliente.client = _ClienteAnthropicFalso(respuesta)
        return cliente

    def test_respuesta_con_texto_se_usa_tal_cual(self):
        cliente = self._cliente_con_respuesta_falsa(
            _RespuestaFalsa([_BloqueFalso("text", "Análisis real.")])
        )
        resultado = cliente._invocar("prompt", fallback="plantilla")
        assert resultado.texto == "Análisis real."
        assert resultado.simulado is False

    def test_respuesta_sin_bloques_de_texto_cae_al_fallback_con_diagnostico(self):
        """P.ej. si el modelo sólo devuelve un bloque `thinking` y se corta
        por max_tokens antes de emitir texto: exactamente lo que se vio en
        producción con `stop_reason='max_tokens'`."""
        cliente = self._cliente_con_respuesta_falsa(
            _RespuestaFalsa([_BloqueFalso("thinking", "razonamiento interno")], stop_reason="max_tokens")
        )
        resultado = cliente._invocar("prompt", fallback="plantilla")

        assert resultado.simulado is True
        assert resultado.texto == "plantilla"
        assert "max_tokens" in resultado.error
        assert "thinking" in resultado.error
        # Señala la variable del perfil concreto que hay que subir.
        assert "SHARKY_MAX_TOKENS_DIARIO" in resultado.error

    def test_respuesta_vacia_cae_al_fallback_con_diagnostico(self):
        cliente = self._cliente_con_respuesta_falsa(_RespuestaFalsa([], stop_reason="end_turn"))
        resultado = cliente._invocar("prompt", fallback="plantilla")

        assert resultado.simulado is True
        assert "(vacío)" in resultado.error


# ======================================================================
# Escaneo semanal de noticias
# ======================================================================
class _CitaFalsa:
    def __init__(self, url: str, title: str):
        self.url = url
        self.title = title


class _BloqueTextoConCitas:
    type = "text"

    def __init__(self, texto: str, citas=None):
        self.text = texto
        self.citations = citas or []


class _BloqueBusquedaFalso:
    type = "server_tool_use"
    name = "web_search"

    def __init__(self, query: str):
        self.input = {"query": query}


def _posiciones_noticias():
    return [
        Position(
            ticker="INDRA", nombre="Indra Sistemas, S.A.", ticker_cotizacion="IDR.MC",
            divisa_cotizacion="EUR", clase=AssetClass.ACCION,
            unidades=2.0, coste_unitario_eur=25.0, sector="Defensa",
        ),
        Position(
            ticker="MSFT", nombre="Microsoft Corporation", ticker_cotizacion="MSFT",
            divisa_cotizacion="USD", clase=AssetClass.ACCION,
            unidades=1.0, coste_unitario_eur=400.0, sector="Tecnologia",
        ),
    ]


class TestNewsScanner:
    """`NewsScanner` no tiene modo simulado con sentido: sin clave de API en
    vivo declara que no pudo buscar, en vez de fingir noticias reales que
    nunca se buscaron (a diferencia de `ClaudeBrainClient`, que sí rellena
    con una plantilla determinista)."""

    def _con_respuesta_falsa(self, respuesta) -> NewsScanner:
        scanner = NewsScanner(api_key="sk-ant-test")
        scanner.is_live = True
        scanner.client = _ClienteAnthropicFalso(respuesta)
        return scanner

    def test_sin_clave_viva_declara_no_disponible(self):
        scanner = NewsScanner(api_key="")
        resultado = scanner.scan(_posiciones_noticias())
        assert resultado.disponible is False
        assert "ANTHROPIC_API_KEY" in resultado.texto

    def test_cartera_vacia_no_llama_a_la_api(self):
        scanner = NewsScanner(api_key="")
        resultado = scanner.scan([])
        assert resultado.disponible is True
        assert "Sin posiciones" in resultado.texto

    def test_respuesta_con_texto_y_citas_se_recogen_por_activo(self):
        respuesta = _RespuestaFalsa([
            _BloqueBusquedaFalso("Indra Sistemas noticias esta semana"),
            _BloqueTextoConCitas(
                "## INDRA\nResultados por encima de guidance.\n",
                citas=[_CitaFalsa("https://example.com/indra", "Indra bate previsiones")],
            ),
            _BloqueBusquedaFalso("Microsoft noticias esta semana"),
            _BloqueTextoConCitas(
                "## MSFT\nNuevo contrato cloud con el gobierno de EEUU.\n",
                citas=[_CitaFalsa("https://example.com/msft", "MSFT gana contrato")],
            ),
        ])
        scanner = self._con_respuesta_falsa(respuesta)

        resultado = scanner.scan(_posiciones_noticias())

        assert resultado.disponible is True
        assert "## INDRA" in resultado.texto
        assert "## MSFT" in resultado.texto
        assert resultado.fuentes == [
            "[Indra bate previsiones](https://example.com/indra)",
            "[MSFT gana contrato](https://example.com/msft)",
        ]
        assert resultado.busquedas_realizadas == 2
        assert resultado.modelo == scanner.model

    def test_pide_la_tool_de_busqueda_web_con_tope_por_activo(self):
        capturado = {}

        class _MessagesEspia:
            def create(self, **kwargs):
                capturado.update(kwargs)
                return _RespuestaFalsa([_BloqueTextoConCitas("## INDRA\nSin novedades.\n")])

        class _ClienteEspia:
            messages = _MessagesEspia()

        scanner = NewsScanner(api_key="sk-ant-test")
        scanner.is_live = True
        scanner.client = _ClienteEspia()

        scanner.scan(_posiciones_noticias())

        tool = capturado["tools"][0]
        assert tool["type"] == "web_search_20250305"
        assert tool["name"] == "web_search"
        assert tool["max_uses"] >= 2  # al menos una búsqueda por activo

    def test_respuesta_sin_texto_no_se_confunde_con_analisis_real(self):
        scanner = self._con_respuesta_falsa(_RespuestaFalsa([]))
        resultado = scanner.scan(_posiciones_noticias())
        assert resultado.disponible is False
        assert "no contenía texto" in resultado.error

    def test_url_repetida_no_se_duplica_en_fuentes(self):
        respuesta = _RespuestaFalsa([
            _BloqueTextoConCitas(
                "## INDRA\nUno.\n",
                citas=[_CitaFalsa("https://example.com/x", "Fuente X")],
            ),
            _BloqueTextoConCitas(
                "## MSFT\nDos, misma fuente.\n",
                citas=[_CitaFalsa("https://example.com/x", "Fuente X")],
            ),
        ])
        scanner = self._con_respuesta_falsa(respuesta)
        resultado = scanner.scan(_posiciones_noticias())
        assert resultado.fuentes == ["[Fuente X](https://example.com/x)"]


class TestVaultManagerNoticiasSemanales:
    def test_sin_escaneos_previos_devuelve_none(self, vault_tmp):
        assert vault_tmp.leer_ultima_fecha_noticias_semanales() is None

    def test_escribe_y_relee_la_fecha_del_ultimo_escaneo(self, vault_tmp):
        moc = vault_tmp.vault_path / "04_Sentimiento_Y_Flujos" / "04_Sentimiento_Y_Flujos.md"
        moc.write_text("# MOC\n", encoding="utf-8")

        resultado = NewsScanResult(
            texto="## INDRA\nSin novedades.\n",
            fuentes=["[Fuente](https://example.com)"],
            modelo="claude-sonnet-5",
            busquedas_realizadas=1,
        )
        posiciones = _posiciones_noticias()

        ruta_antigua = vault_tmp.write_weekly_news_report("2026-08-30", resultado, posiciones)
        assert vault_tmp.leer_ultima_fecha_noticias_semanales() == date(2026, 8, 30)

        # Un escaneo posterior debe quedar como el más reciente, sin
        # importar el orden en que se listen los ficheros en disco.
        ruta_nueva = vault_tmp.write_weekly_news_report("2026-09-06", resultado, posiciones)
        assert vault_tmp.leer_ultima_fecha_noticias_semanales() == date(2026, 9, 6)

        contenido = ruta_nueva.read_text(encoding="utf-8")
        assert "INDRA" in contenido and "MSFT" in contenido
        assert "[Fuente](https://example.com)" in contenido

        moc_texto = moc.read_text(encoding="utf-8")
        assert "## 📰 Noticias Semanales" in moc_texto
        assert f"[[{ruta_antigua.stem}]]" in moc_texto
        assert f"[[{ruta_nueva.stem}]]" in moc_texto

    def test_moc_no_duplica_entradas(self, vault_tmp):
        moc = vault_tmp.vault_path / "04_Sentimiento_Y_Flujos" / "04_Sentimiento_Y_Flujos.md"
        moc.write_text("# MOC\n\n## 📰 Noticias Semanales\n", encoding="utf-8")

        resultado = NewsScanResult(texto="## INDRA\nSin novedades.\n")
        for _ in range(3):
            vault_tmp.write_weekly_news_report("2026-08-30", resultado, _posiciones_noticias())

        assert moc.read_text(encoding="utf-8").count("2026-08-30_Noticias_Semanales") == 1

    def test_escaneo_no_disponible_deja_aviso_visible(self, vault_tmp):
        resultado = NewsScanResult(
            disponible=False, texto="No se pudo buscar.", error="sin API en vivo",
        )
        ruta = vault_tmp.write_weekly_news_report("2026-08-30", resultado, _posiciones_noticias())
        assert "Escaneo no disponible" in ruta.read_text(encoding="utf-8")


# ======================================================================
# Gating semanal (`SharkyAgent.noticias_semanales_pendiente`)
# ======================================================================
class TestTocaNoticiasSemanales:
    """Mismo criterio que `TestCicloDeArranque` para el ciclo diario, pero en
    clave semanal: dispara el día configurado, no se repite el mismo día, y
    no se queda huérfano indefinidamente si esa semana no tocó encender el
    ordenador el día exacto."""

    def test_nunca_ha_corrido_toca(self):
        assert SharkyAgent._toca_noticias_semanales(None) is True

    def test_mismo_dia_no_repite(self):
        hoy = date(2026, 9, 6)  # domingo
        assert SharkyAgent._toca_noticias_semanales(hoy, hoy=hoy) is False

    def test_dia_siguiente_que_no_es_el_configurado_no_toca(self):
        domingo = date(2026, 9, 6)
        lunes = date(2026, 9, 7)
        assert domingo.weekday() == NEWS_SCAN_WEEKDAY
        assert SharkyAgent._toca_noticias_semanales(domingo, hoy=lunes) is False

    def test_el_dia_configurado_de_la_semana_siguiente_toca(self):
        domingo = date(2026, 9, 6)
        domingo_siguiente = date(2026, 9, 13)
        assert SharkyAgent._toca_noticias_semanales(domingo, hoy=domingo_siguiente) is True

    def test_red_de_seguridad_a_los_7_dias_aunque_no_sea_el_dia_configurado(self):
        """Si el ordenador no se enciende nunca en domingo, el escaneo no
        debe quedar huérfano para siempre: en cuanto pasan 7 días desde el
        último, toca igual."""
        domingo = date(2026, 9, 6)
        martes_siguiente = date(2026, 9, 15)
        assert martes_siguiente.weekday() != NEWS_SCAN_WEEKDAY
        assert (martes_siguiente - domingo).days >= 7
        assert SharkyAgent._toca_noticias_semanales(domingo, hoy=martes_siguiente) is True

    def test_antes_de_7_dias_y_sin_ser_el_dia_configurado_no_toca(self):
        domingo = date(2026, 9, 6)
        sabado_siguiente = date(2026, 9, 12)  # 6 días, todavía no toca
        assert SharkyAgent._toca_noticias_semanales(domingo, hoy=sabado_siguiente) is False


class TestRunWeeklyNewsScan:
    """`run_weekly_news_scan` es pura composición de piezas ya cubiertas por
    su cuenta (`NewsScanner`, `VaultManager`); aquí sólo se comprueba el
    cableado -- mismo criterio que el resto de ciclos de `SharkyAgent`, que
    tampoco se instancian completos en la suite (evitan tocar red real vía
    `yfinance`/Anthropic)."""

    def test_compone_store_news_y_vault_correctamente(self, vault_tmp, store_tmp):
        moc = vault_tmp.vault_path / "04_Sentimiento_Y_Flujos" / "04_Sentimiento_Y_Flujos.md"
        moc.write_text("# MOC\n", encoding="utf-8")

        agent = SharkyAgent.__new__(SharkyAgent)
        agent.vault = vault_tmp
        agent.store = store_tmp

        class _NewsScannerFalso:
            def __init__(self):
                self.recibidas = None
                self.kwargs = {}

            def scan(self, positions, **kwargs):
                self.recibidas = list(positions)
                self.kwargs = kwargs
                return NewsScanResult(texto="## AAA\nSin novedades.\n", modelo="claude-sonnet-5")

        agent.news = _NewsScannerFalso()

        res = agent.run_weekly_news_scan()

        assert res["disponible"] is True
        assert set(res["activos_analizados"]) == {"AAA", "BBB", "CCC"}
        assert [p.ticker for p in agent.news.recibidas] == res["activos_analizados"]
        assert Path(res["nota_guardada"]).exists()
        assert vault_tmp.leer_ultima_fecha_noticias_semanales() == date.today()

    def test_pasa_el_contexto_de_la_semana_y_las_posiciones_a_vigilar(self, vault_tmp, store_tmp):
        """El escaneo semanal no busca a ciegas: recibe las conclusiones de
        los controles diarios de la semana y prioriza lo que marcaron."""
        hoy = date.today()
        vault_tmp.write_daily_journal(
            (hoy - timedelta(days=3)).isoformat(), "Control.", HealthStatus(),
            conclusion="- AAA cae un 9% sin noticia conocida.",
            posiciones_a_vigilar=["AAA"],
        )
        vault_tmp.write_daily_journal(
            (hoy - timedelta(days=20)).isoformat(), "Control antiguo.", HealthStatus(),
            conclusion="- Fuera de la ventana semanal.",
            posiciones_a_vigilar=["CCC"],
        )

        agent = SharkyAgent.__new__(SharkyAgent)
        agent.vault = vault_tmp
        agent.store = store_tmp

        class _NewsScannerFalso:
            kwargs = {}

            def scan(self, positions, **kwargs):
                _NewsScannerFalso.kwargs = kwargs
                return NewsScanResult(texto="## AAA\nSin novedades.\n")

        agent.news = _NewsScannerFalso()
        res = agent.run_weekly_news_scan()

        assert res["prioritarios"] == ["AAA"]
        assert _NewsScannerFalso.kwargs["prioritarios"] == ["AAA"]
        assert "AAA cae un 9%" in _NewsScannerFalso.kwargs["contexto_semana"]
        assert "Fuera de la ventana" not in _NewsScannerFalso.kwargs["contexto_semana"]


# ======================================================================
# Las noticias semanales como contexto de decisión (no sólo archivo)
# ======================================================================
class TestLeerUltimasNoticiasSemanales:
    """`leer_ultimas_noticias_semanales` es lo que hace que el escaneo deje
    de ser un archivo muerto: el informe diario y el Comité lo leen a través
    de este método, así que el resumen que devuelve debe ser justo la
    sección útil -- sin fuentes ni enlaces del grafo, que sólo gastarían
    tokens del prompt sin aportar nada a la decisión."""

    def test_extrae_solo_la_seccion_de_resumen(self, vault_tmp):
        resultado = NewsScanResult(
            texto="## AAA\nResultados por encima de guidance.\n## BBB\nSin novedades.\n",
            fuentes=["[Fuente](https://example.com/x)"],
            modelo="claude-sonnet-5",
        )
        vault_tmp.write_weekly_news_report("2026-09-06", resultado, _posiciones_noticias())

        noticias = vault_tmp.leer_ultimas_noticias_semanales()

        assert noticias["fecha"] == date(2026, 9, 6)
        assert noticias["disponible"] is True
        assert "## AAA" in noticias["resumen"]
        assert "Resultados por encima de guidance" in noticias["resumen"]
        # Ni las fuentes ni los enlaces del grafo deben colarse en el resumen.
        assert "Fuentes Citadas" not in noticias["resumen"]
        assert "example.com" not in noticias["resumen"]
        assert "Enlaces del Grafo" not in noticias["resumen"]

    def test_sin_notas_devuelve_none(self, vault_tmp):
        assert vault_tmp.leer_ultimas_noticias_semanales() is None

    def test_marca_no_disponible_cuando_el_ultimo_intento_fallo(self, vault_tmp):
        resultado = NewsScanResult(disponible=False, texto="No se pudo buscar.", error="sin API en vivo")
        vault_tmp.write_weekly_news_report("2026-09-06", resultado, _posiciones_noticias())

        noticias = vault_tmp.leer_ultimas_noticias_semanales()
        assert noticias["disponible"] is False


class TestFormatearNoticiasParaElPrompt:
    """`ClaudeBrainClient._formatear_noticias` es compartida por el informe
    diario y el Comité: un único sitio decide cuándo avisar de que el
    escaneo está desactualizado, en vez de que cada consumidor tenga su
    propio umbral."""

    def test_sin_escaneo_lo_dice_explicitamente(self):
        texto = ClaudeBrainClient._formatear_noticias(None)
        assert "sharky noticias" in texto

    def test_intento_no_disponible_lo_declara(self):
        noticias = {"fecha": date(2026, 9, 6), "disponible": False, "resumen": ""}
        texto = ClaudeBrainClient._formatear_noticias(noticias)
        assert "no disponible" in texto
        assert "2026-09-06" in texto

    def test_escaneo_de_hoy_no_lleva_aviso_de_antiguedad(self):
        noticias = {"fecha": date.today(), "disponible": True, "resumen": "## AAA\nSin novedades.\n"}
        texto = ClaudeBrainClient._formatear_noticias(noticias)
        assert "desactualizado" not in texto
        assert "## AAA" in texto

    def test_escaneo_de_hace_mas_de_10_dias_avisa(self):
        antiguo = date.today() - timedelta(days=15)
        noticias = {"fecha": antiguo, "disponible": True, "resumen": "## AAA\nSin novedades.\n"}
        texto = ClaudeBrainClient._formatear_noticias(noticias)
        assert "desactualizado" in texto


class _MessagesEspia:
    """Captura los kwargs de cada llamada y devuelve respuestas en orden."""

    def __init__(self, *respuestas):
        self.llamadas = []
        self._respuestas = list(respuestas) or [_RespuestaFalsa([_BloqueFalso("text", "Informe.")])]

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        return self._respuestas[min(len(self.llamadas), len(self._respuestas)) - 1]


class _StreamEspia:
    def __init__(self, respuesta):
        self._respuesta = respuesta

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._respuesta


class _MessagesConStreamEspia(_MessagesEspia):
    def __init__(self, respuesta):
        super().__init__(respuesta)
        self.stream_llamadas = []

    def stream(self, **kwargs):
        self.stream_llamadas.append(kwargs)
        return _StreamEspia(self._respuestas[0])


class _ClienteEspia:
    def __init__(self, messages):
        self.messages = messages


def _claude_espia(messages) -> ClaudeBrainClient:
    cliente = ClaudeBrainClient(api_key="sk-ant-test")
    cliente.is_live = True
    cliente.client = _ClienteEspia(messages)
    return cliente


class TestExtraerConclusion:
    """La conclusión es lo único que cada nivel pasa al siguiente."""

    def test_extrae_la_seccion_final(self):
        texto = "## 1. Posiciones\nAAA sube.\n\n## Conclusión del día\n- Vigilar AAA.\n- Sin incumplimientos."
        assert extraer_conclusion(texto, CONCLUSION_DIA) == "- Vigilar AAA.\n- Sin incumplimientos."

    def test_tolera_variaciones_de_formato(self):
        texto = "### conclusion del dia:\n- Vigilar AAA."
        assert extraer_conclusion(texto, CONCLUSION_DIA) == "- Vigilar AAA."

    def test_se_detiene_en_el_siguiente_encabezado(self):
        texto = "## Conclusión de la semana\n- Uno.\n## Otra cosa\nNo es conclusión."
        assert extraer_conclusion(texto, CONCLUSION_SEMANA) == "- Uno."

    def test_sin_seccion_devuelve_vacio(self):
        assert extraer_conclusion("Texto sin conclusión.", CONCLUSION_MES) == ""


class TestClaveExplicitaVacia:
    def test_clave_vacia_no_usa_la_del_entorno(self, monkeypatch):
        """`api_key=""` no debe acabar llamando a la API real con la clave
        del `.env`: los tests lo hacían sin querer."""
        monkeypatch.setattr("sharky.config.ANTHROPIC_API_KEY", "sk-ant-api03-clave-real")
        assert ClaudeBrainClient(api_key="").is_live is False
        assert NewsScanner(api_key="").is_live is False


class TestControlDiario:
    """El control diario razona sólo sobre posiciones, precios, valor de
    mercado y normas, con el perfil barato (effort low)."""

    def test_prompt_centrado_en_posiciones_y_normas(self):
        messages = _MessagesEspia()
        cliente = _claude_espia(messages)
        valuation = PortfolioValuation(
            posiciones=[_pos("AAA", precio_eur=100.0), _pos("BBB", precio_eur=50.0)],
            efectivo_eur=500.0,
        )

        cliente.generate_daily_intelligence(
            health=HealthStatus(),
            valuation=valuation,
            variaciones={"AAA": -9.5, "BBB": 1.0},
            avisos_niveles=["STOP-LOSS AAA"],
        )

        llamada = messages.llamadas[0]
        prompt = llamada["messages"][0]["content"]
        assert "AAA" in prompt and "BBB" in prompt
        assert "-9.50% desde el último control" in prompt
        assert "STOP-LOSS AAA" in prompt
        assert CONCLUSION_DIA in prompt
        # Macro y noticias ya no entran en el control diario.
        assert "INDICADORES MACRO" not in prompt
        assert "NOTICIAS" not in prompt
        assert llamada["max_tokens"] == MAX_TOKENS_DIARIO
        assert llamada["output_config"] == {"effort": EFFORT_DIARIO}

    def test_movimientos_fuertes_segun_umbral(self):
        umbral = UMBRAL_MOVIMIENTO_VIGILANCIA_PCT
        variaciones = {"AAA": -(umbral + 0.5), "BBB": umbral - 0.5, "CCC": umbral}
        assert ClaudeBrainClient.movimientos_fuertes(variaciones) == ["AAA", "CCC"]

    def test_la_conclusion_del_modelo_se_extrae(self):
        messages = _MessagesEspia(_RespuestaFalsa([
            _BloqueFalso("text", "Todo en orden.\n\n## Conclusión del día\n- Vigilar AAA.")
        ]))
        resultado = _claude_espia(messages).generate_daily_intelligence(health=HealthStatus())
        assert resultado.conclusion == "- Vigilar AAA."

    def test_sin_conclusion_del_modelo_se_construye_una_determinista(self):
        """Si el modelo no la da (o no hay API), el nivel semanal sigue
        recibiendo algo medido en vez de nada."""
        cliente = ClaudeBrainClient(api_key="")
        resultado = cliente.generate_daily_intelligence(
            health=HealthStatus(nav_actual_eur=1234.0),
            variaciones={"AAA": -12.0},
        )
        assert resultado.simulado is True
        assert "1,234.00" in resultado.conclusion
        assert "AAA -12.00%" in resultado.conclusion


class TestInvocarPorPerfil:
    def test_presupuestos_grandes_usan_streaming(self):
        """El SDK rechaza peticiones sin streaming de más de ~21000 tokens."""
        messages = _MessagesConStreamEspia(_RespuestaFalsa([_BloqueFalso("text", "Estudio.")]))
        cliente = _claude_espia(messages)

        resultado = cliente._invocar("prompt", "plantilla", max_tokens=32000, effort="high")

        assert resultado.texto == "Estudio."
        assert messages.llamadas == []
        assert messages.stream_llamadas[0]["max_tokens"] == 32000
        assert messages.stream_llamadas[0]["output_config"] == {"effort": "high"}

    def test_effort_vacio_no_se_envia(self):
        messages = _MessagesEspia()
        _claude_espia(messages)._invocar("prompt", "plantilla", effort="")
        assert "output_config" not in messages.llamadas[0]


class TestBovedaNiveles:
    def test_el_diario_guarda_lo_que_releen_los_niveles_superiores(self, vault_tmp):
        valuation = PortfolioValuation(
            posiciones=[
                _pos("AAA", precio_eur=100.0),
                _pos("BBB", precio_eur=50.0, fuente=PriceSource.SIMULADO),
            ],
        )
        ruta = vault_tmp.write_daily_journal(
            "2026-09-18", "Control.", HealthStatus(), valuation=valuation,
            conclusion="- Vigilar AAA.", posiciones_a_vigilar=["AAA"],
        )
        meta, cuerpo = vault_tmp.parse_markdown(ruta.read_text(encoding="utf-8"))

        assert meta["conclusion_ia"] == "- Vigilar AAA."
        assert meta["posiciones_a_vigilar"] == ["AAA"]
        # Un precio no fiable no sirve de base para medir el movimiento de mañana.
        assert meta["precios_eur"] == {"AAA": 100.0}
        assert "Control Diario de la Cartera" in cuerpo

    def test_noticias_semanales_del_periodo_en_orden(self, vault_tmp):
        hoy = date.today()
        for dias in (40, 10, 3):
            vault_tmp.write_weekly_news_report(
                (hoy - timedelta(days=dias)).isoformat(),
                NewsScanResult(texto=f"## AAA\nHace {dias} días.\n\n## Conclusión de la semana\n- C{dias}."),
                _posiciones_noticias(),
            )

        escaneos = vault_tmp.leer_noticias_semanales(31)

        assert [e["fecha"] for e in escaneos] == [hoy - timedelta(days=10), hoy - timedelta(days=3)]
        assert "Hace 10 días" in escaneos[0]["resumen"]
        assert escaneos[1]["conclusion"] == "- C3."

    def test_estudio_mensual_se_escribe_y_se_relee(self, vault_tmp):
        moc = vault_tmp.vault_path / "08_Rebalanceos_Mensuales" / "08_Rebalanceos_Mensuales.md"
        moc.write_text("# MOC\n", encoding="utf-8")
        assert vault_tmp.existe_estudio_mensual("2026-08") is False

        vault_tmp.write_monthly_study(
            "2026-08", "2026-08-01",
            IntelligenceResult(texto="Estudio.", conclusion="- Reducir AAA.", modelo="m"),
            HealthStatus(),
        )

        assert vault_tmp.existe_estudio_mensual("2026-08") is True
        assert vault_tmp.leer_conclusion_estudio_anterior("2026-09") == "- Reducir AAA."
        # El propio mes no cuenta como "anterior".
        assert vault_tmp.leer_conclusion_estudio_anterior("2026-08") == ""
        assert "2026-08_Estudio_Mensual" in moc.read_text(encoding="utf-8")


class TestAgenteNiveles:
    def _agente(self, vault):
        agent = SharkyAgent.__new__(SharkyAgent)
        agent.vault = vault
        agent.claude = ClaudeBrainClient(api_key="")
        return agent

    def test_variacion_contra_el_ultimo_control_con_precios(self, vault_tmp):
        """Compara con el diario anterior más reciente, aunque no sea ayer."""
        hoy = date.today()
        base = PortfolioValuation(posiciones=[_pos("AAA", precio_eur=100.0)])
        vault_tmp.write_daily_journal((hoy - timedelta(days=3)).isoformat(), "x", HealthStatus(), valuation=base)

        hoy_val = PortfolioValuation(posiciones=[
            _pos("AAA", precio_eur=90.0),
            _pos("NUEVA", precio_eur=10.0),  # sin precio previo: no hay variación
        ])
        variaciones = self._agente(vault_tmp)._variaciones_desde_ultimo_control(hoy_val, hoy.isoformat())

        assert variaciones == {"AAA": pytest.approx(-10.0)}

    def test_posiciones_a_vigilar(self):
        """Movimientos fuertes y niveles alcanzados; nada fuera de cartera."""
        niveles = [
            LevelAlert(tipo=LevelKind.STOP_LOSS, ticker="BBB"),
            LevelAlert(tipo=LevelKind.STOP_LOSS, ticker="VENDIDA"),
        ]
        marcadas = SharkyAgent._posiciones_a_vigilar(
            {"AAA": -UMBRAL_MOVIMIENTO_VIGILANCIA_PCT - 1, "DDD": 0.5},
            niveles, ["AAA", "BBB", "DDD"],
        )
        assert marcadas == ["AAA", "BBB"]

    def test_estudio_mensual_pendiente(self, vault_tmp):
        agent = self._agente(vault_tmp)
        mes = date.today().strftime("%Y-%m")
        assert agent.estudio_mensual_pendiente() is True

        vault_tmp.write_monthly_study(
            mes, date.today().isoformat(), IntelligenceResult(texto="Estudio real."), HealthStatus(),
        )
        assert agent.estudio_mensual_pendiente() is False

    def test_estudio_simulado_se_reintenta_al_dia_siguiente_si_hay_api(self, vault_tmp):
        agent = self._agente(vault_tmp)
        mes = date.today().strftime("%Y-%m")
        ayer = (date.today() - timedelta(days=1)).isoformat()
        vault_tmp.write_monthly_study(
            mes, ayer, IntelligenceResult(texto="Plantilla.", simulado=True), HealthStatus(),
        )

        assert agent.estudio_mensual_pendiente() is False  # sin API no se reintenta
        agent.claude.is_live = True
        assert agent.estudio_mensual_pendiente() is True

        # Como mucho una vez al día.
        vault_tmp.write_monthly_study(
            mes, date.today().isoformat(), IntelligenceResult(texto="Plantilla.", simulado=True),
            HealthStatus(),
        )
        assert agent.estudio_mensual_pendiente() is False


class TestEstudioMensual:
    def _plan(self):
        return MonthlyRebalanceReport(
            mes_ano="October 2026", fecha="2026-10-01",
            propuestas=[AllocationProposal(
                ticker="AAA", sector="Tecnologia", accion=RebalanceAction.REDUCIR,
                peso_actual_pct=14.0, peso_objetivo_pct=10.0, capital_objetivo_eur=100.0,
                delta_eur=-40.0, motivo="Excede el máximo por activo",
            )],
        )

    def test_prompt_con_el_contexto_del_mes_y_perfil_mensual(self):
        messages = _MessagesConStreamEspia(_RespuestaFalsa([
            _BloqueFalso("text", "Estudio.\n\n## Conclusión del mes\n- Reducir AAA al 10%.")
        ]))
        cliente = _claude_espia(messages)

        resultado = cliente.generate_monthly_study(
            mes="2026-10",
            health=HealthStatus(),
            valuation=PortfolioValuation(posiciones=[_pos("AAA")]),
            incumplimientos=[],
            tesis=[],
            plan=self._plan(),
            macro_snapshots={},
            memoria_mes=[{"fecha": "2026-09-20", "conclusion_ia": "- AAA rompe soporte."}],
            noticias_mes=[{"fecha": date(2026, 9, 27), "disponible": True,
                           "resumen": "## AAA\nProfit warning.", "conclusion": ""}],
            conclusion_mes_anterior="- Mantener AAA.",
        )

        llamada = messages.stream_llamadas[0]
        prompt = llamada["messages"][0]["content"]
        assert "AAA rompe soporte" in prompt           # controles diarios
        assert "Profit warning" in prompt              # escaneos semanales
        assert "Excede el máximo por activo" in prompt  # plan del motor
        assert "- Mantener AAA." in prompt             # estudio anterior
        assert llamada["max_tokens"] == MAX_TOKENS_MENSUAL
        assert llamada["output_config"] == {"effort": EFFORT_MENSUAL}
        assert resultado.conclusion == "- Reducir AAA al 10%."

    def test_sin_api_devuelve_el_plan_determinista_declarado(self):
        resultado = ClaudeBrainClient(api_key="").generate_monthly_study(
            mes="2026-10", health=HealthStatus(), valuation=None, incumplimientos=[],
            tesis=[], plan=self._plan(), macro_snapshots={}, memoria_mes=[], noticias_mes=[],
        )
        assert resultado.simulado is True
        assert "AAA: REDUCIR" in resultado.texto.upper()
        assert resultado.conclusion


class TestNewsScannerContexto:
    def _scanner(self, messages) -> NewsScanner:
        scanner = NewsScanner(api_key="sk-ant-test")
        scanner.is_live = True
        scanner.client = _ClienteEspia(messages)
        return scanner

    def test_el_prompt_lleva_contexto_prioritarios_y_perfil_semanal(self):
        messages = _MessagesEspia(_RespuestaFalsa([_BloqueTextoConCitas("## INDRA\nNada.\n")]))
        self._scanner(messages).scan(
            _posiciones_noticias(),
            contexto_semana="- 2026-09-15: INDRA cae un 8%.",
            prioritarios=["INDRA", "NO_EN_CARTERA"],
        )

        llamada = messages.llamadas[0]
        prompt = llamada["messages"][0]["content"]
        assert "INDRA cae un 8%" in prompt
        assert "- INDRA" in prompt.split("POSICIONES A INVESTIGAR PRIMERO")[1]
        assert "NO_EN_CARTERA" not in prompt
        assert CONCLUSION_SEMANA in prompt
        assert llamada["output_config"] == {"effort": NEWS_EFFORT}

    def test_pause_turn_se_reanuda_y_se_acumula(self):
        """Con muchas búsquedas la API pausa el turno: hay que reanudarlo en
        vez de guardar un informe a medias."""
        primera = _RespuestaFalsa(
            [_BloqueBusquedaFalso("Indra"), _BloqueTextoConCitas("## INDRA\nUno.\n")],
            stop_reason="pause_turn",
        )
        segunda = _RespuestaFalsa([_BloqueTextoConCitas("## MSFT\nDos.\n")])
        messages = _MessagesEspia(primera, segunda)

        resultado = self._scanner(messages).scan(_posiciones_noticias())

        assert len(messages.llamadas) == 2
        # La reanudación reenvía lo ya generado como turno del asistente.
        assert messages.llamadas[1]["messages"][-1]["role"] == "assistant"
        assert "## INDRA" in resultado.texto and "## MSFT" in resultado.texto
        assert resultado.busquedas_realizadas == 1


class TestNoticiasEnElComite:
    """El dossier que ve el CIO en `sharky committee` también debe llevar
    las noticias recientes: es la otra vía de decisión, aparte del diario."""

    def test_el_dossier_incluye_las_noticias(self):
        capturado = {}

        class _MessagesEspia:
            def create(self, **kwargs):
                capturado.update(kwargs)
                return _RespuestaFalsa([_BloqueFalso("text", "Veredicto.")])

        class _ClienteEspia:
            messages = _MessagesEspia()

        claude = ClaudeBrainClient(api_key="sk-ant-test")
        claude.is_live = True
        claude.client = _ClienteEspia()

        comite = InvestmentCommittee(claude=claude)
        noticias = {
            "fecha": date.today(),
            "disponible": True,
            "resumen": "## MSFT\nNuevo contrato cloud con el gobierno de EEUU.\n",
        }

        comite.convene_session(
            health=HealthStatus(),
            market_snapshots={},
            macro_snapshots={},
            noticias_recientes=noticias,
        )

        prompt = capturado["messages"][0]["content"]
        assert "Noticias Recientes de la Cartera" in prompt
        assert "Nuevo contrato cloud con el gobierno de EEUU" in prompt


# ======================================================================
# Vigilancia de niveles: stop-loss y take-profit
# ======================================================================
def _pos(
    ticker: str = "AAA",
    precio_eur: float = 100.0,
    divisa_cot: str = "USD",
    fuente: PriceSource = PriceSource.MERCADO,
    unidades: float = 10.0,
) -> PositionValuation:
    """Posición valorada, con el precio en EUR ya resuelto."""
    return PositionValuation(
        ticker=ticker,
        nombre=ticker,
        nota_activo=f"[[{ticker}]]",
        unidades=unidades,
        precio_cotizacion=round(precio_eur / 0.90, 4) if divisa_cot == "USD" else precio_eur,
        divisa_cotizacion=divisa_cot,
        precio_unitario_eur=precio_eur,
        valor_mercado_eur=round(precio_eur * unidades, 2),
        coste_total_eur=round(precio_eur * unidades, 2),
        pnl_eur=0.0,
        pnl_pct=0.0,
        fuente_precio=fuente,
    )


def _valoracion(*posiciones: PositionValuation) -> PortfolioValuation:
    return PortfolioValuation(
        posiciones=list(posiciones),
        nav_eur=round(sum(p.valor_mercado_eur for p in posiciones), 2),
    )


def _tesis(
    ticker: str = "AAA",
    divisa: str = "USD",
    entrada: float = 0.0,
    stop: float = 0.0,
    target: float = 0.0,
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker=ticker,
        empresa=ticker,
        divisa=divisa,
        precio_entrada=entrada,
        stop_loss=stop,
        target_precio=target,
        tiene_posicion=True,
    )


def _revisar(tesis, valuation, fx=None):
    return revisar_niveles([(None, t) for t in tesis], valuation, fx or FakeFx())


class TestVigilanciaDeNiveles:
    """La comparación se hace en EUR aunque la tesis declare sus niveles en
    otra divisa: es el mismo error de unidades que fabricaba el PnL de la
    versión anterior, y aquí costaría no liquidar una posición rota."""

    def test_stop_cruzado_en_otra_divisa_se_detecta(self):
        # Stop de 100 USD = 90 € con la tasa del doble. Cotiza a 85 €.
        niveles = _revisar([_tesis(stop=100.0, target=200.0)], _valoracion(_pos(precio_eur=85.0)))
        assert len(niveles) == 1
        assert niveles[0].tipo is LevelKind.STOP_LOSS
        assert niveles[0].nivel_eur == pytest.approx(90.0)

    def test_stop_no_cruzado_no_genera_aviso(self):
        # 95 € sigue por encima del stop de 100 USD (= 90 €).
        niveles = _revisar([_tesis(stop=100.0, target=200.0)], _valoracion(_pos(precio_eur=95.0)))
        assert niveles == []

    def test_comparar_sin_convertir_seria_un_falso_positivo(self):
        """95 € < 100 (el número crudo del stop en USD), pero 95 € > 90 € (el
        stop convertido). Sin la conversión, Sharky ordenaría liquidar una
        posición sana."""
        niveles = _revisar([_tesis(stop=100.0, target=200.0)], _valoracion(_pos(precio_eur=95.0)))
        assert not [n for n in niveles if n.tipo is LevelKind.STOP_LOSS]

    def test_target_alcanzado_avisa_sin_ordenar_vender(self):
        # Target 120 USD = 108 €. Cotiza a 108.9 € (= 121 USD).
        niveles = _revisar(
            [_tesis(entrada=100.0, stop=90.0, target=120.0)],
            _valoracion(_pos(precio_eur=108.9)),
        )
        assert len(niveles) == 1
        assert niveles[0].tipo is LevelKind.TAKE_PROFIT
        assert "no obliga a vender" in texto(niveles[0])

    def test_target_propone_trailing_con_el_riesgo_inicial(self):
        """El trailing replica el riesgo que el RiskGovernor ya aprobó
        (entrada - stop = 10 USD), en vez de inventar un porcentaje nuevo."""
        niveles = _revisar(
            [_tesis(entrada=100.0, stop=90.0, target=120.0)],
            _valoracion(_pos(precio_eur=108.9)),  # 121 USD
        )
        assert niveles[0].criterio_stop == "trailing"
        assert niveles[0].stop_sugerido == pytest.approx(111.0)  # 121 - 10

    def test_break_even_gana_cuando_el_trailing_queda_por_debajo(self):
        """Con un stop inicial muy ancho el trailing caería por debajo del
        precio de entrada: proteger el principal manda."""
        niveles = _revisar(
            [_tesis(entrada=100.0, stop=50.0, target=110.0)],
            _valoracion(_pos(precio_eur=99.0)),  # 110 USD
        )
        assert niveles[0].criterio_stop == "break-even"
        assert niveles[0].stop_sugerido == pytest.approx(100.0)

    def test_el_stop_propuesto_nunca_empeora_el_vigente(self):
        """Sin precio de entrada el trailing cae al porcentaje por defecto; si
        eso quedara por debajo del stop vigente, subirlo sería bajarlo."""
        niveles = _revisar(
            [_tesis(entrada=0.0, stop=100.0, target=105.0)],
            _valoracion(_pos(precio_eur=94.5)),  # 105 USD
        )
        assert niveles[0].criterio_stop == "sin cambio"
        assert niveles[0].stop_sugerido == pytest.approx(100.0)

    def test_si_ambos_niveles_cruzan_manda_el_stop(self):
        """Un frontmatter incoherente (target por debajo del stop) no puede
        acabar en un aviso de beneficios sobre una posición a liquidar."""
        niveles = _revisar(
            [_tesis(stop=200.0, target=50.0)],
            _valoracion(_pos(precio_eur=100.0)),
        )
        assert [n.tipo for n in niveles] == [LevelKind.STOP_LOSS]

    def test_precio_no_fiable_se_declara_no_se_calla(self):
        """Valorar a coste y decir "no ha saltado el stop" es afirmar algo
        que no se ha medido."""
        niveles = _revisar(
            [_tesis(stop=100.0, target=200.0)],
            _valoracion(_pos(precio_eur=10.0, fuente=PriceSource.COSTE)),
        )
        assert [n.tipo for n in niveles] == [LevelKind.NO_VERIFICABLE]
        assert not niveles[0].es_accionable

    def test_divisa_sin_tipo_de_cambio_se_declara(self):
        niveles = _revisar(
            [_tesis(divisa="XYZ", stop=100.0, target=200.0)],
            _valoracion(_pos(precio_eur=85.0)),
        )
        assert [n.tipo for n in niveles] == [LevelKind.NO_VERIFICABLE]

    def test_tesis_sin_posicion_abierta_se_ignora(self):
        """Una tesis en radar no tiene nada que liquidar."""
        niveles = _revisar([_tesis(ticker="ZZZ", stop=100.0, target=200.0)], _valoracion(_pos()))
        assert niveles == []

    def test_tesis_sin_niveles_declarados_se_ignora(self):
        niveles = _revisar([_tesis(stop=0.0, target=0.0)], _valoracion(_pos()))
        assert niveles == []

    def test_orden_por_urgencia(self):
        """Stops primero, targets después, no verificables al final: es el
        orden en el que hay que leerlos, y lo heredan consola y bóveda."""
        niveles = _revisar(
            [
                _tesis(ticker="MUDO", stop=100.0, target=200.0),
                _tesis(ticker="TGT", entrada=100.0, stop=90.0, target=120.0),
                _tesis(ticker="STP", stop=100.0, target=300.0),
            ],
            _valoracion(
                _pos(ticker="MUDO", precio_eur=95.0, fuente=PriceSource.COSTE),
                _pos(ticker="TGT", precio_eur=108.9),
                _pos(ticker="STP", precio_eur=85.0),
            ),
        )
        assert [n.tipo for n in niveles] == [
            LevelKind.STOP_LOSS,
            LevelKind.TAKE_PROFIT,
            LevelKind.NO_VERIFICABLE,
        ]

    def test_resumen_cuenta_por_tipo(self):
        niveles = _revisar(
            [_tesis(stop=100.0, target=300.0)], _valoracion(_pos(precio_eur=85.0))
        )
        assert resumen(niveles) == "1 stop-loss"
        assert resumen([]) == "ningún nivel alcanzado"


class TestPersistenciaDeNiveles:
    """El aviso emergente de Windows corre en otro proceso, después del ciclo:
    lee este fichero en vez de volver a valorar la cartera, para no poder
    enseñar números distintos de los que acaba de escribir el diario."""

    def test_guardar_escribe_la_fecha_y_los_accionables(self, tmp_path: Path):
        niveles = _revisar(
            [_tesis(stop=100.0, target=300.0)], _valoracion(_pos(precio_eur=85.0))
        )
        destino = guardar(niveles, tmp_path / "logs" / "alertas_niveles.json")
        datos = json.loads(destino.read_text(encoding="utf-8"))
        assert datos["fecha"] == date.today().isoformat()
        assert datos["accionables"] == 1
        assert datos["alertas"][0]["tipo"] == "STOP_LOSS"
        assert "STOP-LOSS ALCANZADO" in datos["alertas"][0]["texto"]

    def test_guardar_sin_niveles_deja_constancia_del_cero(self, tmp_path: Path):
        """Un fichero vacío y un fichero ausente no significan lo mismo: el
        primero dice "hoy se miró y no había nada"."""
        destino = guardar([], tmp_path / "alertas.json")
        datos = json.loads(destino.read_text(encoding="utf-8"))
        assert datos["accionables"] == 0
        assert datos["alertas"] == []

    def test_cargar_reconstruye_lo_que_guardar_escribio(self, tmp_path: Path):
        """`TradeRecorder` recarga este fichero para no perder los niveles del
        día al reescribir Estado_Vital.md tras una operación (ver CICLO-1)."""
        niveles = _revisar(
            [_tesis(stop=100.0, target=300.0)], _valoracion(_pos(precio_eur=85.0))
        )
        destino = guardar(niveles, tmp_path / "alertas.json")
        recargados = cargar(destino)
        assert len(recargados) == 1
        assert recargados[0].tipo is LevelKind.STOP_LOSS
        assert recargados[0].ticker == niveles[0].ticker

    def test_cargar_ignora_un_fichero_de_ayer(self, tmp_path: Path):
        destino = tmp_path / "alertas.json"
        destino.write_text(
            json.dumps({"fecha": "2000-01-01", "alertas": [{"tipo": "STOP_LOSS", "ticker": "X"}]}),
            encoding="utf-8",
        )
        assert cargar(destino) == []

    def test_cargar_sin_fichero_devuelve_vacio(self, tmp_path: Path):
        assert cargar(tmp_path / "no_existe.json") == []


class TestNivelesEnEstadoVital:
    def test_la_seccion_aparece_en_el_cuadro_de_mandos(self, vault_tmp: VaultManager):
        niveles = _revisar(
            [
                _tesis(ticker="STP", stop=100.0, target=300.0),
                _tesis(ticker="TGT", entrada=100.0, stop=90.0, target=120.0),
            ],
            _valoracion(
                _pos(ticker="STP", precio_eur=85.0),
                _pos(ticker="TGT", precio_eur=108.9),
            ),
        )
        ruta = vault_tmp.update_health_status(HealthStatus(), alertas_niveles=niveles)
        texto_nota = ruta.read_text(encoding="utf-8")

        assert "## 🎯 Niveles Alcanzados" in texto_nota
        assert "stops_alcanzados: 1" in texto_nota
        assert "targets_alcanzados: 1" in texto_nota
        # El wikilink debe resolver a la ficha del activo, no al ticker crudo.
        assert "[[STP" in texto_nota

    def test_sin_niveles_no_se_escribe_la_seccion(self, vault_tmp: VaultManager):
        ruta = vault_tmp.update_health_status(HealthStatus())
        assert "Niveles Alcanzados" not in ruta.read_text(encoding="utf-8")
