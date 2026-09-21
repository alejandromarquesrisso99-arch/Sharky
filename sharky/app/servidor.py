"""
Servidor HTTP local de la app de Sharky.

Sólo librería estándar (`http.server`): Sharky ya depende de lo justo y una
app de un único usuario en local no necesita un framework. Escucha en
127.0.0.1 por defecto.

Seguridad, aunque sea local: cualquier web abierta en el navegador puede
intentar peticiones a `http://127.0.0.1:<puerto>`. Para que ninguna pueda
leer la cartera ni lanzar acciones que cuestan dinero o registrar
operaciones:

  * Cada arranque genera un token aleatorio que sólo va dentro de la
    página servida por la propia app; toda llamada a `/api/` lo exige en la
    cabecera `X-Sharky-Token` (una web ajena no puede leerlo ni enviar esa
    cabecera sin permiso CORS, que nunca se da).
  * La cabecera `Host` debe ser la de la propia app (frena el DNS
    rebinding).
  * CSP estricta: sólo scripts y estilos propios.
"""

import argparse
import json
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess  # nosec B404 -- sólo abre el navegador local, ver abrir_ventana
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

from sharky.console import enable_utf8

enable_utf8()

from sharky.app import datos  # noqa: E402
from sharky.app.trabajos import ACCIONES, GestorTrabajos, OcupadoError, Trabajo  # noqa: E402
from sharky.models import AssetClass, OrderType  # noqa: E402
from sharky import primer_arranque  # noqa: E402

PUERTO_DEFECTO = int(os.getenv("SHARKY_APP_PORT", "8765"))
HOST_DEFECTO = "127.0.0.1"
ESTATICOS = Path(__file__).resolve().parent / "static"
MAX_CUERPO = 64 * 1024
CACHE_PANEL_SEGUNDOS = 120


class ErrorPeticion(Exception):
    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


