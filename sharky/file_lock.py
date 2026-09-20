"""
Bloqueo de fichero para escrituras concurrentes al libro de posiciones.

`Cartera_Real.md` puede recibir escrituras desde procesos distintos: el
servicio 24/7 (`sharky service`) y un `sharky trade` lanzado a mano al mismo
tiempo. Sin un mutex externo al proceso, un `load` -> modificar -> `save`
concurrente puede perder la escritura de uno de los dos. El lock vive como un
fichero `<destino>.lock` junto al libro: crearlo con `O_EXCL` es una operación
atómica del sistema de ficheros, tanto en Windows como en POSIX, así que sirve
de mutex entre procesos sin dependencias nuevas.
"""

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockTimeoutError(TimeoutError):
    """No se pudo adquirir el lock dentro del timeout dado."""


@contextmanager
def exclusive_lock(path: Path, timeout: float = 10.0, poll_interval: float = 0.05) -> Iterator[None]:
    """Mutex entre procesos basado en la creación exclusiva de `<path>.lock`."""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"No se pudo bloquear {path} tras {timeout}s: {lock_path} ya existe."
                )
            time.sleep(poll_interval)
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
