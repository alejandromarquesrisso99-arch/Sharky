"""
Suite del núcleo de Sharky Capital Management.

Cubre los invariantes que la versión anterior violaba:
  * el PnL nunca mezcla divisas;
  * el drawdown se mide contra el máximo histórico;
  * los umbrales de estado vital son los del mandato escrito en la bóveda;
  * las ventas no se bloquean cuando la cartera está herida;
  * ninguna cifra procede de datos simulados sin declararlo.
"""

from datetime import date, datetime, timedelta

import pytest

from sharky.agent_loop import SharkyAgent
from sharky.claude_client import ClaudeBrainClient
from sharky.config import (
    BREACH_ESCALATION_DAYS,
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
)
from sharky.fx import FxProvider
from sharky.models import (
    ExecutionMode,
    HealthStatus,
    OpportunityAlert,
    OrderType,
    Portfolio,
    Position,
    PriceSource,
    RebalanceAction,
    TradeOrder,
    VitalState,
)
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

    def test_modo_paper_marca_la_operacion(self, tmp_path, store_tmp, market_simple):
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=1.0, precio=100.0,
            modo=ExecutionMode.PAPER_TRADING,
        )
        assert res.orden.modo == ExecutionMode.PAPER_TRADING
        assert "PAPER_TRADING" in res.nota_operacion


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
        h = HealthStatus(ultima_actualizacion=datetime.now())
        assert SharkyAgent._dias_desde_ultimo_ciclo(h) == 0.0

    def test_ayer_es_un_dia(self):
        h = HealthStatus(ultima_actualizacion=datetime.now() - timedelta(days=1))
        assert SharkyAgent._dias_desde_ultimo_ciclo(h) == pytest.approx(1.0)

    def test_una_bovedad_nunca_actualizada_no_cuenta_como_hoy(self):
        """`datetime.min` (bóveda nueva o esquema ilegible) no debe leerse
        como "hace cero días": bloquearía para siempre el primer ciclo."""
        h = HealthStatus(ultima_actualizacion=datetime.min)
        assert SharkyAgent._dias_desde_ultimo_ciclo(h) > 0


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
        assert "MAX_TOKENS_INFORME" in resultado.error

    def test_respuesta_vacia_cae_al_fallback_con_diagnostico(self):
        cliente = self._cliente_con_respuesta_falsa(_RespuestaFalsa([], stop_reason="end_turn"))
        resultado = cliente._invocar("prompt", fallback="plantilla")

        assert resultado.simulado is True
        assert "(vacío)" in resultado.error
