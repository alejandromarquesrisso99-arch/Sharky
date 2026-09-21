"""
App de gestión (`sharky.app`): renderizado de notas, acceso a la bóveda y
seguridad del servidor local.

No se levanta un `SharkyAgent` real (tocaría red vía yfinance/Anthropic):
el servidor recibe un agente mínimo con sólo la bóveda.
"""

import http.client
import json
import threading

import pytest

from sharky.app import datos
from sharky.app.servidor import EstadoApp, crear_servidor
from sharky.app.trabajos import ACCIONES, GestorTrabajos, OcupadoError


# ======================================================================
# Renderizado de notas
# ======================================================================
class TestRenderizarMarkdown:
    def test_wikilinks_con_alias_escapado_de_tabla(self):
        html = datos.renderizar_markdown("| a |\n|---|\n| [[Rheinmetall\\|RHM]] |")
        assert '<a href="#" class="wikilink" data-nota="Rheinmetall">RHM</a>' in html

    def test_wikilink_simple_y_con_seccion(self):
        html = datos.renderizar_markdown("Ver [[Estado_Vital]] y [[Mandato#Límites|límites]].")
        assert 'data-nota="Estado_Vital">Estado_Vital</a>' in html
        assert 'data-nota="Mandato">límites</a>' in html

    def test_callout_de_obsidian(self):
        html = datos.renderizar_markdown("> [!WARNING]\n> Cuidado.")
        assert 'class="callout callout-warning"' in html
        assert "[!WARNING]" not in html

    def test_html_crudo_se_escapa(self):
        """Una nota con HTML no puede inyectar scripts en la app."""
        html = datos.renderizar_markdown('<script>alert(1)</script>\n\n<img src=x onerror="x()">')
        assert "<script>" not in html and "<img" not in html

    def test_alineacion_de_tablas_como_clase(self):
        """La CSP bloquea `style=""`: la alineación va por clase."""
        html = datos.renderizar_markdown("| a | b |\n|---|--:|\n| 1 | 2 |")
        assert 'class="al-right"' in html
        assert "style=" not in html


