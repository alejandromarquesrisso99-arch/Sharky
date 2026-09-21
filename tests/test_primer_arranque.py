"""
Primer arranque: quien clona Sharky empieza sin libro de posiciones ni clave.

El repositorio es público y la bóveda no viaja con él, así que cada usuario
nuevo pasa por aquí. Hasta 2026-09 era un callejón sin salida: cualquier
comando pedía un `sharky portfolio --init` que no existía.
"""

import re
import sys

import pytest

from sharky import config, primer_arranque
from sharky.models import AssetClass, HealthStatus
from sharky.portfolio import PortfolioStore
from sharky.primer_arranque import (
    PLANTILLA_CSV,
    ErrorCSV,
    _numero,
    asistente,
    crear_boveda,
    guardar_clave_api,
    leer_csv_posiciones,
)
from sharky.vault_manager import VaultManager


def _csv(tmp_path, contenido, nombre="posiciones.csv", codificacion="utf-8"):
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido.encode(codificacion))
    return ruta


def _guion(*respuestas):
    """Respuestas del usuario, en orden. Agotadas, se comporta como Ctrl+Z."""
    pendientes = iter(respuestas)

    def preguntar(_texto=""):
        try:
            return next(pendientes)
        except StopIteration:
            raise EOFError from None

    return preguntar


