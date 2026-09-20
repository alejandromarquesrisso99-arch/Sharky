"""
Escritura atómica de ficheros de texto.

Un corte a mitad de escritura (fallo de disco, cierre forzado) no debe dejar
truncada una nota de la bóveda o el libro de posiciones: ambos son la fuente
de verdad. `os.replace` es atómico en el sistema de ficheros (POSIX y NTFS),
así que el fichero destino queda siempre en su versión anterior completa o en
la nueva completa, nunca a medias.
"""

import os
from pathlib import Path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Escribe `content` en `path` sin dejarlo nunca a medio escribir."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, path)
