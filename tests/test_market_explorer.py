"""
Suite del explorador de mercado.

Lo que estos tests protegen es la frontera del módulo: el explorador aporta
convicción cualitativa y NADA más. Los precios, los stops, los objetivos y el
veredicto final siguen saliendo del filtro cuantitativo de siempre, con datos
reales. Si alguien algún día deja que un nivel propuesto por el modelo llegue
a una alerta, estos tests deben romperse.

No se llama a la API en ningún momento: `MarketExplorer` se construye con
`api_key=""` (modo no disponible) o se sustituye por un doble.
"""

import json

import pytest

from sharky.claude_client import CONCLUSION_EXPLORACION
from sharky.config import MAX_POSITION_SIZE_PCT
from sharky.market_explorer import (
    MarketExplorationResult,
    MarketExplorer,
    OpportunityCandidate,
    WEB_SEARCH_BASICO,
    WEB_SEARCH_DINAMICO,
    tipo_web_search,
)
from sharky.models import PriceSource
from sharky.opportunity_detector import CONVICCION_MINIMA, OpportunityDetector
from sharky.vault_manager import VaultManager

from conftest import FakeMarket


TECNICOS_BUENOS = {
    # 25% por debajo del máximo con la tendencia intacta y poca volatilidad:
    # asimetría de sobra para superar el R:R mínimo.
    "XYZ": {
        "precio": 750.0, "max_52s": 1000.0, "min_52s": 700.0, "sma_200": 740.0,
        "vol_diaria": 0.008, "caida_desde_max_pct": 25.0, "sobre_sma200_pct": 1.35,
    }
}

INFORME = f"""## XYZ — Ejemplo Industrial S.A.

Fabrica una pieza que nadie más sabe fabricar.

## {CONCLUSION_EXPLORACION}

- El tema de fondo es la electrificación.
- XYZ es el candidato más sólido.

```json
{{"candidatos": [{{"ticker": "XYZ", "simbolo_yahoo": "XYZ.DE", "empresa": "Ejemplo Industrial S.A.", "sector": "Industria", "conviccion": 9, "max_cartera": 6.0, "tesis": "Foso industrial real.", "catalizadores": ["Pedidos récord"], "riesgos": ["Ciclo de capex"]}}]}}
```
"""


def _resultado(texto: str = INFORME) -> MarketExplorationResult:
    candidatos, aviso = MarketExplorer._extraer_candidatos(texto, 8)
    return MarketExplorationResult(
        texto=MarketExplorer._sin_bloque_json(texto),
        candidatos=candidatos,
        fuentes=["[Fuente](https://ejemplo.test/noticia)"],
        modelo="claude-opus-5",
        busquedas_realizadas=7,
        aviso_parseo=aviso,
    )


# ======================================================================
# Disponibilidad
# ======================================================================
class TestDisponibilidad:
    def test_sin_api_no_inventa_una_exploracion(self):
        """Igual que el escaneo semanal: no hay prosa de plantilla que valga.

        Un informe de oportunidades simulado es indistinguible de uno real
        para quien lo lee, y aquí lo que está en juego es una decisión de
        compra. Sin API, el explorador lo declara y no propone nada.
        """
        explorador = MarketExplorer(api_key="")
        assert explorador.is_live is False

        res = explorador.explore(ya_cubierto=["NVDA"])
        assert res.disponible is False
        assert res.candidatos == []
        assert res.error == "sin API en vivo"

    def test_el_tipo_de_busqueda_se_deriva_del_modelo(self):
        """Un modelo antiguo rechaza la variante con filtrado dinámico."""
        assert tipo_web_search("claude-opus-5") == WEB_SEARCH_DINAMICO
        assert tipo_web_search("claude-sonnet-5") == WEB_SEARCH_DINAMICO
        assert tipo_web_search("claude-haiku-4-5") == WEB_SEARCH_BASICO