class EstadoApp:
    """Estado compartido entre peticiones: agente del panel, trabajos y caché."""

    def __init__(self, fabrica_agente: Optional[Callable[[], Any]] = None, token: Optional[str] = None):
        if fabrica_agente is None:
            from sharky.agent_loop import SharkyAgent
            fabrica_agente = SharkyAgent
        self.fabrica_agente = fabrica_agente
        self.token = token or secrets.token_urlsafe(24)
        self.iniciado = datetime.now()
        self._agente = None
        # El agente del panel no es seguro entre hilos (caché de precios,
        # lecturas de la bóveda): una petición a la vez.
        self.lock_agente = threading.RLock()
        self._panel: Optional[Dict[str, Any]] = None
        self._panel_instante = 0.0
        self.trabajos = GestorTrabajos(fabrica_agente, al_terminar=self._al_terminar_trabajo)
        self.apagar: Optional[Callable[[], None]] = None

    def agente(self):
        with self.lock_agente:
            if self._agente is None:
                self._agente = self.fabrica_agente()
            return self._agente

    def _al_terminar_trabajo(self, _trabajo: Trabajo) -> None:
        self.invalidar_panel()

    def invalidar_panel(self) -> None:
        with self.lock_agente:
            self._panel = None

    def panel(self, refrescar: bool = False) -> Dict[str, Any]:
        with self.lock_agente:
            fresco = time.monotonic() - self._panel_instante < CACHE_PANEL_SEGUNDOS
            if self._panel is None or refrescar or not fresco:
                agente = self.agente()
                if refrescar:
                    # Precios de verdad nuevos, no los de la caché del proveedor.
                    cache = getattr(agente.market, "_cache", None)
                    if isinstance(cache, dict):
                        cache.clear()
                self._panel = datos.construir_panel(agente)
                self._panel_instante = time.monotonic()
            return self._panel

    # ------------------------------------------------------------------
    def registrar_operacion(self, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
        from sharky.trade_ledger import TradeRecorder

        def numero(clave: str, obligatorio: bool = False) -> float:
            valor = cuerpo.get(clave)
            if valor in (None, ""):
                if obligatorio:
                    raise ErrorPeticion(400, f"Falta «{clave}».")
                return 0.0
            try:
                return float(str(valor).replace(",", "."))
            except ValueError:
                raise ErrorPeticion(400, f"«{clave}» no es un número válido.")

        def texto(clave: str) -> Optional[str]:
            valor = str(cuerpo.get(clave) or "").strip()
            return valor or None

        tipo = str(cuerpo.get("tipo", "")).upper()
        if tipo not in ("COMPRA", "VENTA"):
            raise ErrorPeticion(400, "El tipo debe ser COMPRA o VENTA.")
        ticker = (texto("ticker") or "").upper()
        if not ticker:
            raise ErrorPeticion(400, "Falta el ticker.")
        clase = (texto("clase") or "ACCION").upper()
        if clase not in AssetClass.__members__:
            raise ErrorPeticion(400, f"Clase de activo desconocida: {clase}.")

        with self.lock_agente:
            agente = self.agente()
            recorder = TradeRecorder(
                store=agente.store, valuator=agente.valuator, governor=agente.risk,
                vault=agente.vault, fx=agente.fx, market=agente.market,
            )
            resultado = recorder.record(
                ticker=ticker,
                tipo_orden=OrderType(tipo),
                unidades=numero("unidades", obligatorio=True),
                precio=numero("precio", obligatorio=True),
                divisa=texto("divisa"),
                divisa_niveles=texto("divisa_niveles"),
                comision_eur=numero("comision"),
                stop_loss=numero("stop"),
                target_precio=numero("target"),
                tesis_referencia=texto("tesis") or "",
                justificacion=texto("motivo") or "",
                nombre=texto("nombre"),
                isin=texto("isin"),
                ticker_cotizacion=texto("simbolo"),
                clase=AssetClass[clase],
                sector=texto("sector") or "",
                forzar=bool(cuerpo.get("forzar")),
            )
            if resultado.aprobada:
                self._panel = None
        return {
            "aprobada": resultado.aprobada,
            "motivo": resultado.motivo,
            "nav_posterior": resultado.nav_posterior_eur,
            "efectivo_posterior": resultado.efectivo_posterior_eur,
            "pnl_realizado": resultado.pnl_realizado_eur,
            "nota": (
                Path(resultado.nota_operacion).name if resultado.nota_operacion else None
            ),
            # Consecuencias sobre el ciclo de vida de la convicción: la app las
            # enseña para que registrar una venta no parezca dejar viva una
            # tesis que ya no tiene posición detrás.
            "tesis_abierta": (
                Path(resultado.tesis_abierta).name if resultado.tesis_abierta else None
            ),
            "tesis_cerrada": (
                Path(resultado.tesis_cerrada).name if resultado.tesis_cerrada else None
            ),
            "alerta_actualizada": (
                Path(resultado.alerta_actualizada).name
                if resultado.alerta_actualizada else None
            ),
        }


def _crear_manejador(app: EstadoApp, puerto: int):
    hosts_validos = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}

    class Manejador(BaseHTTPRequestHandler):
        server_version = "Sharky"
        sys_version = ""

        def log_message(self, formato: str, *args: Any) -> None:  # silencio
            return

        # -------------------------------------------------------------
        def _enviar(self, estado: int, cuerpo: bytes, tipo: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _json(self, estado: int, datos_: Any) -> None:
            cuerpo = json.dumps(datos_, ensure_ascii=False, default=str).encode("utf-8")
            self._enviar(estado, cuerpo, "application/json; charset=utf-8")

        def _comprobar_host(self) -> None:
            if self.headers.get("Host", "") not in hosts_validos:
                raise ErrorPeticion(403, "Host no permitido.")

        def _comprobar_token(self) -> None:
            recibido = self.headers.get("X-Sharky-Token", "")
            if not secrets.compare_digest(recibido, app.token):
                raise ErrorPeticion(401, "Token de sesión no válido. Recarga la app.")

        def _leer_json(self) -> Dict[str, Any]:
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise ErrorPeticion(415, "Se esperaba JSON.")
            longitud = int(self.headers.get("Content-Length") or 0)
            if longitud > MAX_CUERPO:
                raise ErrorPeticion(413, "Petición demasiado grande.")
            try:
                datos_ = json.loads(self.rfile.read(longitud) or b"{}")
            except json.JSONDecodeError:
                raise ErrorPeticion(400, "JSON no válido.")
            if not isinstance(datos_, dict):
                raise ErrorPeticion(400, "Se esperaba un objeto JSON.")
            return datos_

        # -------------------------------------------------------------
        def do_GET(self) -> None:
            self._atender(self._get)

        def do_POST(self) -> None:
            self._atender(self._post)

        def _atender(self, funcion) -> None:
            try:
                self._comprobar_host()
                funcion(urlparse(self.path))
            except ErrorPeticion as e:
                self._json(e.estado, {"error": e.mensaje})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # nunca tumbar el servidor por una petición
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def _get(self, url) -> None:
            ruta = url.path
            if ruta in ("/", "/index.html"):
                html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
                html = html.replace("%%SHARKY_TOKEN%%", app.token)
                csp = (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'none'"
                )
                self._enviar(200, html.encode("utf-8"), "text/html; charset=utf-8",
                             {"Content-Security-Policy": csp})
                return
            if ruta.startswith("/static/"):
                self._estatico(ruta[len("/static/"):])
                return
            if ruta == "/api/salud":
                # Sin token: sólo sirve para que un segundo arranque sepa que
                # ya hay una app escuchando en este puerto.
                self._json(200, {"app": "sharky"})
                return
            if not ruta.startswith("/api/"):
                raise ErrorPeticion(404, "No encontrado.")

            self._comprobar_token()
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if ruta == "/api/panel":
                self._json(200, app.panel(refrescar=q.get("refrescar") == "1"))
            elif ruta == "/api/informes":
                tipo = q.get("tipo", "diario")
                try:
                    agente = app.agente()
                    self._json(200, {
                        "tipos": {k: v[2] for k, v in datos.TIPOS_INFORME.items()},
                        "tipo": tipo,
                        "notas": datos.listar_informes(agente.vault, tipo),
                    })
                except KeyError:
                    raise ErrorPeticion(400, f"Tipo de informe desconocido: {tipo}.")
            elif ruta == "/api/nota":
                vault = app.agente().vault
                nota_id = q.get("id") or (datos.buscar_nota(vault, q.get("nombre", "")) or "")
                if not nota_id:
                    raise ErrorPeticion(404, f"No existe la nota «{q.get('nombre', '')}».")
                try:
                    self._json(200, datos.leer_nota(vault, nota_id))
                except ValueError:
                    raise ErrorPeticion(403, "Ruta no permitida.")
                except FileNotFoundError:
                    raise ErrorPeticion(404, "No existe esa nota.")
            elif ruta == "/api/trabajos":
                actual = app.trabajos.actual
                self._json(200, {
                    "acciones": [
                        {"clave": a.clave, "titulo": a.titulo, "descripcion": a.descripcion,
                         "usa_claude": a.usa_claude, "coste": a.coste}
                        for a in ACCIONES.values()
                    ],
                    "actual": actual.a_dict() if actual else None,
                    "historial": [
                        {k: v for k, v in t.a_dict().items() if k not in ("log", "resultado")}
                        for t in list(app.trabajos.historial)
                    ],
                })
            elif ruta == "/api/sistema":
                info = datos.info_sistema(app.agente().vault.vault_path)
                info["iniciado"] = app.iniciado.isoformat(timespec="seconds")
                self._json(200, info)
            else:
                raise ErrorPeticion(404, "No encontrado.")

        def _post(self, url) -> None:
            self._comprobar_token()
            cuerpo = self._leer_json()
            ruta = url.path
            if ruta == "/api/trabajos":
                try:
                    trabajo = app.trabajos.lanzar(str(cuerpo.get("accion", "")))
                except KeyError:
                    raise ErrorPeticion(400, "Acción desconocida.")
                except OcupadoError as e:
                    raise ErrorPeticion(409, str(e))
                self._json(202, trabajo.a_dict())
            elif ruta == "/api/operaciones":
                if app.trabajos.en_curso():
                    raise ErrorPeticion(409, "Espera a que termine la acción en curso.")
                self._json(200, app.registrar_operacion(cuerpo))
            elif ruta == "/api/sistema/apagar":
                self._json(200, {"ok": True})
                if app.apagar:
                    threading.Timer(0.3, app.apagar).start()
            else:
                raise ErrorPeticion(404, "No encontrado.")

        def _estatico(self, nombre: str) -> None:
            ruta = (ESTATICOS / nombre).resolve()
            if ESTATICOS not in ruta.parents or not ruta.is_file() or ruta.name == "index.html":
                raise ErrorPeticion(404, "No encontrado.")
            tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/javascript", "image/svg+xml"):
                tipo += "; charset=utf-8"
            self._enviar(200, ruta.read_bytes(), tipo)

    return Manejador


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------
def _ya_escuchando(puerto: int) -> bool:
    """True si en ese puerto ya hay una app de Sharky."""
    try:
        with socket.create_connection((HOST_DEFECTO, puerto), timeout=0.5) as s:
            s.sendall(f"GET /api/salud HTTP/1.1\r\nHost: 127.0.0.1:{puerto}\r\nConnection: close\r\n\r\n".encode())
            return b'"sharky"' in s.recv(4096)
    except OSError:
        return False


def _navegador_app() -> Optional[str]:
    """Edge o Chrome, para abrir la app en una ventana propia sin barra."""
    candidatos = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return next((c for c in candidatos if c and Path(c).exists()), None)


def abrir_ventana(url: str) -> None:
    navegador = _navegador_app()
    if navegador:
        try:
            # Sin shell, y el ejecutable sale de la lista fija de `_navegador_app`
            # (Edge o Chrome); la URL es la de este mismo servidor en 127.0.0.1.
            subprocess.Popen([navegador, f"--app={url}", "--window-size=1440,920"])  # nosec B603
            return
        except OSError:
            pass
    webbrowser.open(url)


def crear_servidor(app: EstadoApp, host: str = HOST_DEFECTO, puerto: int = PUERTO_DEFECTO) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer((host, puerto), _crear_manejador(app, puerto))
    servidor.daemon_threads = True
    app.apagar = servidor.shutdown
    return servidor


def _primer_arranque(argv: list) -> int:
    """Sin libro de posiciones la app no tiene nada que mostrar: se configura
    Sharky primero."""
    if primer_arranque.es_interactivo():
        # `python -m sharky.app` desde una terminal: se pregunta ahí mismo.
        if not primer_arranque.asistente():
            return 1
        return primer_arranque.relanzar("sharky.app", argv)
    # Acceso directo (pythonw): no hay consola donde preguntar, se abre una.
    if primer_arranque.abrir_asistente_en_consola():
        return 0
    print("[Sharky] Todavía no está configurado: ejecuta `python -m sharky.cli init`.")
    return 2


def main(argv: Optional[list] = None) -> int:
    if primer_arranque.falta_configurar():
        return _primer_arranque(list(sys.argv[1:] if argv is None else argv))

    parser = argparse.ArgumentParser(prog="sharky app", description="App de gestión de Sharky")
    parser.add_argument("--puerto", type=int, default=PUERTO_DEFECTO)
    parser.add_argument("--no-abrir", action="store_true", help="No abrir la ventana de la app")
    args = parser.parse_args(argv)

    url = f"http://127.0.0.1:{args.puerto}/"
    if _ya_escuchando(args.puerto):
        print(f"[Sharky] La app ya está en marcha: {url}")
        if not args.no_abrir:
            abrir_ventana(url)
        return 0

    app = EstadoApp()
    try:
        servidor = crear_servidor(app, puerto=args.puerto)
    except OSError as exc:
        print(f"[Sharky] No se pudo abrir el puerto {args.puerto}: {exc}")
        return 1

    print(f"[Sharky] App en {url}  (Ctrl+C o «Apagar» en Sistema para cerrarla)")
    if not args.no_abrir:
        threading.Timer(0.6, abrir_ventana, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    print("[Sharky] App detenida.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
