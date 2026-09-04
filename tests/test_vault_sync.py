"""
Test de sincronía entre los umbrales de riesgo en el código (`sharky.config`)
y los mismos umbrales documentados en el vault de Obsidian.

Por qué existe: en la auditoría de 2026-09 se encontraron dos notas del
vault (`Politica_Control_Riesgo.md` y `Mandato_Institucional.md`) citando
umbrales de drawdown que ya no coincidían con `RiskGovernor.clasificar_estado`
ni con `Reglas_De_Supervivencia.md` -- y sólo se detectó por revisión manual,
nota por nota. Este archivo convierte esa comprobación en algo automático:
si alguien cambia un umbral en `config.py` sin actualizar el vault (o al
revés), el test suite falla aquí en vez de esperar a la próxima auditoría.

Esto NO es un parser de markdown genérico. Cada test conoce la redacción
exacta de la nota que lee. Si se reescribe una nota, hay que actualizar
también su patrón aquí -- ese acoplamiento es intencional: es lo que
convierte este test en una comprobación real en vez de un regex que
siempre "encuentra algo" y no protege nada.
"""

from __future__ import annotations

import re

import pytest

from sharky import config

VAULT = config.VAULT_PATH


def _read_normalizado(relative: str) -> str:
    """Lee una nota del vault con los saltos de línea colapsados a espacios.

    Las notas envuelven frases largas en varias líneas de markdown; colapsar
    el whitespace deja los patrones libres de tener que anticipar dónde cae
    cada salto de línea.
    """
    path = VAULT / relative
    if not path.exists():
        pytest.skip(f"Nota del vault no encontrada: {relative} (¿VAULT_PATH correcto?)")
    raw = path.read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", raw)


def _extraer(text: str, pattern: str, *, doc: str) -> tuple[float, ...]:
    match = re.search(pattern, text)
    assert match, (
        f"No se pudo localizar en {doc} el patrón esperado {pattern!r}. "
        "Si reescribiste la redacción de la nota, actualiza también este patrón "
        "en tests/test_vault_sync.py -- no lo borres sin más."
    )
    return tuple(float(g) for g in match.groups())


class TestReglasDeSupervivencia:
    """`vault/00_Sistema/Reglas_De_Supervivencia.md` -- la nota fuente."""

    DOC = "00_Sistema/Reglas_De_Supervivencia.md"

    def test_escalera_de_drawdown(self) -> None:
        text = _read_normalizado(self.DOC)

        (optimo,) = _extraer(text, r"Óptimo\*\* \| Drawdown < (\d+(?:\.\d+)?)%", doc=self.DOC)
        assert optimo == config.DRAWDOWN_OPTIMO_MAX_PCT

        alerta_lo, alerta_hi = _extraer(
            text, r"Alerta\*\* \| Drawdown entre (\d+(?:\.\d+)?)% y (\d+(?:\.\d+)?)%", doc=self.DOC
        )
        assert alerta_lo == config.DRAWDOWN_OPTIMO_MAX_PCT
        assert alerta_hi == config.DRAWDOWN_ALERTA_MAX_PCT

        ci_lo, ci_hi = _extraer(
            text,
            r"Cuidados Intensivos\*\* \| Drawdown entre (\d+(?:\.\d+)?)% y (\d+(?:\.\d+)?)%",
            doc=self.DOC,
        )
        assert ci_lo == config.DRAWDOWN_ALERTA_MAX_PCT
        assert ci_hi == config.DEATH_DRAWDOWN_PCT

        (muerte,) = _extraer(text, r"Muerte / Reboot\*\* \| Drawdown > (\d+(?:\.\d+)?)%", doc=self.DOC)
        assert muerte == config.DEATH_DRAWDOWN_PCT

    def test_limites_de_posicion_y_cash(self) -> None:
        text = _read_normalizado(self.DOC)

        (max_pos,) = _extraer(
            text,
            r"Máximo por Activo Individual:\*\* Ningún activo puede representar más del \*\*(\d+(?:\.\d+)?)%",
            doc=self.DOC,
        )
        assert max_pos == config.MAX_POSITION_SIZE_PCT

        (max_sector,) = _extraer(
            text,
            r"Máximo por Sector Industrial:\*\* .*? puede superar el \*\*(\d+(?:\.\d+)?)%",
            doc=self.DOC,
        )
        assert max_sector == config.MAX_SECTOR_SIZE_PCT

        cash_min, cash_max = _extraer(
            text,
            r"Reserva de Supervivencia \(Cash\):\*\* Mantener siempre entre el \*\*(\d+(?:\.\d+)?)% y el (\d+(?:\.\d+)?)% en liquidez",
            doc=self.DOC,
        )
        assert cash_min == config.MIN_CASH_PCT
        assert cash_max == config.MAX_CASH_PCT


