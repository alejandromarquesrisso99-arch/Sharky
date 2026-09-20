"""
Tests de la infraestructura de escritura: atomicidad y bloqueo de fichero.

Ver REVISION_2026-09-12.md, INFRA-2 e INFRA-4.
"""

from pathlib import Path

import pytest

from sharky.atomic_io import atomic_write_text
from sharky.file_lock import LockTimeoutError, exclusive_lock


class TestEscrituraAtomica:
    def test_escribe_el_contenido_y_no_deja_tmp_huerfano(self, tmp_path: Path):
        destino = tmp_path / "sub" / "nota.md"
        atomic_write_text(destino, "contenido inicial")

        assert destino.read_text(encoding="utf-8") == "contenido inicial"
        assert list(destino.parent.glob("*.tmp")) == []

    def test_sobrescribe_un_fichero_existente_por_completo(self, tmp_path: Path):
        destino = tmp_path / "nota.md"
        atomic_write_text(destino, "version 1")
        atomic_write_text(destino, "version 2, mas larga que la anterior")

        assert destino.read_text(encoding="utf-8") == "version 2, mas larga que la anterior"
        assert list(tmp_path.glob("*.tmp")) == []


class TestBloqueoDeFichero:
    def test_dos_adquisiciones_secuenciales_no_chocan(self, tmp_path: Path):
        destino = tmp_path / "Cartera_Real.md"
        with exclusive_lock(destino, timeout=1.0):
            pass
        with exclusive_lock(destino, timeout=1.0):
            pass
        assert not Path(str(destino) + ".lock").exists()

    def test_segunda_adquisicion_mientras_la_primera_sigue_activa_expira(self, tmp_path: Path):
        destino = tmp_path / "Cartera_Real.md"
        with exclusive_lock(destino, timeout=1.0):
            with pytest.raises(LockTimeoutError):
                with exclusive_lock(destino, timeout=0.2, poll_interval=0.05):
                    pass

    def test_tras_liberar_el_lock_una_tercera_adquisicion_funciona(self, tmp_path: Path):
        destino = tmp_path / "Cartera_Real.md"
        with exclusive_lock(destino, timeout=1.0):
            with pytest.raises(LockTimeoutError):
                with exclusive_lock(destino, timeout=0.2, poll_interval=0.05):
                    pass
        with exclusive_lock(destino, timeout=1.0):
            pass
        assert not Path(str(destino) + ".lock").exists()
