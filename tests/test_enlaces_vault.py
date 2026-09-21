"""
Higiene de los enlaces de la bóveda, en el punto de escritura.

`test_obsidian_graph_integrity` comprueba la bóveda real, pero sólo después de
que algo la haya escrito. Estuvo en rojo desde 2026-09 por dos motivos que se
repetían en cada ciclo: el texto de Claude enlaza por ticker (`[[RHM]]`) y las
fichas no siempre se llaman así (`Rheinmetall`), y ninguna ficha ni nota de
sector se creaba sola al abrir una posición o emitir una alerta. Estos tests
fijan el comportamiento con una bóveda temporal.
"""

from sharky.models import (
    HealthStatus,
    OpportunityAlert,
    OrderType,
    Portfolio,
)
from sharky.portfolio import PortfolioStore, PortfolioValuator
from sharky.risk_governor import RiskGovernor
from sharky.trade_ledger import TradeRecorder
from sharky.vault_manager import VaultManager

from conftest import FakeFx, FakeMarket


def _ficha(vm: VaultManager, nombre: str, ticker: str, aliases=()) -> None:
    meta = {"ticker": ticker}
    if aliases:
        meta["aliases"] = list(aliases)
    ruta = vm.vault_path / "03_Activos" / "Empresas" / f"{nombre}.md"
    ruta.write_text(vm.build_markdown(meta, f"# {nombre}\n"), encoding="utf-8")


def _alerta(ticker: str = "LDO") -> OpportunityAlert:
    return OpportunityAlert(
        id_alerta=f"ALT-20260906-{ticker}",
        ticker=ticker,
        empresa="Leonardo S.p.A.",
        fecha_deteccion="2026-09-06",
        conviccion=8,
        precio_actual=40.0,
        divisa="EUR",
        entrada_sugerida=40.0,
        stop_loss=36.0,
        target_precio=50.0,
        ratio_rr=2.8,
        potencial_ganancia_pct=25.0,
        riesgo_maximo_pct=10.0,
        descripcion_oportunidad="Complementa a [[RHM]] en defensa europea.",
        catalizadores=["Pedidos récord"],
        riesgos=["Ciclo presupuestario"],
        pct_max_cartera=5.0,
    )


def _recorder(tmp_path, market: FakeMarket) -> TradeRecorder:
    store = PortfolioStore(tmp_path)
    store.save(Portfolio(efectivo_eur=50000.0, posiciones=[]))
    return TradeRecorder(
        store=store,
        valuator=PortfolioValuator(market=market, fx=FakeFx()),
        governor=RiskGovernor(),
        vault=VaultManager(tmp_path),
        fx=FakeFx(),
        market=market,
    )


