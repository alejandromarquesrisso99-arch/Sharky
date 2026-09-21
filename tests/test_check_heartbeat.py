"""
Tests de `scripts/check_heartbeat.py`.

El propio motor (`VaultManager.update_health_status`) ya escribe
`ultimo_ciclo_diario` en cada ciclo; lo único que aporta este script es
comprobarlo y avisar si está obsoleto. Estos tests cubren exactamente esa
lógica -- no repiten lo que ya prueba `TestBoveda` sobre `Estado_Vital.md`.
"""

from datetime import datetime, timedelta

from sharky.vault_manager import VaultManager

from scripts.check_heartbeat import horas_desde_el_ultimo_ciclo


class TestHeartbeat:
    def test_boveda_nueva_es_infinitamente_obsoleta(self, tmp_path):
        """Sin Estado_Vital.md, debe tratarse como obsoleto, no como "no aplica"."""
        assert horas_desde_el_ultimo_ciclo(tmp_path) == float("inf")

    def test_heartbeat_recien_escrito_esta_fresco(self, tmp_path):
        vm = VaultManager(tmp_path)
        vm.health_path.write_text(
            vm.build_markdown({"ultima_actualizacion": datetime.now().isoformat()}, "# x\n"),
            encoding="utf-8",
        )
        assert horas_desde_el_ultimo_ciclo(tmp_path) < 0.01

    def test_heartbeat_antiguo_se_refleja_en_las_horas_transcurridas(self, tmp_path):
        vm = VaultManager(tmp_path)
        hace_40h = datetime.now() - timedelta(hours=40)
        vm.health_path.write_text(
            vm.build_markdown({"ultima_actualizacion": hace_40h.isoformat()}, "# x\n"),
            encoding="utf-8",
        )
        horas = horas_desde_el_ultimo_ciclo(tmp_path)
        assert 39.9 < horas < 40.1

    def test_una_operacion_registrada_no_tapa_un_ciclo_caido(self, tmp_path):
        """`sharky trade` refresca `ultima_actualizacion` pero no
        `ultimo_ciclo_diario`: registrar una operación el día en que el
        arranque falló no debe hacer pasar el heartbeat por bueno."""
        vm = VaultManager(tmp_path)
        hace_40h = datetime.now() - timedelta(hours=40)
        vm.health_path.write_text(
            vm.build_markdown(
                {
                    "ultima_actualizacion": datetime.now().isoformat(),
                    "ultimo_ciclo_diario": hace_40h.isoformat(),
                },
                "# x\n",
            ),
            encoding="utf-8",
        )
        horas = horas_desde_el_ultimo_ciclo(tmp_path)
        assert 39.9 < horas < 40.1