# ======================================================================
# Lectura de candidatos
# ======================================================================
class TestParseo:
    def test_lee_el_bloque_json_final(self):
        candidatos, aviso = MarketExplorer._extraer_candidatos(INFORME, 8)
        assert aviso is None
        assert len(candidatos) == 1
        c = candidatos[0]
        assert c.ticker == "XYZ"
        assert c.simbolo == "XYZ.DE"
        assert c.conviccion == 9
        assert c.catalizadores == ["Pedidos récord"]

    def test_el_informe_guardado_no_repite_el_bloque_json(self):
        """El JSON ya viaja como datos: en la nota sólo estorba."""
        limpio = MarketExplorer._sin_bloque_json(INFORME)
        assert "```json" not in limpio
        assert "Fabrica una pieza" in limpio

    def test_sin_bloque_json_el_informe_sigue_valiendo(self):
        candidatos, aviso = MarketExplorer._extraer_candidatos("Sólo prosa.", 8)
        assert candidatos == []
        assert "no incluía el bloque" in aviso

    def test_json_invalido_se_declara_en_vez_de_romper(self):
        texto = "Informe.\n\n```json\n{no es json}\n```\n"
        candidatos, aviso = MarketExplorer._extraer_candidatos(texto, 8)
        assert candidatos == []
        assert "no era JSON válido" in aviso

    def test_respeta_el_tope_de_candidatos(self):
        muchos = json.dumps({
            "candidatos": [{"ticker": f"T{i}", "empresa": f"E{i}"} for i in range(20)]
        })
        candidatos, _ = MarketExplorer._extraer_candidatos(f"```json\n{muchos}\n```", 3)
        assert len(candidatos) == 3

    def test_descarta_tickers_repetidos(self):
        repetido = json.dumps({
            "candidatos": [{"ticker": "AAA"}, {"ticker": "aaa"}, {"ticker": "BBB"}]
        })
        candidatos, _ = MarketExplorer._extraer_candidatos(f"```json\n{repetido}\n```", 8)
        assert [c.ticker for c in candidatos] == ["AAA", "BBB"]

    def test_el_peso_propuesto_no_puede_exceder_el_mandato(self):
        """El modelo escribe `max_cartera`: se acota antes de creerle.

        Una alerta que pidiera un 15% contradiría las reglas de supervivencia
        desde el propio texto de la nota, aunque el RiskGovernor la recortara
        después al dimensionar.
        """
        c = OpportunityCandidate(ticker="AAA", max_cartera=40.0)
        assert c.max_cartera == MAX_POSITION_SIZE_PCT

    def test_el_candidato_no_tiene_donde_guardar_un_precio(self):
        """La frontera del módulo, escrita como test.

        Si alguien añade `stop_loss` o `target_precio` a `OpportunityCandidate`,
        habrá dejado que un nivel inventado por un modelo entre en la bóveda
        con el mismo aspecto que uno medido.
        """
        campos = set(OpportunityCandidate.model_fields)
        assert not campos & {"precio", "precio_actual", "stop_loss", "target_precio", "ratio_rr"}


# ======================================================================
# Los candidatos pasan por el filtro de siempre
# ======================================================================
class TestFiltroCuantitativo:
    def test_un_candidato_con_asimetria_se_convierte_en_alerta(self):
        market = FakeMarket({"XYZ.DE": (750.0, "EUR")}, tecnicos=TECNICOS_BUENOS)
        detector = OpportunityDetector(market=market)
        candidato = _resultado().candidatos[0]

        alertas = detector.scan_universe(
            {candidato.ticker: candidato.perfil()},
            {candidato.ticker: market.get_snapshot("XYZ", symbol="XYZ.DE")},
            simbolos={candidato.ticker: candidato.simbolo},
        )

        assert len(alertas) == 1
        a = alertas[0]
        assert a.ticker == "XYZ"
        assert a.ratio_rr >= 2.8
        # Los niveles los pone el filtro, no el modelo.
        assert a.stop_loss < a.precio_actual < a.target_precio
        assert a.target_precio == pytest.approx(1000.0)

    def test_un_candidato_sin_datos_no_emite_alerta(self):
        """El modelo puede inventarse un símbolo: sin cotización, no hay señal."""
        market = FakeMarket({}, tecnicos={})
        detector = OpportunityDetector(market=market)
        candidato = OpportunityCandidate(ticker="FAKE", simbolo="NO.EXISTE", conviccion=9)

        alertas = detector.scan_universe(
            {"FAKE": candidato.perfil()}, {},
            simbolos={"FAKE": candidato.simbolo},
        )
        assert alertas == []
        assert detector.ultimo_diagnostico[0]["veredicto"] == "SIN DATOS"

    def test_una_tesis_excelente_con_mal_precio_no_pasa(self):
        """El resultado normal y deseable: buena empresa, precio de hoy no.

        El explorador propone por convicción; el precio decide. Que no salga
        alerta no es un fallo del explorador.
        """
        tecnicos = {
            "XYZ": {
                "precio": 990.0, "max_52s": 1000.0, "min_52s": 800.0, "sma_200": 900.0,
                "vol_diaria": 0.02, "caida_desde_max_pct": 1.0, "sobre_sma200_pct": 10.0,
            }
        }
        market = FakeMarket({"XYZ": (990.0, "EUR")}, tecnicos=tecnicos)
        detector = OpportunityDetector(market=market)

        alertas = detector.scan_universe(
            {"XYZ": OpportunityCandidate(ticker="XYZ", conviccion=10).perfil()},
            market.get_batch_snapshots(["XYZ"]),
        )
        assert alertas == []
        assert detector.ultimo_diagnostico[0]["veredicto"] == "NO CUALIFICA"

    def test_un_precio_no_fiable_tampoco_pasa(self):
        market = FakeMarket(
            {"XYZ": (750.0, "EUR")}, tecnicos=TECNICOS_BUENOS,
            fuente=PriceSource.SIMULADO,
        )
        detector = OpportunityDetector(market=market)
        alertas = detector.scan_universe(
            {"XYZ": OpportunityCandidate(ticker="XYZ", conviccion=9).perfil()},
            market.get_batch_snapshots(["XYZ"]),
        )
        assert alertas == []

    def test_la_conviccion_minima_se_sigue_aplicando(self):
        """Venir de un modelo caro no exime del listón de convicción."""
        market = FakeMarket({"XYZ": (750.0, "EUR")}, tecnicos=TECNICOS_BUENOS)
        detector = OpportunityDetector(market=market)
        flojo = OpportunityCandidate(ticker="XYZ", conviccion=CONVICCION_MINIMA - 1)

        assert detector.scan_universe(
            {"XYZ": flojo.perfil()}, market.get_batch_snapshots(["XYZ"])
        ) == []
        assert detector.ultimo_diagnostico[0]["veredicto"] == "DESCARTADO"

    def test_el_universo_curado_sigue_funcionando_igual(self):
        """`scan_for_opportunities` delega en `scan_universe` sin cambiar nada."""
        market = FakeMarket(
            {"ASML": (750.0, "USD")},
            tecnicos={"ASML": dict(TECNICOS_BUENOS["XYZ"])},
        )
        detector = OpportunityDetector(market=market)
        alertas = detector.scan_for_opportunities(market.get_batch_snapshots(["ASML"]))
        assert [a.ticker for a in alertas] == ["ASML"]