# ======================================================================
# normalizar_enlaces
# ======================================================================
class TestNormalizarEnlaces:
    def test_un_ticker_con_ficha_apunta_a_ella_y_se_lee_igual(self, vault_tmp):
        _ficha(vault_tmp, "Rheinmetall", "RHM")
        assert (
            vault_tmp.normalizar_enlaces("Liquidar [[RHM]] hoy.")
            == "Liquidar [[Rheinmetall|RHM]] hoy."
        )

    def test_dentro_de_una_tabla_escapa_el_pipe(self, vault_tmp):
        """Sin escapar, el `|` del alias parte la celda en dos columnas."""
        _ficha(vault_tmp, "Rheinmetall", "RHM")
        assert (
            vault_tmp.normalizar_enlaces("| [[RHM]] | 16% |")
            == "| [[Rheinmetall\\|RHM]] | 16% |"
        )
        assert (
            vault_tmp.normalizar_enlaces("> | [[RHM]] | 16% |")
            == "> | [[Rheinmetall\\|RHM]] | 16% |"
        )

    def test_respeta_el_alias_que_ya_traia(self, vault_tmp):
        _ficha(vault_tmp, "Rheinmetall", "RHM")
        assert (
            vault_tmp.normalizar_enlaces("[[RHM|la alemana]]")
            == "[[Rheinmetall|la alemana]]"
        )

    def test_resuelve_tambien_por_los_aliases_de_la_ficha(self, vault_tmp):
        """Un ticker que ya no está en cartera sigue llevando a su ficha."""
        _ficha(vault_tmp, "Uranio", "URNU", aliases=["Uranium"])
        assert vault_tmp.normalizar_enlaces("[[URNU]]") == "[[Uranio|URNU]]"
        assert vault_tmp.normalizar_enlaces("[[Uranium]]") == "[[Uranio|Uranium]]"

    def test_lo_que_no_resuelve_queda_en_texto_plano(self, vault_tmp):
        assert (
            vault_tmp.normalizar_enlaces("[[CRWD]] +14% y [[MP|MP Materials]]")
            == "CRWD +14% y MP Materials"
        )

    def test_no_toca_lo_que_ya_resuelve_ni_embebidos_ni_plantillas(self, vault_tmp):
        _ficha(vault_tmp, "MSFT", "MSFT")
        texto = "[[MSFT]] [[MSFT#Métricas|métricas]] ![[grafico.png]] [[{{TICKER}}]]"
        assert vault_tmp.normalizar_enlaces(texto) == texto

    def test_aplicarlo_dos_veces_no_cambia_nada(self, vault_tmp):
        _ficha(vault_tmp, "Rheinmetall", "RHM")
        una = vault_tmp.normalizar_enlaces("| [[RHM]] |\n[[RHM]] y [[ZZZ]]")
        assert vault_tmp.normalizar_enlaces(una) == una


# ======================================================================
# Lo que redacta Claude
# ======================================================================
class TestTextoDelModelo:
    def test_el_diario_guarda_los_enlaces_ya_resueltos(self, vault_tmp):
        _ficha(vault_tmp, "Rheinmetall", "RHM")

        ruta = vault_tmp.write_daily_journal(
            "2026-09-21",
            "Stop roto en [[RHM]].",
            HealthStatus(),
            conclusion="Liquidar [[RHM]] y vigilar [[ZZZ]].",
        )

        texto = ruta.read_text(encoding="utf-8")
        assert "[[RHM]]" not in texto
        assert "Stop roto en [[Rheinmetall|RHM]]." in texto
        # La conclusión vive en el frontmatter y la relee el escaneo semanal.
        meta, _ = vault_tmp.parse_markdown(texto)
        assert meta["conclusion_ia"] == "Liquidar [[Rheinmetall|RHM]] y vigilar ZZZ."


