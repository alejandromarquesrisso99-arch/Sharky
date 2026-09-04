"""
Utilidades de consola.

Sharky imprime euros, emojis y acentos. En Windows la consola usa cp1252 por
defecto, que no puede codificar ni `€` ni `🔄`: sin esta corrección cualquier
salida revienta con `UnicodeEncodeError`. Se aplica en todos los puntos de
entrada (CLI y scripts), no sólo en uno.
"""

import sys


def enable_utf8() -> None:
    """Fuerza UTF-8 en stdout/stderr de forma idempotente y sin fallar nunca."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            # `reconfigure` existe en `io.TextIOWrapper` (el caso real en
            # ejecución normal) pero no en el protocolo abstracto `TextIO`
            # con el que typeshed tipa `sys.stdout`/`sys.stderr` -- de ahí el
            # ignore. El try/except ya cubre en runtime el caso en que el
            # flujo esté redirigido a algo sin este método.
            flujo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            # Flujo redirigido o no reconfigurable: se deja como está.
            pass
