"""
Comprueba que el ciclo diario de Sharky sigue corriendo con normalidad.

Contexto
--------
Sharky no es un servicio permanente: se lanza una vez al iniciar sesión
(ver `instalar_inicio_windows.ps1`) y cada ciclo que termina bien actualiza
`ultima_actualizacion` en `Estado_Vital.md` vía
`VaultManager.update_health_status()`. Ese timestamp ya es, de hecho, un
heartbeat -- lo único que faltaba era algo que lo comprobara y avisara si
deja de refrescarse. Sin esto, un fallo silencioso del Task Scheduler
(entorno virtual roto, red caída, una excepción no capturada) simplemente
deja de aparecer en pantalla, y nadie se entera hasta que alguien abre el
vault a propósito -- que es justo el tipo de brecha operativa que más
tiempo tarda en descubrirse.

Qué hace
--------
Lee `ultima_actualizacion` y devuelve código de salida 1 (con un mensaje
por stdout) si lleva más de `--max-horas` sin refrescarse, o si el fichero
nunca se ha escrito. Código 0 si está fresco. Pensado para una tarea
programada aparte de `SharkyStartup` (ver
`instalar_heartbeat_windows.ps1`), que puede reaccionar al código de salida
sin tener que parsear la salida.

Uso:
    python scripts/check_heartbeat.py
    python scripts/check_heartbeat.py --max-horas 48
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sharky.config import VAULT_PATH  # noqa: E402
from sharky.vault_manager import VaultManager  # noqa: E402


def horas_desde_el_ultimo_ciclo(vault_path: Path = VAULT_PATH) -> float:
    """Horas transcurridas desde `ultima_actualizacion` de Estado_Vital.md.

    `float("inf")` si el fichero no existe o nunca se ha escrito: eso
    también cuenta como "obsoleto", no como "no aplica".
    """
    salud = VaultManager(vault_path).read_health_status()
    if salud.ultima_actualizacion == datetime.min:
        return float("inf")
    delta = datetime.now() - salud.ultima_actualizacion
    return delta.total_seconds() / 3600.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-horas",
        type=float,
        default=36.0,
        help=(
            "Antigüedad máxima admisible del último ciclo antes de avisar "
            "(por defecto 36h: un día de margen sobre el ciclo diario para "
            "un arranque tardío del ordenador, sin dejar pasar dos días)."
        ),
    )
    args = parser.parse_args()

    horas = horas_desde_el_ultimo_ciclo()

    if horas == float("inf"):
        print("[Sharky] ALERTA: Estado_Vital.md no existe o nunca se ha escrito.")
        return 1

    if horas > args.max_horas:
        print(
            f"[Sharky] ALERTA: el último ciclo se completó hace {horas:.1f} horas "
            f"(máximo admitido: {args.max_horas:.0f}h). Revisa logs\\sharky_startup.log "
            "y comprueba que la tarea 'SharkyStartup' sigue registrada "
            "(schtasks /query /tn SharkyStartup)."
        )
        return 1

    print(f"[Sharky] OK: último ciclo hace {horas:.1f} horas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