# ======================================================================
# La nota de la bóveda
# ======================================================================
class TestInformeEnLaBoveda:
    def _diagnostico(self):
        return [
            {"ticker": "XYZ", "veredicto": "ALERTA", "detalle": "asimetría confirmada"},
            {"ticker": "ABC", "veredicto": "NO CUALIFICA", "detalle": "no hay descuento"},
        ]

    def test_escribe_la_nota_con_frontmatter_utilizable(self, vault_tmp: VaultManager):
        ruta = vault_tmp.write_market_exploration(
            "2026-09-20", _resultado(), self._diagnostico(), []
        )
        meta, cuerpo = vault_tmp.parse_markdown(ruta.read_text(encoding="utf-8"))

        assert meta["tipo"] == "exploracion_mercado"
        assert meta["fecha"] == "2026-09-20"
        assert meta["modelo"] == "claude-opus-5"
        assert meta["candidatos_propuestos"] == 1
        assert meta["alertas_emitidas"] == 0
        assert meta["tickers_propuestos"] == ["XYZ"]
        assert "electrificación" in meta["conclusion_exploracion"]
        assert "Ejemplo Industrial" in cuerpo

    def test_el_veredicto_de_cada_candidato_queda_escrito(self, vault_tmp: VaultManager):
        """Sin esta tabla, una exploración sin alertas parece un fallo."""
        ruta = vault_tmp.write_market_exploration(
            "2026-09-20", _resultado(), self._diagnostico(), []
        )
        texto = ruta.read_text(encoding="utf-8")

        assert "## 2. Veredicto Cuantitativo" in texto
        assert "NO CUALIFICA" in texto and "no hay descuento" in texto
        assert "no se ha emitido ninguna alerta" in texto

    def test_declara_cuando_no_pudo_leer_los_candidatos(self, vault_tmp: VaultManager):
        ruta = vault_tmp.write_market_exploration(
            "2026-09-20", _resultado("Informe sin bloque de datos."), [], []
        )
        texto = ruta.read_text(encoding="utf-8")
        assert "[!WARNING]" in texto
        assert "no incluía el bloque" in texto

    def test_declara_cuando_no_hubo_exploracion(self, vault_tmp: VaultManager):
        res = MarketExplorationResult(
            disponible=False, texto="_Sin API._", error="sin API en vivo"
        )
        ruta = vault_tmp.write_market_exploration("2026-09-20", res, [], [])
        texto = ruta.read_text(encoding="utf-8")
        assert "Exploración no disponible" in texto
        assert "ANTHROPIC_API_KEY" in texto

    def test_la_ultima_exploracion_se_puede_releer(self, vault_tmp: VaultManager):
        vault_tmp.write_market_exploration("2026-09-13", _resultado(), [], [])
        vault_tmp.write_market_exploration("2026-09-20", _resultado(), [], [])

        ultima = vault_tmp.leer_ultima_exploracion()
        assert ultima is not None
        assert ultima["fecha"].isoformat() == "2026-09-20"
        assert ultima["candidatos"] == 1
        assert ultima["id"].startswith("09_Alertas_Oportunidades/Exploraciones/")

    def test_sin_exploraciones_devuelve_none(self, vault_tmp: VaultManager):
        assert vault_tmp.leer_ultima_exploracion() is None