# ======================================================================
# Fichas y sectores que faltan
# ======================================================================
class TestFichasYSectores:
    def test_una_alerta_nueva_crea_la_ficha_de_su_activo(self, vault_tmp):
        ruta_alerta = vault_tmp.write_opportunity_alert(_alerta("LDO"))

        ficha = vault_tmp.vault_path / "03_Activos" / "Empresas" / "LDO.md"
        assert ficha.exists()
        # Enlazadas en los dos sentidos.
        assert f"[[{ruta_alerta.stem}]]" in ficha.read_text(encoding="utf-8")
        assert "[[LDO]]" in ruta_alerta.read_text(encoding="utf-8")

    def test_no_duplica_una_ficha_que_existe_con_otro_nombre(self, vault_tmp):
        _ficha(vault_tmp, "Rheinmetall", "RHM")

        assert vault_tmp.asegurar_ficha("RHM", "Rheinmetall AG") is None
        assert not (vault_tmp.vault_path / "03_Activos" / "Empresas" / "RHM.md").exists()

    def test_la_ficha_crea_su_sector_y_repetir_no_hace_nada(self, vault_tmp):
        assert vault_tmp.asegurar_ficha("KRKN", "Kraken", "Defensa_Naval") is not None
        assert (vault_tmp.vault_path / "03_Activos" / "Sectores" / "Defensa_Naval.md").exists()

        assert vault_tmp.asegurar_ficha("KRKN", "Kraken", "Defensa_Naval") is None
        assert vault_tmp.asegurar_sector("Defensa_Naval") is None

    def test_las_notas_creadas_enlazan_hacia_fuera(self, vault_tmp):
        """El test del grafo rechaza los callejones sin salida igual que los
        enlaces rotos: una nota creada sola tiene que enlazar a algo."""
        ficha = vault_tmp.asegurar_ficha("KRKN", "Kraken", "Defensa_Naval")
        sector = vault_tmp.vault_path / "03_Activos" / "Sectores" / "Defensa_Naval.md"

        for ruta in (ficha, sector):
            texto = ruta.read_text(encoding="utf-8")
            assert "[[03_Activos]]" in texto
            assert "[[Reglas_De_Supervivencia]]" in texto

    def test_la_ficha_enlaza_la_tesis_si_ya_existe(self, vault_tmp):
        (vault_tmp.vault_path / "01_Tesis_Activas" / "Tesis_INDRA.md").write_text(
            "---\nticker: INDRA\nestado: Activa\n---\n\n# Tesis\n", encoding="utf-8"
        )

        ruta = vault_tmp.asegurar_ficha("INDRA", "Indra Sistemas", "Defensa")

        assert "[[Tesis_INDRA]]" in ruta.read_text(encoding="utf-8")

    def test_una_tesis_abierta_desde_una_alerta_no_deja_enlaces_rotos(self, vault_tmp):
        alerta = _alerta("OHB")
        vault_tmp.write_opportunity_alert(alerta)

        ruta = vault_tmp.crear_tesis_desde_alerta(
            alerta, "2026-09-21", precio_entrada=40.0, sector="Espacio"
        )

        texto = ruta.read_text(encoding="utf-8")
        existentes = vault_tmp._notas_existentes()
        for destino in ("OHB", "Espacio", "2026-09-06_ALERTA_ALT-20260906-OHB"):
            assert f"[[{destino}]]" in texto
            assert destino in existentes
        # `level_watch` es código, no una nota de la bóveda.
        assert "[[level_watch]]" not in texto


# ======================================================================
# Operaciones
# ======================================================================
class TestOperaciones:
    def test_abrir_una_posicion_crea_su_ficha_y_su_sector(self, tmp_path):
        recorder = _recorder(tmp_path, FakeMarket({"MSFT": (442.0, "USD")}))

        res = recorder.record(
            ticker="MSFT", tipo_orden=OrderType.COMPRA, unidades=1.0, precio=442.0,
            divisa="USD", stop_loss=400.0, target_precio=560.0, nombre="Microsoft",
            sector="Cloud_Software", ticker_cotizacion="MSFT",
            # Lo que se prueba es la ficha, no el gobernador.
            forzar=True,
        )

        assert res.aprobada, res.motivo
        assert (tmp_path / "03_Activos" / "Empresas" / "MSFT.md").exists()
        assert (tmp_path / "03_Activos" / "Sectores" / "Cloud_Software.md").exists()
        assert recorder.store.load().get("MSFT").nota_activo == "[[MSFT]]"

    def test_recomprar_un_ticker_con_ficha_usa_la_que_ya_tiene(self, tmp_path):
        recorder = _recorder(tmp_path, FakeMarket({"NOK": (4.0, "EUR")}))
        _ficha(recorder.vault, "Nokia", "NOK")

        res = recorder.record(
            ticker="NOK", tipo_orden=OrderType.COMPRA, unidades=10.0, precio=4.0,
            divisa="EUR", stop_loss=3.6, target_precio=5.2, nombre="Nokia Oyj",
            sector="Telecomunicaciones", ticker_cotizacion="NOKIA.HE", forzar=True,
        )

        assert res.aprobada, res.motivo
        assert recorder.store.load().get("NOK").nota_activo == "[[Nokia]]"
        assert not (tmp_path / "03_Activos" / "Empresas" / "NOK.md").exists()
