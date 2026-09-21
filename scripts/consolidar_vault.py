"""
Consolidación de notas duplicadas de la bóveda.

Problema
--------
La bóveda contenía dos notas para varios activos: una con el nombre descriptivo
(1,5-2 KB de análisis y 13-16 enlaces entrantes) y otra con el ticker (un stub de
200 bytes que sólo redirigía). Los `[[wikilinks]]` apuntaban a mitades distintas,
así que el grafo de Obsidian quedaba partido en dos y ninguna de las dos notas
mostraba el conjunto real de relaciones.

Criterio
--------
Gana la nota que **contiene el análisis**, no la que tiene el nombre más corto.
El nombre eliminado se conserva como `aliases` en la nota canónica, para que
Obsidian la sugiera al enlazar. Un `[[RHM]]` escrito tal cual NO resuelve por
alias: eso lo corrige `reparar_enlaces_vault.py` (2026-09).

El código sigue identificando los activos por su ticker: la correspondencia
ticker → nota vive en el campo `nota_activo` del libro de posiciones.

Uso:
    python scripts/consolidar_vault.py [--dry-run]
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sharky.console import enable_utf8  # noqa: E402

enable_utf8()

from sharky.config import VAULT_PATH  # noqa: E402
from sharky.vault_manager import VaultManager  # noqa: E402

# stub_a_eliminar -> nota_canonica_que_conserva_el_contenido
FUSIONES: Dict[str, str] = {
    "RHM": "Rheinmetall",
    "LMT": "Lockheed_Martin",
    "BLK": "BlackRock",
    "URNU": "Uranio",
    "Uranium": "Uranio",
    "Tesis_RHM": "Tesis_Rheinmetall",
    "Tesis_LMT": "Tesis_Lockheed_Martin",
    "Tesis_MSFT": "Tesis_Microsoft",
    "Tesis_URNU": "Tesis_Uranium_GlobalX",
    "BTC": "Bitcoin",
    "MP": "Rare_Earths",
    "CCJ": "Uranio",
}

# nombre_actual -> nombre_nuevo (se conserva el contenido, cambia el archivo)
RENOMBRADOS: Dict[str, str] = {
    # "_Ejemplo" era un resto de la plantilla de fábrica: esta tesis ya es real.
    "Tesis_NVDA_Ejemplo": "Tesis_NVDA",
}

# Archivos generados por una plantilla sin resolver.
BASURA = ["{{TICKER}}.md"]


def localizar(nombre: str) -> List[Path]:
    return [p for p in VAULT_PATH.rglob(f"{nombre}.md")]


def añadir_alias(ruta: Path, alias: List[str], dry: bool) -> None:
    """Registra nombres alternativos en el frontmatter de la nota canónica."""
    vault = VaultManager(VAULT_PATH)
    meta, cuerpo = vault.parse_markdown(ruta.read_text(encoding="utf-8"))
    existentes = meta.get("aliases") or []
    if isinstance(existentes, str):
        existentes = [existentes]
    nuevos = [a for a in alias if a not in existentes and a != ruta.stem]
    if not nuevos:
        return
    # `alias` (singular) lo usaban los stubs para apuntar al canónico; se
    # descarta para que no quede un puntero circular.
    meta.pop("alias", None)
    meta["aliases"] = existentes + nuevos
    if not dry:
        ruta.write_text(vault.build_markdown(meta, cuerpo), encoding="utf-8")
    print(f"   alias en {ruta.name}: +{nuevos}")


def reescribir_enlaces(sustituciones: Dict[str, str], dry: bool) -> int:
    """Reapunta los wikilinks al nombre canónico, preservando alias y anclas."""
    total = 0
    for ruta in sorted(VAULT_PATH.rglob("*.md")):
        texto = original = ruta.read_text(encoding="utf-8")
        for viejo, nuevo in sustituciones.items():
            # Coincide con [[viejo]], [[viejo|etiqueta]] y [[viejo#ancla]],
            # exigiendo que el objetivo sea exacto para no tocar [[Tesis_RHM]]
            # al sustituir [[RHM]].
            patron = re.compile(r"\[\[" + re.escape(viejo) + r"(?=[\]|#])")
            texto = patron.sub(f"[[{nuevo}", texto)
        if texto != original:
            total += 1
            if not dry:
                ruta.write_text(texto, encoding="utf-8")
            print(f"   enlaces actualizados: {ruta.relative_to(VAULT_PATH)}")
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Muestra los cambios sin aplicarlos")
    args = parser.parse_args()
    dry = args.dry_run

    print("🧹 CONSOLIDACIÓN DEL GRAFO DE OBSIDIAN" + ("  [SIMULACIÓN]" if dry else ""))

    # 1. Renombrados (se hacen primero: liberan el nombre destino).
    print("\n1. Renombrando notas con nombre heredado:")
    for viejo, nuevo in RENOMBRADOS.items():
        origen = localizar(viejo)
        if not origen:
            print(f"   • {viejo}: no existe, nada que hacer.")
            continue
        origen = origen[0]
        destino = origen.parent / f"{nuevo}.md"
        if destino.exists():
            print(f"   • {destino.name} existe (stub): se elimina para liberar el nombre.")
            if not dry:
                destino.unlink()
        print(f"   • {origen.name} → {destino.name}")
        if not dry:
            origen.rename(destino)

    # 2. Fusiones: alias en el canónico y borrado del stub.
    print("\n2. Fusionando duplicados:")
    fusionadas: Dict[str, str] = {}
    for stub, canonico in FUSIONES.items():
        rutas_canonico = localizar(canonico)
        rutas_stub = localizar(stub)
        if not rutas_canonico:
            print(f"   ⚠️  {canonico} no existe: se conserva {stub} sin cambios.")
            continue
        if not rutas_stub:
            print(f"   • {stub}: ya no existe.")
            fusionadas[stub] = canonico
            continue
        print(f"   • {stub} → {canonico}")
        añadir_alias(rutas_canonico[0], [stub], dry)
        if not dry:
            for r in rutas_stub:
                r.unlink()
        fusionadas[stub] = canonico

    # 3. Reapuntar todos los wikilinks.
    print("\n3. Reapuntando wikilinks:")
    sustituciones = dict(fusionadas)
    sustituciones.update(RENOMBRADOS)
    tocados = reescribir_enlaces(sustituciones, dry)
    if tocados == 0:
        print("   • Nada que reapuntar.")

    # 4. Basura de plantillas.
    print("\n4. Eliminando artefactos de plantilla:")
    for nombre in BASURA:
        for ruta in VAULT_PATH.rglob(nombre):
            print(f"   • {ruta.relative_to(VAULT_PATH)}")
            if not dry:
                ruta.unlink()

    print(f"\n{'✅ Simulación completada (no se escribió nada).' if dry else '✅ Consolidación aplicada.'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