# ======================================================================
# Acceso a la bóveda
# ======================================================================
class TestAccesoBoveda:
    def test_no_se_lee_nada_fuera_de_la_boveda(self, vault_tmp):
        (vault_tmp.vault_path.parent / "secreto.md").write_text("clave", encoding="utf-8")
        for ruta in ("../secreto.md", "../../.env", "C:/Windows/win.ini"):
            with pytest.raises(ValueError):
                datos.leer_nota(vault_tmp, ruta)

    def test_solo_notas_markdown(self, vault_tmp):
        (vault_tmp.vault_path / "datos.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            datos.leer_nota(vault_tmp, "datos.json")

    def test_buscar_nota_rechaza_rutas_y_comodines(self, vault_tmp):
        (vault_tmp.vault_path / "03_Activos").mkdir(exist_ok=True)
        (vault_tmp.vault_path / "03_Activos" / "Rheinmetall.md").write_text("# RHM", encoding="utf-8")
        assert datos.buscar_nota(vault_tmp, "Rheinmetall") == "03_Activos/Rheinmetall.md"
        for nombre in ("*", "../x", "Rhein*", "[R]heinmetall", ""):
            assert datos.buscar_nota(vault_tmp, nombre) is None

    def test_listado_excluye_el_moc_y_ordena_de_mas_reciente(self, vault_tmp):
        from sharky.models import HealthStatus

        carpeta = vault_tmp.vault_path / "05_Diario_Reflexion"
        (carpeta / "05_Diario_Reflexion.md").write_text("# MOC", encoding="utf-8")
        vault_tmp.write_daily_journal("2026-09-17", "Uno.", HealthStatus())
        vault_tmp.write_daily_journal("2026-09-18", "Dos.", HealthStatus(), posiciones_a_vigilar=["AAA"])

        notas = datos.listar_informes(vault_tmp, "diario")

        assert [n["id"] for n in notas] == [
            "05_Diario_Reflexion/2026-09-18_Cierre_Mercado.md",
            "05_Diario_Reflexion/2026-09-17_Cierre_Mercado.md",
        ]
        assert {"texto": "Vigilar: AAA", "tono": "aviso"} in notas[0]["etiquetas"]


# ======================================================================
# Trabajos en segundo plano
# ======================================================================
class TestTrabajos:
    def test_no_hay_dos_acciones_a_la_vez(self):
        liberar = threading.Event()

        class _Agente:
            def revisar_niveles_ahora(self):
                liberar.wait(5)
                print("revisado")
                return {"resumen": "ok"}

        gestor = GestorTrabajos(_Agente)
        trabajo = gestor.lanzar("niveles")
        with pytest.raises(OcupadoError):
            gestor.lanzar("diario")
        liberar.set()
        for _ in range(100):
            if trabajo.estado != "en_curso":
                break
            threading.Event().wait(0.05)

        assert trabajo.estado == "ok"
        assert trabajo.resultado == {"resumen": "ok"}
        # Lo que imprime la acción va a su propio registro, no a la consola.
        assert "revisado" in "".join(trabajo.log)

    def test_un_fallo_queda_registrado_sin_tumbar_nada(self):
        class _Agente:
            def run_daily_cycle(self):
                raise RuntimeError("fallo de prueba")

        gestor = GestorTrabajos(_Agente)
        trabajo = gestor.lanzar("diario")
        for _ in range(100):
            if trabajo.estado != "en_curso":
                break
            threading.Event().wait(0.05)
        assert trabajo.estado == "error"
        assert "fallo de prueba" in trabajo.error

    def test_las_acciones_que_usan_claude_declaran_su_coste(self):
        for accion in ACCIONES.values():
            assert accion.coste
            assert accion.usa_claude == (
                accion.clave in {"diario", "noticias", "estudio", "comite", "explorar", "revisar"}
            )


# ======================================================================
# Servidor: seguridad
# ======================================================================
@pytest.fixture
def servidor(vault_tmp):
    class _Agente:
        vault = vault_tmp

    app = EstadoApp(fabrica_agente=_Agente, token="token-de-prueba")
    srv = crear_servidor(app, puerto=0)
    puerto = srv.server_address[1]
    # `crear_servidor` valida el Host contra el puerto pedido (0): se
    # recrea con el puerto real para que la comprobación sea la de verdad.
    srv.server_close()
    srv = crear_servidor(app, puerto=puerto)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield puerto
    srv.shutdown()
    srv.server_close()


def _peticion(puerto, metodo, ruta, cabeceras=None, cuerpo=None, host=None):
    conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
    cab = {"Host": host or f"127.0.0.1:{puerto}", **(cabeceras or {})}
    conexion.request(metodo, ruta, body=cuerpo, headers=cab)
    respuesta = conexion.getresponse()
    datos_ = respuesta.read()
    conexion.close()
    return respuesta, datos_


class TestSeguridadServidor:
    def test_la_pagina_lleva_el_token_y_una_csp_estricta(self, servidor):
        respuesta, cuerpo = _peticion(servidor, "GET", "/")
        assert respuesta.status == 200
        assert b"token-de-prueba" in cuerpo
        csp = respuesta.getheader("Content-Security-Policy")
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp

    def test_api_sin_token_se_rechaza(self, servidor):
        respuesta, _ = _peticion(servidor, "GET", "/api/informes?tipo=diario")
        assert respuesta.status == 401

    def test_api_con_token_responde(self, servidor):
        respuesta, cuerpo = _peticion(
            servidor, "GET", "/api/informes?tipo=diario", {"X-Sharky-Token": "token-de-prueba"}
        )
        assert respuesta.status == 200
        assert json.loads(cuerpo)["tipo"] == "diario"

    def test_host_ajeno_se_rechaza(self, servidor):
        """Frena el DNS rebinding: una web ajena apuntando a 127.0.0.1."""
        respuesta, _ = _peticion(
            servidor, "GET", "/api/informes", {"X-Sharky-Token": "token-de-prueba"}, host="evil.example"
        )
        assert respuesta.status == 403

    def test_post_exige_json(self, servidor):
        """Un formulario HTML de otra web no puede lanzar acciones."""
        respuesta, _ = _peticion(
            servidor, "POST", "/api/trabajos",
            {"X-Sharky-Token": "token-de-prueba", "Content-Type": "application/x-www-form-urlencoded"},
            cuerpo="accion=estudio",
        )
        assert respuesta.status == 415

    def test_no_se_sirven_ficheros_fuera_de_static(self, servidor):
        for ruta in ("/static/../servidor.py", "/static/..%2Fservidor.py", "/static/index.html"):
            respuesta, _ = _peticion(servidor, "GET", ruta)
            assert respuesta.status == 404

    def test_nota_fuera_de_la_boveda(self, servidor):
        respuesta, _ = _peticion(
            servidor, "GET", "/api/nota?id=../.env", {"X-Sharky-Token": "token-de-prueba"}
        )
        assert respuesta.status == 403


# ======================================================================
# Panel: fecha del último control
# ======================================================================
def _agente_sin_red(tmp_path, custodio="Trade Republic Bank GmbH"):
    """SharkyAgent con bóveda temporal y mercado de prueba: no toca la red."""
    from sharky.agent_loop import SharkyAgent
    from sharky.models import Portfolio, Position
    from sharky.portfolio import PortfolioStore, PortfolioValuator
    from sharky.risk_governor import RiskGovernor
    from sharky.vault_manager import VaultManager

    from conftest import FakeFx, FakeMarket

    store = PortfolioStore(tmp_path)
    store.save(Portfolio(custodio=custodio, efectivo_eur=1000.0, posiciones=[
        Position(ticker="AAA", nombre="Alfa", ticker_cotizacion="AAA", divisa_cotizacion="EUR",
                 unidades=10.0, coste_unitario_eur=100.0, sector="Tecnologia"),
    ]))
    market, fx = FakeMarket({"AAA": (110.0, "EUR")}), FakeFx()
    agente = SharkyAgent.__new__(SharkyAgent)
    agente.vault = VaultManager(tmp_path)
    agente.market, agente.fx, agente.store = market, fx, store
    agente.valuator = PortfolioValuator(market=market, fx=fx)
    agente.risk = RiskGovernor()
    return agente


class TestPanelUltimoControl:
    """El panel revalora la cartera en el momento, y ese estado recalculado
    trae «ahora» como fecha del último control. Hasta 2026-09 el panel la
    enseñaba: «Último control: <hora actual>» con el control del día
    pendiente, o sin haberse hecho nunca ninguno."""

    def test_sin_ningun_control_no_inventa_una_fecha(self, tmp_path):
        panel = datos.construir_panel(_agente_sin_red(tmp_path))

        assert panel["salud"]["ultimo_ciclo"] is None
        assert panel["cadencia"]["diario"]["ultimo"] is None
        assert panel["cadencia"]["diario"]["hecho_hoy"] is False

    def test_ensena_la_fecha_guardada_del_ultimo_control(self, tmp_path):
        from datetime import datetime, timedelta

        agente = _agente_sin_red(tmp_path)
        ayer = datetime.now() - timedelta(days=1)
        agente.vault.health_path.write_text(
            agente.vault.build_markdown({"ultimo_ciclo_diario": ayer.isoformat()}, "# x\n"),
            encoding="utf-8",
        )

        panel = datos.construir_panel(agente)

        assert panel["cadencia"]["diario"]["ultimo"] == ayer.isoformat(timespec="minutes")
        assert panel["salud"]["ultimo_ciclo"] == ayer.isoformat(timespec="minutes")


def test_el_panel_nombra_el_broker_del_libro(tmp_path):
    """La pantalla Operar decía siempre «Trade Republic»: cada usuario
    declara su bróker en `sharky init` y el panel lo lleva."""
    panel = datos.construir_panel(_agente_sin_red(tmp_path, custodio="Mi Bróker S.A."))

    assert panel["cartera"]["custodio"] == "Mi Bróker S.A."