class TestPoliticaControlRiesgo:
    """`vault/03_Mesa_Cuantitativa_Riesgo/Politica_Control_Riesgo.md`."""

    DOC = "03_Mesa_Cuantitativa_Riesgo/Politica_Control_Riesgo.md"

    def test_limites_cuantitativos(self) -> None:
        text = _read_normalizado(self.DOC)

        (max_pos,) = _extraer(
            text, r"Límite de Concentración Individual:\*\* Máximo \*\*(\d+(?:\.\d+)?)%", doc=self.DOC
        )
        assert max_pos == config.MAX_POSITION_SIZE_PCT

        (max_sector,) = _extraer(text, r"Límite Sectorial:\*\* Máximo \*\*(\d+(?:\.\d+)?)%", doc=self.DOC)
        assert max_sector == config.MAX_SECTOR_SIZE_PCT

        (cash_min,) = _extraer(
            text, r"Reserva de Liquidez \(Cash\):\*\* Mínimo \*\*(\d+(?:\.\d+)?)%", doc=self.DOC
        )
        assert cash_min == config.MIN_CASH_PCT

    def test_escalera_de_contingencia(self) -> None:
        text = _read_normalizado(self.DOC)

        (optimo,) = _extraer(text, r"Drawdown < (\d+(?:\.\d+)?)% \(Estado Óptimo\)", doc=self.DOC)
        assert optimo == config.DRAWDOWN_OPTIMO_MAX_PCT

        alerta_lo, alerta_hi = _extraer(
            text, r"Drawdown (\d+(?:\.\d+)?)% - (\d+(?:\.\d+)?)% \(Estado Alerta\)", doc=self.DOC
        )
        assert alerta_lo == config.DRAWDOWN_OPTIMO_MAX_PCT
        assert alerta_hi == config.DRAWDOWN_ALERTA_MAX_PCT

        ci_lo, ci_hi = _extraer(
            text, r"Drawdown (\d+(?:\.\d+)?)% - (\d+(?:\.\d+)?)% \(Cuidados Intensivos\)", doc=self.DOC
        )
        assert ci_lo == config.DRAWDOWN_ALERTA_MAX_PCT
        assert ci_hi == config.DEATH_DRAWDOWN_PCT

        (muerte,) = _extraer(
            text, r"Drawdown > (\d+(?:\.\d+)?)% \(Muerte / Liquidación\)", doc=self.DOC
        )
        assert muerte == config.DEATH_DRAWDOWN_PCT


class TestMandatoInstitucional:
    """`vault/00_Comite_Direccion/Mandato_Institucional.md`."""

    DOC = "00_Comite_Direccion/Mandato_Institucional.md"

    def test_escalera_de_drawdown_citada_en_el_mandato(self) -> None:
        text = _read_normalizado(self.DOC)

        (optimo,) = _extraer(text, r"Óptimo hasta (\d+(?:\.\d+)?)%", doc=self.DOC)
        assert optimo == config.DRAWDOWN_OPTIMO_MAX_PCT

        alerta_lo, alerta_hi = _extraer(
            text, r"Alerta (\d+(?:\.\d+)?)%-(\d+(?:\.\d+)?)%", doc=self.DOC
        )
        assert alerta_lo == config.DRAWDOWN_OPTIMO_MAX_PCT
        assert alerta_hi == config.DRAWDOWN_ALERTA_MAX_PCT

        ci_lo, ci_hi = _extraer(
            text, r"Cuidados Intensivos (\d+(?:\.\d+)?)%-(\d+(?:\.\d+)?)%", doc=self.DOC
        )
        assert ci_lo == config.DRAWDOWN_ALERTA_MAX_PCT
        assert ci_hi == config.DEATH_DRAWDOWN_PCT

        (muerte,) = _extraer(
            text, r"pérdida del (\d+(?:\.\d+)?)% se considera el umbral de liquidación/muerte", doc=self.DOC
        )
        assert muerte == config.DEATH_DRAWDOWN_PCT

    def test_liquidez_estrategica(self) -> None:
        text = _read_normalizado(self.DOC)

        cash_min, cash_max = _extraer(
            text, r"entre el (\d+(?:\.\d+)?)% y el (\d+(?:\.\d+)?)% en efectivo", doc=self.DOC
        )
        assert cash_min == config.MIN_CASH_PCT
        assert cash_max == config.MAX_CASH_PCT