@pytest.fixture
def sin_clave(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")


# ======================================================================
# CSV de posiciones
# ======================================================================
class TestLeerCsv:
    def test_la_plantilla_se_lee_tal_cual(self, tmp_path):
        posiciones = leer_csv_posiciones(_csv(tmp_path, PLANTILLA_CSV))

        por_ticker = {p.ticker: p for p in posiciones}
        assert list(por_ticker) == ["AAPL", "SAN", "IWDA"]
        san = por_ticker["SAN"]
        assert san.unidades == pytest.approx(200.0)
        assert san.coste_unitario_eur == pytest.approx(4.5)
        assert san.divisa_cotizacion == "EUR"
        assert san.ticker_cotizacion == "SAN.MC"
        assert san.isin == "ES0113900J37"
        assert san.nota_activo == "[[SAN]]"
        assert por_ticker["IWDA"].clase == AssetClass.ETF

    def test_sin_cabecera_con_comas_y_punto_decimal(self, tmp_path):
        ruta = _csv(tmp_path, "MSFT,Microsoft,US5949181045,1.5,300.25,USD,Tecnologia,MSFT,ACCION\n")

        (p,) = leer_csv_posiciones(ruta)

        assert (p.unidades, p.coste_unitario_eur, p.divisa_cotizacion) == (1.5, 300.25, "USD")

    def test_decimal_con_coma_y_miles_con_punto(self, tmp_path):
        (p,) = leer_csv_posiciones(_csv(tmp_path, "ZZZ;Zeta;;1.234,5;2,5;EUR\n"))

        assert p.unidades == pytest.approx(1234.5)
        assert p.coste_unitario_eur == pytest.approx(2.5)

    def test_bom_de_utf8_y_csv_de_excel_en_cp1252(self, tmp_path):
        con_bom = _csv(tmp_path, "﻿ticker;nombre;isin;unidades;coste;divisa\nZZZ;Zeta;;1;2;EUR\n", "a.csv")
        excel = _csv(tmp_path, "TEF;Telefónica;;10;4;EUR\n", "b.csv", codificacion="cp1252")

        assert leer_csv_posiciones(con_bom)[0].ticker == "ZZZ"
        assert leer_csv_posiciones(excel)[0].nombre == "Telefónica"

    def test_las_columnas_opcionales_pueden_faltar(self, tmp_path):
        (p,) = leer_csv_posiciones(_csv(tmp_path, "ZZZ;Zeta;;10;4;EUR\n"))

        assert p.isin is None
        assert p.sector == ""
        assert p.ticker_cotizacion is None  # se valora a coste hasta resolve-isin
        assert p.clase == AssetClass.ACCION

    def test_el_simbolo_del_registro_solo_si_cotiza_en_la_misma_divisa(self, tmp_path):
        """Un símbolo en otra divisa valoraría la posición con el precio
        equivocado: mejor sin cotización (a coste y señalizada)."""
        en_usd = leer_csv_posiciones(_csv(tmp_path, "SPY;SPDR S&P 500;;1;400;USD\n", "a.csv"))
        en_eur = leer_csv_posiciones(_csv(tmp_path, "SPY;SPDR S&P 500;;1;400;EUR\n", "b.csv"))

        assert en_usd[0].ticker_cotizacion == "SPY"
        assert en_eur[0].ticker_cotizacion is None

    def test_ignora_comentarios_y_lineas_vacias_aunque_precedan_a_la_cabecera(self, tmp_path):
        ruta = _csv(tmp_path, "# mis posiciones\n\n" + PLANTILLA_CSV + "\n")

        assert len(leer_csv_posiciones(ruta)) == 3

    def test_devuelve_todos_los_errores_de_una_vez_con_su_linea(self, tmp_path):
        ruta = _csv(
            tmp_path,
            "ticker;nombre;isin;unidades;coste_medio_eur;divisa\n"
            "AAA;Alfa;;0;10;EUR\n"          # unidades a cero
            "BBB;Beta;;diez;10;EUR\n"       # unidades no numéricas
            "CCC;Gamma;;1;10;EUROS\n"       # divisa mal
            "DDD;Delta;XX123;1;10;EUR\n"    # ISIN mal
            "EEE;Épsilon;;1;10\n"           # faltan columnas
            "FFF;Fi;;1;10;EUR;;;BONO\n"     # clase inexistente
            "AAA;Otra vez;;1;10;EUR\n",     # ticker repetido
        )

        with pytest.raises(ErrorCSV) as exc:
            leer_csv_posiciones(ruta)

        errores = exc.value.errores
        assert [re.match(r"Línea (\d+)", e).group(1) for e in errores] == [
            "2", "3", "4", "5", "6", "7", "8",
        ]
        assert "repetido" in errores[-1]

    def test_demasiadas_columnas_sugiere_separar_con_punto_y_coma(self, tmp_path):
        ruta = _csv(tmp_path, "AAA,Alfa,,1,5,2,5,EUR,Tecnologia,AAA,ACCION\n")

        with pytest.raises(ErrorCSV) as exc:
            leer_csv_posiciones(ruta)

        assert "`;`" in exc.value.errores[0]


@pytest.mark.parametrize(
    "texto, esperado",
    [("1.234,56", 1234.56), ("1,234.56", 1234.56), ("0,5", 0.5), ("10", 10.0), (" 2 € ", 2.0)],
)
def test_numero_admite_coma_o_punto_decimal(texto, esperado):
    assert _numero(texto) == pytest.approx(esperado)


def test_numero_rechaza_lo_que_no_es_un_numero():
    with pytest.raises(ValueError):
        _numero("abc")


# ======================================================================
# Clave de Claude en .env
# ======================================================================
class TestClaveApi:
    EJEMPLO = "# Clave\nANTHROPIC_API_KEY=tu_api_key_aqui\nCLAUDE_MODEL=modelo-x\n"

    def test_crea_el_env_desde_el_ejemplo(self, tmp_path):
        ejemplo = _csv(tmp_path, self.EJEMPLO, ".env.example")
        env = tmp_path / ".env"

        guardar_clave_api("sk-ant-prueba", env, ejemplo)

        texto = env.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY=sk-ant-prueba" in texto
        assert "tu_api_key_aqui" not in texto
        assert "CLAUDE_MODEL=modelo-x" in texto

    def test_actualiza_un_env_existente_sin_tocar_el_resto(self, tmp_path):
        env = _csv(tmp_path, "SHARKY_MAX_POS_PCT=8\nANTHROPIC_API_KEY=vieja\n", ".env")

        guardar_clave_api("sk-ant-nueva", env, tmp_path / "no_existe")

        assert env.read_text(encoding="utf-8") == "SHARKY_MAX_POS_PCT=8\nANTHROPIC_API_KEY=sk-ant-nueva\n"

    def test_una_clave_con_barras_se_guarda_literal(self, tmp_path):
        env = _csv(tmp_path, "ANTHROPIC_API_KEY=\n", ".env")

        guardar_clave_api(r"sk-ant-a\1b", env, tmp_path / "no_existe")

        assert r"ANTHROPIC_API_KEY=sk-ant-a\1b" in env.read_text(encoding="utf-8")

    def test_si_no_hay_linea_la_anade(self, tmp_path):
        env = _csv(tmp_path, "OTRA=1", ".env")

        guardar_clave_api("sk-ant-x", env, tmp_path / "no_existe")

        assert env.read_text(encoding="utf-8") == "OTRA=1\nANTHROPIC_API_KEY=sk-ant-x\n"


# ======================================================================
# Bóveda nueva
# ======================================================================
class TestCrearBoveda:
    def _posiciones(self, tmp_path):
        return leer_csv_posiciones(_csv(tmp_path, PLANTILLA_CSV))

    def test_crea_libro_fichas_e_indices(self, tmp_path):
        vault = tmp_path / "vault"

        crear_boveda(self._posiciones(tmp_path), 1000.0, "Mi Bróker", vault)

        cartera = PortfolioStore(vault).load()
        assert cartera.efectivo_eur == pytest.approx(1000.0)
        assert cartera.custodio == "Mi Bróker"
        assert [p.ticker for p in cartera.posiciones] == ["AAPL", "SAN", "IWDA"]
        assert (vault / "03_Activos" / "Empresas" / "SAN.md").exists()
        assert (vault / "05_Diario_Reflexion" / "05_Diario_Reflexion.md").exists()
        moc_activos = (vault / "03_Activos" / "03_Activos.md").read_text(encoding="utf-8")
        assert "[[SAN]]" in moc_activos

    def test_no_sobrescribe_un_libro_existente(self, tmp_path):
        vault = tmp_path / "vault"
        crear_boveda(self._posiciones(tmp_path), 1000.0, vault_path=vault)
        antes = (vault / "00_Sistema" / "Cartera_Real.md").read_text(encoding="utf-8")

        with pytest.raises(FileExistsError):
            crear_boveda([], 5.0, vault_path=vault)

        assert (vault / "00_Sistema" / "Cartera_Real.md").read_text(encoding="utf-8") == antes

    def test_las_notas_que_escribe_sharky_caen_en_su_indice(self, tmp_path):
        """Los encabezados de los índices son los que usa `_append_to_moc`:
        si no coincidieran, cada entrada acabaría al final, tras el grafo."""
        vault = tmp_path / "vault"
        crear_boveda([], 0.0, vault_path=vault)

        VaultManager(vault).write_daily_journal("2026-09-21", "Sin novedades.", HealthStatus())

        moc = (vault / "05_Diario_Reflexion" / "05_Diario_Reflexion.md").read_text(encoding="utf-8")
        assert moc.index("[[2026-09-21_Cierre_Mercado]]") < moc.index("## 🔗 Enlaces del Grafo")


# ======================================================================
# Asistente
# ======================================================================
class TestAsistente:
    def _rutas(self, tmp_path):
        return dict(
            vault_path=tmp_path / "vault",
            ruta_env=tmp_path / ".env",
            ruta_ejemplo=tmp_path / "no_existe",
            ruta_plantilla=tmp_path / "plantilla.csv",
        )

    def test_camino_feliz(self, tmp_path, sin_clave):
        csv_ruta = _csv(tmp_path, PLANTILLA_CSV)
        salida = []

        listo = asistente(
            **self._rutas(tmp_path),
            preguntar=_guion(f'"{csv_ruta}"', "1500,50", "", "s"),
            preguntar_secreto=lambda _t: "sk-ant-prueba",
            mostrar=salida.append,
        )

        assert listo
        assert "ANTHROPIC_API_KEY=sk-ant-prueba" in (tmp_path / ".env").read_text(encoding="utf-8")
        cartera = PortfolioStore(tmp_path / "vault").load()
        assert cartera.efectivo_eur == pytest.approx(1500.5)
        assert cartera.custodio == primer_arranque.CUSTODIO_POR_DEFECTO
        assert len(cartera.posiciones) == 3
        # La clave nunca se muestra.
        assert not any("sk-ant-prueba" in linea for linea in salida)

    def test_cancelar_en_el_resumen_no_escribe_nada(self, tmp_path, sin_clave):
        csv_ruta = _csv(tmp_path, PLANTILLA_CSV)

        listo = asistente(
            **self._rutas(tmp_path),
            preguntar=_guion(str(csv_ruta), "", "", "n"),
            preguntar_secreto=lambda _t: "sk-ant-prueba",
            mostrar=lambda _t: None,
        )

        assert not listo
        assert not (tmp_path / ".env").exists()
        assert not (tmp_path / "vault" / "00_Sistema" / "Cartera_Real.md").exists()

    def test_enter_crea_una_plantilla_que_despues_se_puede_usar(self, tmp_path, sin_clave):
        rutas = self._rutas(tmp_path)

        listo = asistente(
            **rutas,
            preguntar=_guion("", str(rutas["ruta_plantilla"]), "", "", "s"),
            preguntar_secreto=lambda _t: "",
            mostrar=lambda _t: None,
        )

        assert listo
        assert rutas["ruta_plantilla"].read_text(encoding="utf-8") == PLANTILLA_CSV
        assert len(PortfolioStore(rutas["vault_path"]).load().posiciones) == 3
        assert not (tmp_path / ".env").exists()  # sin clave: modo simulado

    def test_un_csv_con_errores_se_explica_y_se_vuelve_a_pedir(self, tmp_path, sin_clave):
        malo = _csv(tmp_path, "AAA;Alfa;;cero;10;EUR\n", "malo.csv")
        bueno = _csv(tmp_path, PLANTILLA_CSV, "bueno.csv")
        salida = []

        listo = asistente(
            **self._rutas(tmp_path),
            preguntar=_guion(str(malo), str(bueno), "", "", "s"),
            preguntar_secreto=lambda _t: "",
            mostrar=salida.append,
        )

        assert listo
        assert any("Línea 1" in linea for linea in salida)

    @pytest.mark.parametrize("interrupcion", [_guion("q"), _guion()])
    def test_salir_o_ctrl_c_no_escribe_nada(self, tmp_path, sin_clave, interrupcion):
        listo = asistente(
            **self._rutas(tmp_path),
            preguntar=interrupcion,
            preguntar_secreto=lambda _t: "sk-ant-prueba",
            mostrar=lambda _t: None,
        )

        assert not listo
        assert not (tmp_path / ".env").exists()
        assert not (tmp_path / "vault" / "00_Sistema").exists()

    def test_con_clave_configurada_no_la_pide(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-ya-configurada")

        def no_preguntar(_texto):
            raise AssertionError("no debía pedir la clave")

        listo = asistente(
            **self._rutas(tmp_path),
            preguntar=_guion(str(_csv(tmp_path, PLANTILLA_CSV)), "", "", "s"),
            preguntar_secreto=no_preguntar,
            mostrar=lambda _t: None,
        )

        assert listo
        assert not (tmp_path / ".env").exists()

    def test_con_libro_existente_no_lo_toca(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-ya-configurada")
        rutas = self._rutas(tmp_path)
        crear_boveda([], 42.0, vault_path=rutas["vault_path"])

        listo = asistente(**rutas, preguntar=_guion(), mostrar=lambda _t: None)

        assert listo
        assert PortfolioStore(rutas["vault_path"]).load().efectivo_eur == pytest.approx(42.0)


# ======================================================================
# Arranque sin configurar
# ======================================================================
class TestArranqueSinConfigurar:
    def test_sin_nadie_delante_no_pregunta_y_explica_que_hacer(self, monkeypatch, capsys):
        """La tarea programada escribe en un log: preguntar la dejaría colgada."""
        from sharky import cli

        monkeypatch.setattr(sys, "argv", ["sharky", "startup"])
        monkeypatch.setattr(primer_arranque, "falta_configurar", lambda *a: True)
        monkeypatch.setattr(primer_arranque, "es_interactivo", lambda: False)
        monkeypatch.setattr(primer_arranque, "asistente", lambda **k: pytest.fail("no debía preguntar"))

        assert cli.main() == 2
        assert "python -m sharky.cli init" in capsys.readouterr().out

    def test_con_consola_configura_y_repite_la_orden(self, monkeypatch):
        from sharky import cli

        llamadas = []
        monkeypatch.setattr(sys, "argv", ["sharky", "portfolio"])
        monkeypatch.setattr(primer_arranque, "falta_configurar", lambda *a: True)
        monkeypatch.setattr(primer_arranque, "es_interactivo", lambda: True)
        monkeypatch.setattr(primer_arranque, "asistente", lambda **k: True)
        monkeypatch.setattr(
            primer_arranque, "relanzar", lambda modulo, args: llamadas.append((modulo, args)) or 0
        )

        assert cli.main() == 0
        assert llamadas == [("sharky.cli", ["portfolio"])]

    def test_la_app_sin_consola_abre_el_asistente_en_otra_ventana(self, monkeypatch):
        """El acceso directo lanza la app con pythonw: no hay consola."""
        from sharky.app import servidor

        monkeypatch.setattr(primer_arranque, "falta_configurar", lambda *a: True)
        monkeypatch.setattr(primer_arranque, "es_interactivo", lambda: False)
        abiertas = []
        monkeypatch.setattr(primer_arranque, "abrir_asistente_en_consola", lambda: abiertas.append(1) or True)
        monkeypatch.setattr(servidor, "crear_servidor", lambda *a, **k: pytest.fail("no debía arrancar"))

        assert servidor.main([]) == 0
        assert abiertas == [1]

    def test_falta_configurar_mira_el_libro_de_posiciones(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
        assert primer_arranque.falta_configurar()

        crear_boveda([], 0.0)

        assert not primer_arranque.falta_configurar()
