"""
Acciones largas de la app, en segundo plano y de una en una.

Un estudio mensual puede tardar minutos: la petición HTTP no puede
esperarlo. Cada acción corre en su propio hilo con su propio
`SharkyAgent` (no comparte la caché ni el estado del agente que sirve el
panel) y la interfaz consulta su estado cada poco.

Nunca hay dos acciones a la vez: dos ciclos escribiendo la bóveda y
`Estado_Vital.md` en paralelo es exactamente el tipo de carrera que el
resto de Sharky evita con escrituras atómicas y un único responsable por
nota.
"""

import io
import json
import sys
import threading
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional


@dataclass(frozen=True)
class Accion:
    clave: str
    titulo: str
    descripcion: str
    usa_claude: bool
    coste: str  # estimación orientativa, se enseña antes de confirmar
    ejecutar: Callable[[Any], Dict[str, Any]]


ACCIONES: Dict[str, Accion] = {
    a.clave: a
    for a in [
        Accion(
            "niveles", "Comprobar niveles",
            "Stop-loss y take-profit de las tesis abiertas con precios actuales.",
            False, "Gratis", lambda agent: agent.revisar_niveles_ahora(),
        ),
        Accion(
            "diario", "Control diario",
            "Valoración, niveles, radar y control del día por Claude "
            "(posiciones, precios, valor de mercado y normas).",
            True, "≈ 0,02–0,05 $", lambda agent: agent.run_daily_cycle(),
        ),
        Accion(
            "noticias", "Escaneo de noticias",
            "Busca en la web noticias de cada posición con el contexto de los "
            "últimos 7 controles diarios.",
            True, "≈ 0,70–1,10 $", lambda agent: agent.run_weekly_news_scan(),
        ),
        Accion(
            "estudio", "Estudio mensual",
            "Plan de rebalanceo del Día 1 y reevaluación de cada posición con "
            "todo el contexto del mes.",
            True, "≈ 0,50–1 $", lambda agent: agent.run_monthly_study(),
        ),
        Accion(
            "rebalanceo", "Plan de rebalanceo",
            "Sólo el plan determinista del motor de rebalanceo, sin Claude.",
            False, "Gratis", lambda agent: agent.generate_monthly_rebalance(),
        ),
        Accion(
            "comite", "Comité de inversión",
            "Las cuatro mesas y la resolución del CIO sobre el estado actual.",
            True, "≈ 0,20 $", lambda agent: agent.run_investment_committee(),
        ),
    ]
}


class SalidaPorHilo(io.TextIOBase):
    """`sys.stdout` que manda lo que imprime cada trabajo a su propio log.

    Sharky informa de problemas con `print` (p.ej. `[ClaudeBrain] Error en
    la llamada a la API...`). Sin esto, esos avisos acabarían en una
    consola que nadie ve en vez de en la app.
    """

    def __init__(self, original):
        super().__init__()
        self.original = original
        self._destinos: Dict[int, List[str]] = {}

    def capturar(self, destino: List[str]) -> None:
        self._destinos[threading.get_ident()] = destino

    def soltar(self) -> None:
        self._destinos.pop(threading.get_ident(), None)

    def write(self, texto: str) -> int:
        destino = self._destinos.get(threading.get_ident())
        if destino is not None:
            destino.append(texto)
        else:
            try:
                self.original.write(texto)
            except (OSError, ValueError, AttributeError):
                pass  # pythonw: no hay consola
        return len(texto)

    def flush(self) -> None:
        try:
            self.original.flush()
        except (OSError, ValueError, AttributeError):
            pass


def instalar_salida_por_hilo() -> SalidaPorHilo:
    if not isinstance(sys.stdout, SalidaPorHilo):
        sys.stdout = SalidaPorHilo(sys.stdout)
    return sys.stdout  # type: ignore[return-value]


@dataclass
class Trabajo:
    accion: Accion
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    estado: str = "en_curso"  # en_curso | ok | error
    inicio: datetime = field(default_factory=datetime.now)
    fin: Optional[datetime] = None
    log: List[str] = field(default_factory=list)
    resultado: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def a_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "accion": self.accion.clave,
            "titulo": self.accion.titulo,
            "estado": self.estado,
            "inicio": self.inicio.isoformat(timespec="seconds"),
            "fin": self.fin.isoformat(timespec="seconds") if self.fin else None,
            "log": "".join(self.log)[-20000:],
            # Pasa por JSON con `default=str` para que nada del resultado
            # (enums, fechas...) rompa la respuesta HTTP.
            "resultado": json.loads(json.dumps(self.resultado, default=str)) if self.resultado else None,
            "error": self.error,
        }


class OcupadoError(RuntimeError):
    pass


class GestorTrabajos:
    def __init__(
        self,
        fabrica_agente: Callable[[], Any],
        al_terminar: Optional[Callable[[Trabajo], None]] = None,
    ):
        self._fabrica = fabrica_agente
        self._al_terminar = al_terminar
        self._lock = threading.Lock()
        self.actual: Optional[Trabajo] = None
        self.historial: Deque[Trabajo] = deque(maxlen=25)
        self._salida = instalar_salida_por_hilo()

    def en_curso(self) -> Optional[Trabajo]:
        with self._lock:
            return self.actual if self.actual and self.actual.estado == "en_curso" else None

    def lanzar(self, clave: str) -> Trabajo:
        if clave not in ACCIONES:
            raise KeyError(clave)
        with self._lock:
            if self.actual and self.actual.estado == "en_curso":
                raise OcupadoError(f"Ya hay una acción en curso: {self.actual.accion.titulo}.")
            trabajo = Trabajo(accion=ACCIONES[clave])
            self.actual = trabajo
            self.historial.appendleft(trabajo)
        threading.Thread(target=self._ejecutar, args=(trabajo,), daemon=True, name=f"sharky-{clave}").start()
        return trabajo

    def _ejecutar(self, trabajo: Trabajo) -> None:
        self._salida.capturar(trabajo.log)
        try:
            agente = self._fabrica()
            trabajo.resultado = trabajo.accion.ejecutar(agente)
            trabajo.estado = "ok"
        except Exception as exc:
            trabajo.error = f"{type(exc).__name__}: {exc}"
            trabajo.log.append("\n" + traceback.format_exc())
            trabajo.estado = "error"
        finally:
            trabajo.fin = datetime.now()
            self._salida.soltar()
            if self._al_terminar:
                try:
                    self._al_terminar(trabajo)
                except Exception:
                    pass

    def buscar(self, trabajo_id: str) -> Optional[Trabajo]:
        with self._lock:
            return next((t for t in self.historial if t.id == trabajo_id), None)
