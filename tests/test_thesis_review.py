"""
Suite de la revisión mensual de tesis.

Estos tests protegen tres cosas, en orden de gravedad si se rompen:

  1. **Que la revisión no toque un solo número de la tesis.** El stop-loss es
     la única salida obligatoria del mandato; `level_watch` lo compara cada
     día contra el precio real. Una revisión que pudiera moverlo convertiría
     una posición perdedora en una posición con el stop siempre un poco más
     abajo.
  2. **Que añada en vez de sobrescribir.** Lo que se escribió en agosto tiene
     que seguir ahí en diciembre, o se pierde la única pregunta que enseña
     algo.
  3. **Que la selección sea determinista y explicable.** Qué se revisa y qué
     no, con el motivo escrito, sin gastar API.

No se llama a la API en ningún momento.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from sharky.models import (
    InvestmentThesis,
    LevelAlert,
    LevelKind,
    RiskBreach,
)
from sharky.thesis_review import (
    ThesisReviewer,
    ThesisVerdict,
    movimiento_del_mes,
    seleccionar,
)
from sharky.vault_manager import VaultManager


TESIS_BASE = """---
ticker: MSFT
empresa: Microsoft Corporation
tipo: Largo
estado: Activa
unidades: 3.141590
precio_entrada: 400.0
stop_loss: 350.0
target_precio: 560.0
conviccion: 9
ratio_rr: 3.2
fecha_apertura: 2026-08-31
sectores: '[[Cloud_Software]]'
empresa_nota: '[[MSFT]]'
divisa: EUR
tiene_posicion: true
---

# 🎯 Tesis de Inversión: Microsoft Corporation (MSFT)

## 💡 Racional de Inversión

Azure y el foso de distribución empresarial.

---

## 🔗 Enlaces Bidireccionales del Grafo

