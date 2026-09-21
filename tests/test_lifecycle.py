"""
Ciclo de vida de una tesis y de una alerta.

Una tesis nace de una alerta ejecutada y muere en la venta que cierra la
posición. Hasta 2026-09 no hacía ninguna de las dos cosas sola, y las tres
omisiones tenían consecuencias reales:

  * Una alerta nunca caducaba: su ticker quedaba vetado para siempre en
    `has_active_alert` y sus niveles congelados seguían entrando cada mes en
    el rebalanceo mientras el motor tomaba precio fresco.
  * Comprar desde una alerta no creaba tesis: la posición recién abierta no
    tenía ningún stop que `level_watch` pudiera vigilar.
  * Vender no cerraba la tesis, y una tesis activa sin posición es justo la
    condición que la convierte en candidata de COMPRA -- así que vender por
    stop dejaba al motor proponiendo recomprarla el Día 1 siguiente.

El último es el que más caro sale, y tiene su propio test al final.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from sharky.models import (
    AlertStatus,
    HealthStatus,
    MarketSnapshot,
    OpportunityAlert,
    OrderType,
    PriceSource,
)
from sharky.opportunity_detector import alertas_caducadas
from sharky.portfolio import PortfolioValuator
from sharky.rebalance_engine import MonthlyRebalanceEngine
from sharky.risk_governor import RiskGovernor
from sharky.trade_ledger import TradeRecorder
from sharky.vault_manager import VaultManager

from conftest import FakeFx


def _alerta(ticker="ZZZ", fecha="2026-09-01", stop=90.0, target=130.0, divisa="EUR") -> OpportunityAlert:
    return OpportunityAlert(
        id_alerta=f"ALT-{fecha.replace('-', '')}-{ticker}",
        ticker=ticker,
        empresa=f"{ticker} Industrial S.A.",
        fecha_deteccion=fecha,
        conviccion=9,
        precio_actual=100.0,
        divisa=divisa,
        entrada_sugerida=100.0,
        stop_loss=stop,
        target_precio=target,
        ratio_rr=3.0,
        potencial_ganancia_pct=30.0,
        riesgo_maximo_pct=10.0,
        descripcion_oportunidad="Foso industrial defendible.",
        catalizadores=["Pedidos récord", "Capacidad saturada"],
        riesgos=["Ciclo de capex", "Concentración de clientes"],
        pct_max_cartera=6.0,
    )


def _snap(ticker="ZZZ", precio=100.0, divisa="EUR", fuente=PriceSource.MERCADO) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=ticker, precio_actual=precio, divisa=divisa, fuente=fuente
    )


# ======================================================================
# Política de caducidad
# ======================================================================
class TestCaducidadDeAlertas:
    def test_una_alerta_reciente_con_precio_intacto_sigue_viva(self):
        alerta = _alerta(fecha=date.today().isoformat())
        assert alertas_caducadas([alerta], {"ZZZ": _snap()}) == []

    def test_caduca_por_edad(self):
        vieja = (date.today() - timedelta(days=45)).isoformat()
        caducadas = alertas_caducadas([_alerta(fecha=vieja)], {"ZZZ": _snap()})

        assert len(caducadas) == 1
        assert "45 días" in caducadas[0][1]

    def test_caduca_si_el_precio_rompe_su_propio_stop(self):
        """El nivel que la habría sacado ya se cumplió sin haber entrado."""
        alerta = _alerta(fecha=date.today().isoformat(), stop=90.0)
        caducadas = alertas_caducadas([alerta], {"ZZZ": _snap(precio=85.0)})

        assert len(caducadas) == 1
        assert "ha roto el stop" in caducadas[0][1]

    def test_caduca_si_el_objetivo_ya_se_alcanzo(self):
        alerta = _alerta(fecha=date.today().isoformat(), target=130.0)
        caducadas = alertas_caducadas([alerta], {"ZZZ": _snap(precio=135.0)})

        assert len(caducadas) == 1
        assert "no queda recorrido" in caducadas[0][1]

    def test_un_precio_en_otra_divisa_no_decide_nada(self):
        """Comparar un stop en EUR contra un precio en USD es un error de unidades."""
        alerta = _alerta(fecha=date.today().isoformat(), stop=90.0, divisa="EUR")
        assert alertas_caducadas([alerta], {"ZZZ": _snap(precio=50.0, divisa="USD")}) == []

    def test_un_precio_no_fiable_no_decide_nada(self):
        alerta = _alerta(fecha=date.today().isoformat(), stop=90.0)
        snap = _snap(precio=10.0, fuente=PriceSource.SIMULADO)
        assert alertas_caducadas([alerta], {"ZZZ": snap}) == []

    def test_sin_cotizacion_solo_manda_la_edad(self):
        reciente = _alerta(fecha=date.today().isoformat())
        vieja = _alerta(ticker="YYY", fecha=(date.today() - timedelta(days=99)).isoformat())

        caducadas = alertas_caducadas([reciente, vieja], {})
        assert [a.ticker for a, _ in caducadas] == ["YYY"]


# ======================================================================
# Escritura del cierre de una alerta
# ======================================================================
class TestCierreDeAlerta:
    def test_una_alerta_marcada_deja_de_estar_activa(self, vault_tmp: VaultManager):
        alerta = _alerta()
        vault_tmp.write_opportunity_alert(alerta)
        assert vault_tmp.has_active_alert("ZZZ") is True

        ruta = vault_tmp.marcar_alerta(
            alerta, AlertStatus.EXPIRADA, "2026-10-01", motivo="Emitida hace mucho."
        )

        assert ruta is not None
        assert vault_tmp.has_active_alert("ZZZ") is False
        assert vault_tmp.list_active_alerts() == []

        meta, cuerpo = vault_tmp.parse_markdown(ruta.read_text(encoding="utf-8"))
        assert meta["estado"] == "EXPIRADA"
        assert str(meta["fecha_cierre_alerta"]) == "2026-10-01"
        # El aviso va arriba: quien abra la nota no puede leer un precio de
        # entrada que ya no sirve sin enterarse antes de que está muerta.
        assert cuerpo.index("EXPIRADA el 2026-10-01") < cuerpo.index("Plan de Entrada")

    def test_el_moc_no_dice_dos_cosas_a_la_vez(self, vault_tmp: VaultManager):
        """Una alerta caducada no puede seguir bajo «Alertas Activas»."""
        moc = vault_tmp.vault_path / "09_Alertas_Oportunidades" / "09_Alertas_Oportunidades.md"
        moc.write_text(
            "# MOC\n\n## 🔥 Alertas Activas en Radar\n\n"
            "## 🗄️ Alertas Caducadas / Histórico\n",
            encoding="utf-8",
        )
        alerta = _alerta()
        ruta = vault_tmp.write_opportunity_alert(alerta)
        assert f"[[{ruta.stem}]]" in moc.read_text(encoding="utf-8")

        vault_tmp.marcar_alerta(alerta, AlertStatus.EXPIRADA, "2026-10-01", motivo="Vieja.")
        texto = moc.read_text(encoding="utf-8")

        activas, historico = texto.split("## 🗄️")
        assert f"[[{ruta.stem}]]" not in activas
        assert f"[[{ruta.stem}]]" in historico

    def test_marcar_una_alerta_inexistente_no_revienta(self, vault_tmp: VaultManager):
        assert vault_tmp.marcar_alerta(_alerta(), AlertStatus.EXPIRADA, "2026-10-01") is None


# ======================================================================
# Apertura y cierre de tesis
# ======================================================================
class TestCicloDeTesis:
    def test_una_alerta_ejecutada_se_convierte_en_tesis(self, vault_tmp: VaultManager):
        alerta = _alerta()
        ruta = vault_tmp.crear_tesis_desde_alerta(
            alerta, fecha_str="2026-10-01", precio_entrada=98.0,
            divisa_entrada="EUR", stop_loss=88.0, target_precio=128.0,
            sector="Industria_Europea", id_operacion="OP-TEST",
        )

        tesis = {t.ticker: t for _, t in vault_tmp.list_active_theses()}
        assert "ZZZ" in tesis
        t = tesis["ZZZ"]
        # Mandan los niveles de la ORDEN, no los de la alerta.
        assert t.precio_entrada == pytest.approx(98.0)
        assert t.stop_loss == pytest.approx(88.0)
        assert t.target_precio == pytest.approx(128.0)
        assert t.conviccion == 9
        assert "OP-TEST" in ruta.read_text(encoding="utf-8")

    def test_la_tesis_hereda_el_racional_y_no_la_tabla_de_precios(self, vault_tmp: VaultManager):
        """Copiar el cuerpo entero arrastraría niveles ya caducados."""
        alerta = _alerta()
        vault_tmp.write_opportunity_alert(alerta)
        leida = vault_tmp.list_active_alerts()[0][1]

        ruta = vault_tmp.crear_tesis_desde_alerta(
            leida, fecha_str="2026-10-01", precio_entrada=98.0, divisa_entrada="EUR"
        )
        texto = ruta.read_text(encoding="utf-8")

        assert "Foso industrial defendible." in texto
        assert "Pedidos récord" in texto
        assert "Ciclo de capex" in texto
        assert "Zona de Entrada" not in texto

    def test_vender_archiva_la_tesis_sin_borrar_nada(self, vault_tmp: VaultManager):
        alerta = _alerta()
        vault_tmp.crear_tesis_desde_alerta(
            alerta, fecha_str="2026-10-01", precio_entrada=100.0, divisa_entrada="EUR"
        )

        destino = vault_tmp.cerrar_tesis(
            "ZZZ", fecha_str="2026-11-15", pnl_realizado_eur=-120.5,
            motivo="Stop-loss alcanzado.", precio_salida=88.0, divisa="EUR",
        )

        assert destino is not None
        assert destino.parent.name == "02_Tesis_Cerradas"
        assert vault_tmp.buscar_tesis("ZZZ") is None
        assert vault_tmp.list_active_theses() == []

        meta, cuerpo = vault_tmp.parse_markdown(destino.read_text(encoding="utf-8"))
        assert meta["estado"] == "Cerrada"
        assert str(meta["fecha_cierre"]) == "2026-11-15"
        assert meta["pnl_realizado_eur"] == pytest.approx(-120.5)
        # El racional original sobrevive al cierre: es el material del post-mortem.
        assert "Foso industrial defendible." in cuerpo
        assert "Stop-loss alcanzado." in cuerpo
        assert "-120.50 €" in cuerpo or "-120,50 €" in cuerpo

    def test_cerrar_una_tesis_inexistente_devuelve_none(self, vault_tmp: VaultManager):
        """Una posición sin tesis documentada es legítima y no rompe la venta."""
        assert vault_tmp.cerrar_tesis("NO_EXISTE", "2026-11-15") is None


# ======================================================================
# El ciclo completo a través del registro de operaciones
# ======================================================================
class TestCicloEnElRegistro:
    def _recorder(self, tmp_path, store, market):
        return TradeRecorder(
            store=store,
            valuator=PortfolioValuator(market=market, fx=FakeFx()),
            governor=RiskGovernor(),
            vault=VaultManager(tmp_path),
            fx=FakeFx(),
            market=market,
        )

    def _vault_con_alerta(self, tmp_path) -> VaultManager:
        vault = VaultManager(tmp_path)
        vault.write_opportunity_alert(_alerta(ticker="AAA", stop=85.0, target=130.0))
        return vault

    def test_comprar_desde_una_alerta_abre_tesis_y_consume_la_alerta(
        self, tmp_path: Path, store_tmp, market_simple
    ):
        vault = self._vault_con_alerta(tmp_path)
        vault.update_health_status(HealthStatus(capital_inicial_eur=3000.0))
        recorder = self._recorder(tmp_path, store_tmp, market_simple)

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=100.0,
            divisa="EUR", stop_loss=95.0, target_precio=130.0,
            # La cartera de prueba ya tiene AAA al limite de concentracion: lo
            # que se prueba aqui es el ciclo de vida, no el gobernador.
            forzar=True,
        )

        assert res.aprobada, res.motivo
        assert res.tesis_abierta is not None
        assert res.alerta_actualizada is not None

        # La alerta queda consumida, no vetando el ticker para siempre.
        assert vault.has_active_alert("AAA") is False
        # Y la posición ya tiene un stop que `level_watch` puede vigilar.
        tesis = {t.ticker: t for _, t in vault.list_active_theses()}
        assert tesis["AAA"].stop_loss == pytest.approx(95.0)

    def test_no_sobrescribe_una_tesis_escrita_a_mano(
        self, tmp_path: Path, store_tmp, market_simple
    ):
        """La convicción propia manda sobre la heredada de una alerta."""
        vault = self._vault_con_alerta(tmp_path)
        vault.update_health_status(HealthStatus(capital_inicial_eur=3000.0))
        propia = vault.vault_path / "01_Tesis_Activas" / "Tesis_AAA.md"
        propia.write_text(
            "---\nticker: AAA\nempresa: Mía\nestado: Activa\nprecio_entrada: 1.0\n"
            "stop_loss: 0.5\ntarget_precio: 2.0\nconviccion: 4\ndivisa: EUR\n"
            "fecha_apertura: 2026-01-01\n---\n\nRacional escrito a mano.\n",
            encoding="utf-8",
        )
        recorder = self._recorder(tmp_path, store_tmp, market_simple)

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=100.0,
            divisa="EUR", stop_loss=95.0, target_precio=130.0, forzar=True,
        )

        assert res.aprobada, res.motivo
        assert res.tesis_abierta is None
        assert "Racional escrito a mano." in propia.read_text(encoding="utf-8")
        # La alerta sí se consume: la compra ocurrió igual.
        assert res.alerta_actualizada is not None

    def test_vender_toda_la_posicion_cierra_la_tesis(
        self, tmp_path: Path, store_tmp, market_simple
    ):
        vault = VaultManager(tmp_path)
        vault.update_health_status(HealthStatus(capital_inicial_eur=3000.0))
        vault.crear_tesis_desde_alerta(
            _alerta(ticker="AAA"), fecha_str="2026-10-01",
            precio_entrada=90.0, divisa_entrada="EUR",
        )
        recorder = self._recorder(tmp_path, store_tmp, market_simple)

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=10.0, precio=100.0,
            divisa="EUR",
        )

        assert res.aprobada, res.motivo
        assert res.tesis_cerrada is not None
        assert vault.list_active_theses() == []

    def test_una_venta_parcial_no_cierra_la_tesis(
        self, tmp_path: Path, store_tmp, market_simple
    ):
        """Reducir tamaño no invalida la convicción."""
        vault = VaultManager(tmp_path)
        vault.update_health_status(HealthStatus(capital_inicial_eur=3000.0))
        vault.crear_tesis_desde_alerta(
            _alerta(ticker="AAA"), fecha_str="2026-10-01",
            precio_entrada=90.0, divisa_entrada="EUR",
        )
        recorder = self._recorder(tmp_path, store_tmp, market_simple)

        res = recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=4.0, precio=100.0,
            divisa="EUR",
        )

        assert res.aprobada, res.motivo
        assert res.tesis_cerrada is None
        assert [t.ticker for _, t in vault.list_active_theses()] == ["AAA"]

    def test_vender_por_stop_no_deja_al_motor_proponiendo_recomprar(
        self, tmp_path: Path, store_tmp, market_simple
    ):
        """La regresión que motivó todo esto, escrita como test.

        Antes: vendes por stop -> la tesis sigue activa sin posición -> el Día 1
        siguiente `_candidatos` la propone como COMPRA, con la convicción
        intacta y unos niveles que el mercado acaba de demostrar falsos.
        """
        vault = VaultManager(tmp_path)
        vault.update_health_status(HealthStatus(capital_inicial_eur=3000.0))
        vault.crear_tesis_desde_alerta(
            _alerta(ticker="AAA"), fecha_str="2026-10-01",
            precio_entrada=90.0, divisa_entrada="EUR",
        )
        recorder = self._recorder(tmp_path, store_tmp, market_simple)
        recorder.record(
            ticker="AAA", tipo_orden=OrderType.VENTA, unidades=10.0, precio=100.0,
            divisa="EUR",
        )

        motor = MonthlyRebalanceEngine(
            market=market_simple, governor=RiskGovernor(), fx=FakeFx()
        )
        candidatos = motor._candidatos(
            vault.list_active_theses(), [a for _, a in vault.list_active_alerts()], {}
        )

        assert "AAA" not in [c["ticker"] for c in candidatos]


# ======================================================================
# El comité ve las tesis, no su recuento
# ======================================================================
class TestComiteVeLasTesis:
    def test_el_dossier_incluye_cada_tesis(self, vault_tmp: VaultManager):
        from sharky.firm_committee import InvestmentCommittee

        vault_tmp.crear_tesis_desde_alerta(
            _alerta(ticker="AAA"), fecha_str="2026-10-01",
            precio_entrada=90.0, divisa_entrada="EUR",
        )
        theses = [t for _, t in vault_tmp.list_active_theses()]
        bloque = InvestmentCommittee._bloque_tesis(theses)

        assert "AAA" in bloque
        assert "convicción 9/10" in bloque

    def test_sin_tesis_lo_dice(self):
        from sharky.firm_committee import InvestmentCommittee

        assert "Sin tesis activas" in InvestmentCommittee._bloque_tesis([])
