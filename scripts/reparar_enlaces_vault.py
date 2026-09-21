"""
Reparación de los enlaces rotos de la bóveda.

Problema
--------
Hasta 2026-09 el texto que redacta Claude se guardaba tal cual, y el prompt le
pide enlazar por ticker: `[[RHM]]`, `[[URNU]]`, `[[BTC]]`... Las fichas no
siempre se llaman como su ticker (`Rheinmetall`, `Uranio`, `Bitcoin`), así que
cada diario, estudio y escaneo semanal dejaba enlaces que no llevaban a ningún
sitio. Además, ninguna ficha ni nota de sector se creaba sola: una posición
abierta con `sharky trade` (INDRA), una alerta del radar (LDO, CCJ, GEV) o un
sector nuevo (Agua, Defensa_Naval...) quedaban enlazados a notas inexistentes.
`test_obsidian_graph_integrity` estaba en rojo por eso.

Desde el mismo cambio, `VaultManager` lo evita al escribir
(`normalizar_enlaces`, `asegurar_ficha`, `asegurar_sector`). Este script
aplica lo mismo a lo que ya estaba escrito:

  1. Crea la ficha de cada posición de `Cartera_Real` y de cada alerta activa
     que no la tenga, y la nota de cada sector enlazado que falte.
  2. Pasa `normalizar_enlaces` por todas las notas menos las plantillas: un
     ticker con ficha pasa a `[[Ficha|TICKER]]`, que se lee igual, y lo que no
     resuelve a nada queda como texto plano.

Idempotente: una segunda ejecución no cambia nada. La bóveda está versionada,
así que el resultado se revisa con `git diff vault/`.

Uso:
    python scripts/reparar_enlaces_vault.py
"""

import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sharky.console import enable_utf8  # noqa: E402

enable_utf8()

from sharky.atomic_io import atomic_write_text  # noqa: E402
from sharky.config import VAULT_PATH  # noqa: E402
from sharky.portfolio import PortfolioStore  # noqa: E402
from sharky.vault_manager import VaultManager  # noqa: E402

# Destino de cada wikilink de un campo como `sectores: '[[Defensa]], [[Espacio]]'`.
_DESTINO = re.compile(r"\[\[([^\[\]|#\n]+)")


def crear_notas_que_faltan(vm: VaultManager) -> List[Path]:
    """Fichas de posiciones y alertas activas, y notas de sector enlazadas."""
    creadas: List[Optional[Path]] = []

    store = PortfolioStore(vm.vault_path)
    if store.exists():
        for p in store.load().posiciones:
            creadas.append(vm.asegurar_sector(p.sector))
            creadas.append(
                vm.asegurar_ficha(
                    p.ticker, p.nombre, p.sector,
                    origen="Cartera_Real", seguimiento="Activo_Cartera",
                )
            )

    for ruta, alerta in vm.list_active_alerts():
        creadas.append(vm.asegurar_ficha(alerta.ticker, alerta.empresa, origen=ruta.stem))

    for carpeta in ("01_Tesis_Activas", "02_Tesis_Cerradas"):
        for tesis in sorted((vm.vault_path / carpeta).glob("*.md")):
            meta, _ = vm.parse_markdown(tesis.read_text(encoding="utf-8"))
            for sector in _DESTINO.findall(str(meta.get("sectores") or "")):
                creadas.append(vm.asegurar_sector(sector))

    return [r for r in creadas if r is not None]


def normalizar_notas(vm: VaultManager) -> List[Path]:
    """Aplica `normalizar_enlaces` a cada nota; sólo reescribe las que cambian."""
    cambiadas: List[Path] = []
    for ruta in sorted(vm.vault_path.rglob("*.md")):
        if ".obsidian" in ruta.parts or "07_Plantillas" in ruta.parts:
            continue
        original = ruta.read_text(encoding="utf-8")
        nuevo = vm.normalizar_enlaces(original)
        if nuevo != original:
            atomic_write_text(ruta, nuevo, encoding="utf-8")
            cambiadas.append(ruta)
    return cambiadas


def main() -> int:
    vm = VaultManager(VAULT_PATH)

    creadas = crear_notas_que_faltan(vm)
    for ruta in creadas:
        print(f"[Sharky] Nota creada: {ruta.relative_to(vm.vault_path)}")

    cambiadas = normalizar_notas(vm)
    for ruta in cambiadas:
        print(f"[Sharky] Enlaces corregidos: {ruta.relative_to(vm.vault_path)}")

    print(
        f"[Sharky] {len(creadas)} nota(s) creada(s), "
        f"{len(cambiadas)} nota(s) con enlaces corregidos."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