* Ficha de Empresa: [[MSFT]]
"""


def _tesis(ticker="MSFT", conviccion=9, apertura="2026-08-31", **kw) -> InvestmentThesis:
    datos = dict(
        ticker=ticker, empresa=f"{ticker} S.A.", tipo="Largo", estado="Activa",
        precio_entrada=100.0, divisa="EUR", stop_loss=90.0, target_precio=130.0,
        conviccion=conviccion, ratio_rr=3.0, fecha_apertura=apertura,
        sectores="[[Tecnologia_Global]]", empresa_nota=f"[[{ticker}]]",
        racional="Racional de prueba.",
    )
    datos.update(kw)
    return InvestmentThesis(**datos)


def _nota(tmp_path: Path, contenido: str = TESIS_BASE) -> Path:
    destino = tmp_path / "01_Tesis_Activas" / "Tesis_Microsoft.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    return destino


def _veredicto(**kw) -> ThesisVerdict:
    datos = dict(
        ticker="MSFT", veredicto="MANTENER",
        que_ha_cambiado="Azure aceleró.", que_sigue_en_pie="El foso.",
        que_la_invalidaria="Que el capex comprima el FCF.",
    )
    datos.update(kw)
    return ThesisVerdict(**datos)


# ======================================================================
# Selección
# ======================================================================
class TestSeleccion:
    def test_una_tesis_tranquila_no_se_revisa(self):
        """El punto del diseño: no generar prosa donde no pasó nada."""
        tesis = [(Path("t.md"), _tesis(apertura="2026-09-01"))]
        a_revisar, omitidas = seleccionar(tesis, hoy=date(2026, 10, 1))

        assert a_revisar == []
        assert len(omitidas) == 1
        assert "sin movimiento" in omitidas[0].descarte

    def test_un_nivel_alcanzado_la_selecciona(self):
        tesis = [(Path("t.md"), _tesis(apertura="2026-09-01"))]
        nivel = LevelAlert(
            tipo=LevelKind.STOP_LOSS, ticker="MSFT", precio_eur=80.0,
            precio_cotizacion=80.0, divisa_cotizacion="EUR", nivel=90.0,
            divisa_nivel="EUR", valor_posicion_eur=1000.0,
        )
        a_revisar, _ = seleccionar(tesis, niveles=[nivel], hoy=date(2026, 10, 1))

        assert [s.ticker for s in a_revisar] == ["MSFT"]
        assert "nivel alcanzado" in a_revisar[0].motivos

    def test_un_incumplimiento_abierto_la_selecciona(self):
        tesis = [(Path("t.md"), _tesis(apertura="2026-09-01"))]
        brecha = RiskBreach(
            regla="Concentración", severidad="ALTA", sujeto="MSFT",
            valor_actual_pct=12.0, limite_pct=10.0, mensaje="excede",
            accion_correctiva="recortar",
        )
        a_revisar, _ = seleccionar(tesis, incumplimientos=[brecha], hoy=date(2026, 10, 1))

        assert "incumplimiento del mandato abierto" in a_revisar[0].motivos

    def test_el_movimiento_del_mes_la_selecciona(self):
        """Una deriva lenta no dispara ningún aviso diario y sí una revisión."""
        memoria = [
            {"fecha": "2026-09-01", "precios_eur": {"MSFT": 100.0}},
            {"fecha": "2026-09-30", "precios_eur": {"MSFT": 80.0}},
        ]
        tesis = [(Path("t.md"), _tesis(apertura="2026-09-01"))]
        a_revisar, _ = seleccionar(tesis, memoria=memoria, hoy=date(2026, 10, 1))

        assert "movimiento del mes -20.0%" in a_revisar[0].motivos

    def test_las_noticias_del_mes_la_seleccionan(self):
        noticias = [{
            "fecha": date(2026, 9, 20), "disponible": True,
            "resumen": "## MSFT — Microsoft\nAzure aceleró.\n\n## NVDA\nOtra cosa.",
        }]
        tesis = [(Path("t.md"), _tesis(apertura="2026-09-01"))]
        a_revisar, _ = seleccionar(tesis, noticias=noticias, hoy=date(2026, 10, 1))

        assert "noticias del mes" in a_revisar[0].motivos

    def test_la_red_de_seguridad_rescata_una_tesis_olvidada(self):
        """Tranquila no es lo mismo que olvidada."""
        tesis = [(Path("t.md"), _tesis(apertura="2026-01-01"))]
        a_revisar, _ = seleccionar(tesis, hoy=date(2026, 10, 1), meses_max=3)

        assert "9 mes(es) sin revisar" in a_revisar[0].motivos[0]

    def test_una_tesis_escrita_ayer_no_necesita_revision(self):
        """La red de seguridad cuenta desde la apertura si nunca se revisó."""
        tesis = [(Path("t.md"), _tesis(apertura="2026-09-30"))]
        a_revisar, omitidas = seleccionar(tesis, hoy=date(2026, 10, 1), meses_max=3)

        assert a_revisar == []
        assert len(omitidas) == 1

    def test_la_fecha_de_revision_manda_sobre_la_de_apertura(self):
        tesis = [(Path("t.md"), _tesis(apertura="2026-01-01"))]
        a_revisar, omitidas = seleccionar(
            tesis, revisadas={"MSFT": "2026-09-15"}, hoy=date(2026, 10, 1), meses_max=3
        )
        assert a_revisar == []
        assert len(omitidas) == 1

    def test_el_tope_deja_traza_en_vez_de_perder_tesis(self):
        tesis = [
            (Path(f"{i}.md"), _tesis(ticker=f"T{i}", apertura="2026-01-01"))
            for i in range(5)
        ]
        a_revisar, omitidas = seleccionar(tesis, hoy=date(2026, 10, 1), tope=2)

        assert len(a_revisar) == 2
        assert len(omitidas) == 3
        assert all("supera el tope" in o.descarte for o in omitidas)

    def test_ordena_por_numero_de_motivos_y_conviccion(self):
        tesis = [
            (Path("a.md"), _tesis(ticker="AAA", conviccion=6, apertura="2026-01-01")),
            (Path("b.md"), _tesis(ticker="BBB", conviccion=9, apertura="2026-01-01")),
        ]
        brecha = RiskBreach(
            regla="R", severidad="ALTA", sujeto="AAA", valor_actual_pct=1.0,
            limite_pct=0.0, mensaje="m", accion_correctiva="a",
        )
        a_revisar, _ = seleccionar(tesis, incumplimientos=[brecha], hoy=date(2026, 10, 1))

        # AAA tiene dos motivos (red de seguridad + incumplimiento); BBB uno.
        assert [s.ticker for s in a_revisar] == ["AAA", "BBB"]

    def test_el_movimiento_necesita_dos_controles_con_precios(self):
        assert movimiento_del_mes([{"precios_eur": {"MSFT": 100.0}}]) == {}
        assert movimiento_del_mes([]) == {}


# ======================================================================
# Lectura de los veredictos
# ======================================================================
class TestParseo:
    def test_lee_el_bloque_json(self):
        texto = (
            "Sintesis.\n\n```json\n"
            + json.dumps({"veredictos": [{
                "ticker": "MSFT", "veredicto": "REDUCIR",
                "que_ha_cambiado": "x", "que_sigue_en_pie": "y",
                "que_la_invalidaria": "z", "propuesta_niveles": "",
            }]})
            + "\n```\n"
        )
        veredictos, aviso = ThesisReviewer._extraer_veredictos(texto, ["MSFT"])
        assert aviso is None
        assert veredictos[0].veredicto == "REDUCIR"

    def test_descarta_veredictos_sobre_tesis_que_no_se_pidieron(self):
        """El revisor no puede anotar una tesis que no ha leído."""
        texto = (
            "```json\n"
            + json.dumps({"veredictos": [
                {"ticker": "MSFT"}, {"ticker": "INTRUSO"},
            ]})
            + "\n```"
        )
        veredictos, _ = ThesisReviewer._extraer_veredictos(texto, ["MSFT"])
        assert [v.ticker for v in veredictos] == ["MSFT"]

    def test_avisa_de_las_tesis_sin_veredicto(self):
        texto = "```json\n" + json.dumps({"veredictos": [{"ticker": "MSFT"}]}) + "\n```"
        _, aviso = ThesisReviewer._extraer_veredictos(texto, ["MSFT", "NVDA"])
        assert "NVDA" in aviso

    def test_un_veredicto_inventado_cae_a_mantener(self):
        """MANTENER es el veredicto que no cambia nada: el fallo seguro."""
        assert ThesisVerdict(ticker="MSFT", veredicto="VENDER TODO").veredicto == "MANTENER"

    def test_sin_bloque_json_se_declara(self):
        veredictos, aviso = ThesisReviewer._extraer_veredictos("Solo prosa.", ["MSFT"])
        assert veredictos == []
        assert "no incluía el bloque" in aviso

    def test_el_veredicto_no_tiene_donde_guardar_un_nivel_aplicable(self):
        """La frontera del módulo, escrita como test.

        `propuesta_niveles` es texto dirigido a una persona. Si algún día
        alguien lo convierte en un `float` que se asiente en el frontmatter,
        habrá dejado que un modelo renegocie el stop-loss cada mes.
        """
        campos = ThesisVerdict.model_fields
        assert not set(campos) & {"stop_loss", "target_precio", "conviccion"}
        assert campos["propuesta_niveles"].annotation is str


# ======================================================================
# La escritura sobre la nota: lo que de verdad importa
# ======================================================================
class TestEscritura:
    def test_no_cambia_ni_un_numero_de_la_tesis(self, tmp_path: Path):
        """El invariante central del módulo."""
        ruta = _nota(tmp_path)
        vault = VaultManager(tmp_path)
        antes, _ = vault.parse_markdown(ruta.read_text(encoding="utf-8"))

        vault.anotar_revision_tesis(ruta, _veredicto(veredicto="CERRAR"), "2026-10-01")
        despues, _ = vault.parse_markdown(ruta.read_text(encoding="utf-8"))

        for campo in VaultManager.CAMPOS_INTOCABLES:
            assert antes.get(campo) == despues.get(campo), campo

    def test_las_lineas_que_no_escribe_quedan_identicas(self, tmp_path: Path):
        """Byte a byte, no sólo numéricamente equivalentes.

        Un round-trip de YAML convertiría `unidades: 3.141590` en `3.14159`:
        mismo número, distinto texto. Editar el frontmatter como texto evita
        que una revisión ensucie el diff de campos que no le pertenecen.
        """
        ruta = _nota(tmp_path)
        lineas_antes = ruta.read_text(encoding="utf-8").split("\n---\n")[0].splitlines()

        VaultManager(tmp_path).anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")
        lineas_despues = ruta.read_text(encoding="utf-8").split("\n---\n")[0].splitlines()

        nuevas = set(lineas_despues) - set(lineas_antes)
        assert nuevas == {"fecha_revision: 2026-10-01", "veredicto_revision: MANTENER"}
        assert not set(lineas_antes) - set(lineas_despues)
        assert "unidades: 3.141590" in lineas_despues

    def test_conserva_todo_el_cuerpo_anterior(self, tmp_path: Path):
        ruta = _nota(tmp_path)
        cuerpo_antes = ruta.read_text(encoding="utf-8")

        VaultManager(tmp_path).anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")
        despues = ruta.read_text(encoding="utf-8")

        assert "Azure y el foso de distribución empresarial." in despues
        assert "## 💡 Racional de Inversión" in despues
        assert len(despues) > len(cuerpo_antes)

    def test_las_revisiones_se_apilan(self, tmp_path: Path):
        """En marzo tienes que poder leer lo que pensabas en octubre."""
        ruta = _nota(tmp_path)
        vault = VaultManager(tmp_path)

        vault.anotar_revision_tesis(ruta, _veredicto(veredicto="MANTENER"), "2026-10-01")
        vault.anotar_revision_tesis(ruta, _veredicto(veredicto="REDUCIR"), "2026-11-01")
        texto = ruta.read_text(encoding="utf-8")

        assert "Revisión 2026-10-01" in texto
        assert "Revisión 2026-11-01" in texto
        # La más antigua arriba: la nota se lee como una cronología.
        assert texto.index("Revisión 2026-10-01") < texto.index("Revisión 2026-11-01")
        # El frontmatter refleja sólo la última.
        meta, _ = vault.parse_markdown(texto)
        assert str(meta["fecha_revision"]) == "2026-11-01"
        assert meta["veredicto_revision"] == "REDUCIR"

    def test_la_revision_va_antes_de_los_enlaces_del_grafo(self, tmp_path: Path):
        ruta = _nota(tmp_path)
        VaultManager(tmp_path).anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")
        texto = ruta.read_text(encoding="utf-8")

        assert texto.index("Revisión 2026-10-01") < texto.index("Enlaces Bidireccionales")

    def test_sin_enlaces_del_grafo_se_anade_al_final(self, tmp_path: Path):
        sin_enlaces = TESIS_BASE.split("## 🔗")[0]
        ruta = _nota(tmp_path, sin_enlaces)
        VaultManager(tmp_path).anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")

        assert ruta.read_text(encoding="utf-8").rstrip().endswith(
            "**Qué la invalidaría ahora:** Que el capex comprima el FCF."
        )

    def test_una_propuesta_de_nivel_se_marca_como_no_aplicada(self, tmp_path: Path):
        """Si el aviso desaparece, el lector asume que el stop ya cambió."""
        ruta = _nota(tmp_path)
        vault = VaultManager(tmp_path)
        vault.anotar_revision_tesis(
            ruta, _veredicto(propuesta_niveles="Subir el stop a 360 EUR."), "2026-10-01"
        )
        texto = ruta.read_text(encoding="utf-8")

        assert "NO aplicada" in texto
        assert "Subir el stop a 360 EUR." in texto
        # Y el stop de verdad sigue donde estaba.
        meta, _ = vault.parse_markdown(texto)
        assert meta["stop_loss"] == 350.0

    def test_el_motivo_de_la_seleccion_queda_escrito(self, tmp_path: Path):
        ruta = _nota(tmp_path)
        VaultManager(tmp_path).anotar_revision_tesis(
            ruta, _veredicto(), "2026-10-01", motivos=["nivel alcanzado", "noticias del mes"]
        )
        assert "nivel alcanzado, noticias del mes" in ruta.read_text(encoding="utf-8")

    def test_una_nota_sin_frontmatter_no_se_anota(self, tmp_path: Path):
        ruta = _nota(tmp_path, "# Tesis suelta\n\nSin frontmatter.\n")
        with pytest.raises(ValueError, match="frontmatter"):
            VaultManager(tmp_path).anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")

    def test_la_guardia_de_campos_intocables_salta(self, tmp_path: Path):
        """Defensa contra una regresión futura, no contra el código de hoy."""
        ruta = _nota(tmp_path)
        vault = VaultManager(tmp_path)
        original = VaultManager._fijar_clave

        def saboteador(frontmatter, clave, valor):
            frontmatter = original(frontmatter, clave, valor)
            return original(frontmatter, "stop_loss", "1.0")

        VaultManager._fijar_clave = staticmethod(saboteador)
        try:
            with pytest.raises(ValueError, match="stop_loss"):
                vault.anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")
        finally:
            VaultManager._fijar_clave = staticmethod(original)

        # Y la nota queda intacta: la escritura ni siquiera llegó a ocurrir.
        meta, _ = vault.parse_markdown(ruta.read_text(encoding="utf-8"))
        assert meta["stop_loss"] == 350.0
        assert "fecha_revision" not in meta

    def test_las_fechas_de_revision_se_pueden_releer(self, tmp_path: Path):
        ruta = _nota(tmp_path)
        vault = VaultManager(tmp_path)
        assert vault.leer_fechas_revision_tesis() == {}

        vault.anotar_revision_tesis(ruta, _veredicto(), "2026-10-01")
        assert vault.leer_fechas_revision_tesis() == {"MSFT": "2026-10-01"}
