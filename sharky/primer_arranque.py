"""
Primer arranque: configuración inicial para quien acaba de clonar Sharky.

La bóveda y el `.env` no viajan con el repositorio (es público; ver
.gitignore), así que quien clona Sharky empieza sin libro de posiciones y sin
clave de Claude. Hasta 2026-09 eso era un callejón sin salida: cualquier
comando se paraba pidiendo un `sharky portfolio --init` que nunca existió, y
la única forma de empezar era escribir `Cartera_Real.md` a mano, con un
formato que no estaba documentado.

El asistente pregunta sólo lo imprescindible y no escribe nada hasta que se
confirma el resumen final:

  1. La clave de la API de Claude, sin mostrarla en pantalla. Se guarda en
     `.env`; se puede dejar vacía y Sharky funciona en modo simulado.
  2. Las posiciones, desde un CSV con las columnas en un orden fijo
     (`COLUMNAS`): lo que cualquiera puede preparar en una hoja de cálculo o
     pedirle a Claude que saque del extracto de su bróker.
  3. El efectivo y el custodio.

Con eso crea el libro, una ficha mínima por posición y las notas índice de la
bóveda. Nunca sobrescribe un libro que ya existe.
"""

import csv
import getpass
import io
import os
import re
import subprocess  # nosec B404 -- sólo relanza el propio Sharky, ver `relanzar`
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from sharky import config
from sharky.atomic_io import atomic_write_text
from sharky.market_data import INSTRUMENT_REGISTRY
from sharky.models import AssetClass, Portfolio, Position
from sharky.portfolio import PortfolioStore
from sharky.vault_manager import (
    ENCABEZADO_FICHAS_NUEVAS,
    ENCABEZADO_SECTORES_NUEVOS,
    VaultManager,
)

# (nombre, obligatoria, qué va en ella). El ORDEN es el formato: el CSV se lee
# por posición, no por el nombre de la cabecera, que es opcional.
COLUMNAS: List[Tuple[str, bool, str]] = [
    ("ticker", True, "nombre corto de la posición; da nombre a su ficha (p. ej. MSFT)"),
    ("nombre", True, "nombre de la empresa o del fondo"),
    ("isin", False, "código ISIN; con él `resolve-isin` busca el símbolo de cotización"),
    ("unidades", True, "número de títulos, con decimales si los hay"),
    ("coste_medio_eur", True, "precio medio de compra por título, en euros"),
    ("divisa", True, "divisa en la que cotiza el activo: EUR, USD, GBp, HKD..."),
    ("sector", False, "sector, para el límite de concentración (p. ej. Tecnologia)"),
    ("simbolo", False, "símbolo de Yahoo Finance (p. ej. RHM.DE); vacío = se busca en el registro de Sharky"),
    ("clase", False, "ACCION (por defecto), ETF, ETC o CRIPTO"),
]
_MINIMO_COLUMNAS = 6  # hasta `divisa`, la última obligatoria

# Cifras ficticias: la plantilla está en un repositorio público.
PLANTILLA_CSV = (
    ";".join(nombre for nombre, _, _ in COLUMNAS) + "\n"
    "AAPL;Apple Inc.;US0378331005;10;150,00;USD;Tecnologia;AAPL;ACCION\n"
    "SAN;Banco Santander;ES0113900J37;200;4,50;EUR;Banca;SAN.MC;ACCION\n"
    "IWDA;iShares Core MSCI World;IE00B4L5Y983;5;80,00;EUR;Renta_Variable_Global;IWDA.AS;ETF\n"
)

CUSTODIO_POR_DEFECTO = "Trade Republic Bank GmbH"

_TICKER_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_ISIN_VALIDO = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Carpeta -> (título, para qué sirve, encabezados bajo los que Sharky apunta
# cada nota nueva con `VaultManager._append_to_moc`).
INDICES = {
    "00_Sistema": ("🧭 Sistema", "Núcleo operativo: libro de posiciones, estado vital y reglas.", []),
    "00_Comite_Direccion": ("🏛️ Comité de Dirección", "Mandato y gobierno de la cartera.", []),
    "01_Departamento_Macro": ("🌐 Departamento Macro", "Informes macro y geopolítica.", []),
    "01_Tesis_Activas": ("📈 Tesis Activas", "Convicciones vivas, con su stop y su objetivo.", ["## 📈 Tesis Vivas"]),
    "02_Analisis_Fundamental": ("🔬 Análisis Fundamental", "Metodología de fosos económicos.", []),
    "02_Tesis_Cerradas": ("📁 Tesis Cerradas", "Tesis de posiciones ya vendidas.", ["## 📋 Registro Histórico de Tesis"]),
    "03_Activos": ("🗺️ Activos", "Fichas de empresas, fondos y sectores.", [ENCABEZADO_FICHAS_NUEVAS, ENCABEZADO_SECTORES_NUEVOS]),
    "03_Mesa_Cuantitativa_Riesgo": ("🛡️ Mesa de Riesgo", "Política de control de riesgo.", []),
    "04_Operaciones_Bitacora": ("🧾 Operaciones", "Operaciones registradas con `sharky trade`.", ["## 📋 Operaciones Registradas"]),
    "04_Sentimiento_Y_Flujos": ("📰 Sentimiento y Flujos", "Escaneos semanales de noticias.", ["## 📰 Noticias Semanales"]),
    "05_Diario_Reflexion": ("📓 Diario", "Controles diarios de la cartera.", ["## 📋 Entradas del Diario"]),
    "06_Lecciones_Aprendidas": ("🎓 Lecciones Aprendidas", "Heurísticas y post-mortems.", []),
    "08_Rebalanceos_Mensuales": (
        "📅 Rebalanceos Mensuales", "Planes del Día 1 y estudios mensuales.",
        ["## 📋 Informes de Rebalanceo Emitidos", "## 🧠 Estudios Mensuales"],
    ),
    "09_Alertas_Oportunidades": (
        "🚨 Alertas de Oportunidad", "Radar de oportunidades asimétricas.",
        ["## 🔥 Alertas Activas en Radar", "## 🔭 Exploraciones de Mercado", "## 🗄️ Alertas Caducadas / Histórico"],
    ),
}


class ErrorCSV(ValueError):
    """El CSV no se puede importar. `errores` trae un mensaje por problema."""

    def __init__(self, errores: List[str]):
        super().__init__("\n".join(errores))
        self.errores = errores


# ----------------------------------------------------------------------
# Rutas (se resuelven al llamar, no al importar, para poder cambiarlas)
# ----------------------------------------------------------------------
def _vault(vault_path: Optional[Path]) -> Path:
    return Path(vault_path) if vault_path else config.VAULT_PATH


def falta_configurar(vault_path: Optional[Path] = None) -> bool:
    """True si todavía no hay libro de posiciones: Sharky no puede hacer nada."""
    return not PortfolioStore(_vault(vault_path)).exists()


# ----------------------------------------------------------------------
# CSV de posiciones
# ----------------------------------------------------------------------
def _numero(texto: str) -> float:
    """Lee `1.234,56`, `1,234.56`, `0,5` o `10`. Sin separador de miles
    ambiguo: con un solo separador, se toma como decimal."""
    t = texto.strip().replace(" ", "").replace(" ", "").replace("€", "")
    if not t:
        raise ValueError("vacío")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    return float(t)


def _divisa(texto: str) -> str:
    t = texto.strip()
    if t.upper() == "GBX" or t == "GBp":
        return "GBp"  # peniques: no es lo mismo que GBP (ver sharky.fx)
    if re.fullmatch(r"[A-Za-z]{3}", t):
        return t.upper()
    raise ValueError(t)


def _leer_texto(ruta: Path) -> str:
    datos = ruta.read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")  # CSV guardado por Excel en Windows


def leer_csv_posiciones(ruta: Path) -> List[Position]:
    """Posiciones de un CSV con las columnas en el orden de `COLUMNAS`.

    Acepta `;`, `,` o tabulador como separador y coma o punto como decimal.
    La cabecera es opcional; se ignoran las líneas vacías y las que empiezan
    por `#`. No se queda en el primer error: los devuelve todos a la vez en
    `ErrorCSV`, cada uno con su número de línea.
    """
    texto = _leer_texto(ruta)
    primera = next(
        (linea for linea in texto.splitlines() if linea.strip() and not linea.lstrip().startswith("#")),
        "",
    )
    separador = max(";,\t", key=primera.count) if primera else ";"

    posiciones: List[Position] = []
    errores: List[str] = []
    vistos = set()
    primera_fila = True
    for n, fila in enumerate(csv.reader(io.StringIO(texto), delimiter=separador), start=1):
        celdas = [c.strip() for c in fila]
        if not any(celdas) or celdas[0].startswith("#"):
            continue
        es_cabecera = primera_fila and celdas[0].lower() == "ticker"
        primera_fila = False
        if es_cabecera:
            continue

        if len(celdas) < _MINIMO_COLUMNAS:
            errores.append(
                f"Línea {n}: tiene {len(celdas)} columnas y hacen falta al menos "
                f"{_MINIMO_COLUMNAS} (ticker, nombre, isin, unidades, coste_medio_eur, divisa)."
            )
            continue
        if len(celdas) > len(COLUMNAS):
            errores.append(
                f"Línea {n}: tiene {len(celdas)} columnas y el máximo es {len(COLUMNAS)}. "
                f"¿Usas la coma como decimal y también como separador? Separa las "
                f"columnas con `;`."
            )
            continue
        celdas += [""] * (len(COLUMNAS) - len(celdas))
        ticker, nombre, isin, unidades_txt, coste_txt, divisa_txt, sector, simbolo, clase_txt = celdas

        problemas = []
        unidades = coste = 0.0
        divisa = "EUR"
        clase = AssetClass.ACCION
        if not _TICKER_VALIDO.match(ticker):
            problemas.append(f"ticker «{ticker}» no válido (letras, números, `_`, `.` o `-`, sin espacios)")
        elif ticker.upper() in vistos:
            problemas.append(f"ticker {ticker} repetido")
        else:
            # Aunque esta fila tenga otros errores: una segunda con el mismo
            # ticker sigue siendo un duplicado.
            vistos.add(ticker.upper())
        if not nombre:
            problemas.append("falta el nombre")
        isin = isin.upper()
        if isin and not _ISIN_VALIDO.match(isin):
            problemas.append(f"ISIN «{isin}» no válido")
        try:
            unidades = _numero(unidades_txt)
            if unidades <= 0:
                problemas.append("las unidades deben ser mayores que 0")
        except ValueError:
            problemas.append(f"unidades «{unidades_txt}» no es un número")
        try:
            coste = _numero(coste_txt)
            if coste <= 0:
                problemas.append("el coste medio debe ser mayor que 0")
        except ValueError:
            problemas.append(f"coste medio «{coste_txt}» no es un número")
        try:
            divisa = _divisa(divisa_txt)
        except ValueError:
            problemas.append(f"divisa «{divisa_txt}» no válida (tres letras: EUR, USD, GBp...)")
        try:
            clase = AssetClass(clase_txt.upper()) if clase_txt else AssetClass.ACCION
        except ValueError:
            problemas.append(f"clase «{clase_txt}» no válida (ACCION, ETF, ETC o CRIPTO)")

        if problemas:
            errores.append(f"Línea {n} ({ticker or 'sin ticker'}): " + "; ".join(problemas) + ".")
            continue

        # Sin símbolo, se usa el del registro de Sharky sólo si cotiza en la
        # misma divisa que declara el CSV: un símbolo en otra divisa valoraría
        # la posición con el precio equivocado (ver FX-1). Si no, queda sin
        # cotización -- valorada a coste y señalizada -- hasta `resolve-isin`.
        if not simbolo:
            registrado = INSTRUMENT_REGISTRY.get(ticker.upper())
            if registrado and registrado[1] == divisa:
                simbolo = registrado[0]

        posiciones.append(
            Position(
                ticker=ticker,
                nombre=nombre,
                isin=isin or None,
                ticker_cotizacion=simbolo or None,
                divisa_cotizacion=divisa,
                clase=clase,
                unidades=unidades,
                coste_unitario_eur=coste,
                sector=sector,
                nota_activo=f"[[{ticker}]]",
            )
        )

    if errores:
        raise ErrorCSV(errores)
    return posiciones


# ----------------------------------------------------------------------
# Escritura
# ----------------------------------------------------------------------
def guardar_clave_api(clave: str, ruta_env: Path, ruta_ejemplo: Path) -> None:
    """Fija `ANTHROPIC_API_KEY` en `.env`, creándolo desde `.env.example` si
    no existe. El resto de líneas se conserva tal cual."""
    if ruta_env.exists():
        texto = ruta_env.read_text(encoding="utf-8")
    elif ruta_ejemplo.exists():
        texto = ruta_ejemplo.read_text(encoding="utf-8")
    else:
        texto = ""

    linea = f"ANTHROPIC_API_KEY={clave}"
    patron = re.compile(r"^ANTHROPIC_API_KEY=.*$", re.MULTILINE)
    if patron.search(texto):
        # Función y no cadena: una clave con `\` no debe leerse como escape.
        texto = patron.sub(lambda _: linea, texto, count=1)
    else:
        texto = (texto.rstrip("\n") + "\n" if texto else "") + linea + "\n"
    atomic_write_text(ruta_env, texto, encoding="utf-8")


def _crear_indices(vault_path: Path) -> None:
    """Una nota índice por carpeta, sin tocar las que ya existan."""
    otras = [c for c in INDICES if c != "00_Sistema"]
    for carpeta, (titulo, descripcion, encabezados) in INDICES.items():
        ruta = vault_path / carpeta / f"{carpeta}.md"
        if ruta.exists():
            continue
        secciones = "".join(f"{e}\n\n" for e in encabezados)
        if carpeta == "00_Sistema":
            grafo = (
                "* Cartera (fuente de verdad): [[Cartera_Real]]\n"
                "* Reglas: [[Reglas_De_Supervivencia]], [[Metricas_Riesgo]]\n"
                "* Índices: " + ", ".join(f"[[{c}]]" for c in otras) + "\n"
            )
        else:
            grafo = "* Sistema: [[00_Sistema]] | Cartera: [[Cartera_Real]]\n"
        cuerpo = f"# {titulo}\n\n{descripcion}\n\n{secciones}---\n\n## 🔗 Enlaces del Grafo\n\n{grafo}"
        atomic_write_text(
            ruta, VaultManager.build_markdown({"tipo": "moc"}, cuerpo), encoding="utf-8"
        )


def crear_boveda(
    posiciones: List[Position],
    efectivo_eur: float,
    custodio: str = CUSTODIO_POR_DEFECTO,
    vault_path: Optional[Path] = None,
) -> Path:
    """Crea el libro de posiciones, las notas índice y una ficha por posición.

    Se niega a sobrescribir un libro existente: es la fuente de verdad de una
    cartera real, y un asistente no debe poder borrarla por error.
    """
    vault = _vault(vault_path)
    store = PortfolioStore(vault)
    if store.exists():
        raise FileExistsError(f"Ya existe un libro de posiciones en {store.ledger_path}.")

    vm = VaultManager(vault)  # crea las carpetas
    _crear_indices(vault)
    ruta = store.save(
        Portfolio(custodio=custodio, efectivo_eur=efectivo_eur, posiciones=posiciones)
    )
    for p in posiciones:
        vm.asegurar_ficha(
            p.ticker, p.nombre, p.sector, origen="Cartera_Real", seguimiento="Activo_Cartera"
        )
    return ruta


# ----------------------------------------------------------------------
# Asistente
# ----------------------------------------------------------------------
def es_interactivo() -> bool:
    """True si hay alguien delante: entrada y salida son una consola.

    La tarea programada de Windows redirige la salida a un log; ahí la
    entrada puede seguir siendo una consola, así que no basta con mirar
    `stdin`, o el arranque se quedaría esperando una respuesta que nadie ve.
    """
    return all(f is not None and f.isatty() for f in (sys.stdin, sys.stdout))


def _preguntar_secreto(texto: str) -> str:
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass(texto)
    return input(texto)


def _explicar_formato(mostrar: Callable[[str], None]) -> None:
    mostrar("El CSV lleva una posición por línea, con las columnas en este orden:")
    for i, (nombre, obligatoria, que) in enumerate(COLUMNAS, start=1):
        marca = "obligatoria" if obligatoria else "opcional"
        mostrar(f"  {i}. {nombre:<16} ({marca}) {que}")
    mostrar(
        "Separa las columnas con `;` y usa coma o punto como decimal. Las opcionales "
        "pueden quedar vacías, pero su columna debe estar (`;;`). La cabecera es opcional."
    )


def _pedir_csv(
    preguntar: Callable[[str], str],
    mostrar: Callable[[str], None],
    ruta_plantilla: Path,
) -> Optional[List[Position]]:
    _explicar_formato(mostrar)
    while True:
        respuesta = preguntar(
            "\nRuta del CSV con tus posiciones (Enter: crear una plantilla; q: salir): "
        ).strip().strip('"').strip("'")
        if respuesta.lower() == "q":
            return None
        if not respuesta:
            if not ruta_plantilla.exists():
                atomic_write_text(ruta_plantilla, PLANTILLA_CSV, encoding="utf-8")
                mostrar(f"Plantilla creada en {ruta_plantilla} con tres posiciones de ejemplo.")
            else:
                mostrar(f"Ya hay una plantilla en {ruta_plantilla}; no la sobrescribo.")
            mostrar(
                "Ábrela con Excel o un editor, cambia los ejemplos por tus posiciones, "
                "guárdala y escribe aquí su ruta. (No se sube a git: .gitignore excluye los CSV.)"
            )
            continue

        ruta = Path(respuesta).expanduser()
        if not ruta.is_file():
            mostrar(f"No encuentro el fichero {ruta}.")
            continue
        try:
            posiciones = leer_csv_posiciones(ruta)
        except ErrorCSV as exc:
            mostrar(f"El CSV tiene {len(exc.errores)} problema(s):")
            for error in exc.errores[:15]:
                mostrar(f"  • {error}")
            if len(exc.errores) > 15:
                mostrar(f"  … y {len(exc.errores) - 15} más.")
            mostrar("Corrígelo, guárdalo y vuelve a darme la ruta.")
            continue

        mostrar(f"\n{len(posiciones)} posición(es) leída(s):")
        for p in posiciones:
            simbolo = p.ticker_cotizacion or "sin símbolo"
            mostrar(
                f"  {p.ticker:<14} {p.unidades:>14,.6f} × {p.coste_unitario_eur:>10,.2f} € "
                f"({p.divisa_cotizacion}, {simbolo})"
            )
        return posiciones


def _pedir_efectivo(preguntar: Callable[[str], str], mostrar: Callable[[str], None]) -> float:
    while True:
        respuesta = preguntar("\nEfectivo disponible en la cuenta, en EUR [0]: ").strip()
        if not respuesta:
            return 0.0
        try:
            valor = _numero(respuesta)
        except ValueError:
            mostrar("Escribe un número, por ejemplo 1500 o 1500,50.")
            continue
        if valor < 0:
            mostrar("El efectivo no puede ser negativo.")
            continue
        return valor


def asistente(
    vault_path: Optional[Path] = None,
    ruta_env: Optional[Path] = None,
    ruta_ejemplo: Optional[Path] = None,
    ruta_plantilla: Optional[Path] = None,
    preguntar: Callable[[str], str] = input,
    preguntar_secreto: Callable[[str], str] = _preguntar_secreto,
    mostrar: Callable[[str], None] = print,
) -> bool:
    """Configura Sharky preguntando en consola. True si queda listo para usar.

    No escribe nada hasta el «¿Creo la bóveda...?» final: cancelar en
    cualquier punto deja todo como estaba.
    """
    vault = _vault(vault_path)
    ruta_env = ruta_env or config.BASE_DIR / ".env"
    ruta_ejemplo = ruta_ejemplo or config.BASE_DIR / ".env.example"
    ruta_plantilla = ruta_plantilla or config.BASE_DIR / "posiciones.csv"

    try:
        mostrar("\n🦈 CONFIGURACIÓN INICIAL DE SHARKY")
        mostrar("=" * 78)

        store = PortfolioStore(vault)
        if store.exists():
            mostrar(f"Ya hay un libro de posiciones en {store.ledger_path}; no se toca.")
            if config.has_live_api_key():
                mostrar("La clave de Claude también está configurada: no hay nada que hacer.")
                return True
            clave = preguntar_secreto("Clave de la API de Claude (Enter para dejarla como está): ").strip()
            if clave:
                guardar_clave_api(clave, ruta_env, ruta_ejemplo)
                mostrar(f"✅ Clave guardada en {ruta_env}.")
            return True

        # 1. Clave de Claude
        clave = ""
        if config.has_live_api_key():
            mostrar("✓ Clave de la API de Claude: ya configurada.")
        else:
            mostrar(
                "\n1/3 · Clave de la API de Claude (se crea en console.anthropic.com). "
                "No se muestra al escribirla ni se sube a git."
            )
            clave = preguntar_secreto("Pega tu clave (Enter para seguir sin ella): ").strip()
            if not clave:
                mostrar(
                    "Sin clave, Sharky funciona en modo simulado: el diario se marca como "
                    "tal y no hay noticias, exploración ni revisión de tesis. Puedes "
                    "añadirla luego en .env."
                )
            elif not clave.startswith("sk-ant-"):
                mostrar("⚠️  No empieza por `sk-ant-`: revisa que sea una clave de Anthropic.")

        # 2. Posiciones
        mostrar("\n2/3 · Posiciones")
        posiciones = _pedir_csv(preguntar, mostrar, ruta_plantilla)
        if posiciones is None:
            mostrar("Cancelado: no se ha escrito nada.")
            return False

        # 3. Efectivo y custodio
        mostrar("\n3/3 · Efectivo y bróker")
        efectivo = _pedir_efectivo(preguntar, mostrar)
        custodio = preguntar(f"Bróker o custodio [{CUSTODIO_POR_DEFECTO}]: ").strip() or CUSTODIO_POR_DEFECTO

        coste = sum(p.coste_total_eur for p in posiciones)
        mostrar("\nResumen:")
        mostrar(f"  Clave de Claude: {'nueva' if clave else ('ya configurada' if config.has_live_api_key() else 'sin clave (modo simulado)')}")
        mostrar(f"  Posiciones:      {len(posiciones)} (coste total {coste:,.2f} €)")
        mostrar(f"  Efectivo:        {efectivo:,.2f} €")
        mostrar(f"  Custodio:        {custodio}")
        mostrar(f"  Bóveda:          {vault}")
        confirmacion = preguntar("¿Creo la bóveda con estos datos? [S/n]: ").strip().lower()
        if confirmacion not in ("", "s", "si", "sí", "y", "yes"):
            mostrar("Cancelado: no se ha escrito nada.")
            return False

        if clave:
            guardar_clave_api(clave, ruta_env, ruta_ejemplo)
        crear_boveda(posiciones, efectivo, custodio, vault)
    except (KeyboardInterrupt, EOFError):
        mostrar("\nCancelado: no se ha escrito nada.")
        return False

    sin_simbolo = [p.ticker for p in posiciones if not p.ticker_cotizacion]
    mostrar("\n✅ Sharky está configurado. Siguientes pasos:")
    if sin_simbolo:
        mostrar(
            f"  • {', '.join(sin_simbolo)} no tiene(n) símbolo de cotización y se valoran a "
            "coste. `python -m sharky.cli resolve-isin` sugiere uno a partir del ISIN; "
            "añádelo como `ticker_cotizacion` en vault/00_Sistema/Cartera_Real.md."
        )
    mostrar(
        "  • Escribe una tesis con su stop-loss para cada posición en vault/01_Tesis_Activas "
        "(plantilla: vault/07_Plantillas/Plantilla_Tesis.md). Sin tesis, Sharky no vigila "
        "ningún stop."
    )
    mostrar("  • Abre la carpeta vault/ con Obsidian para ver la bóveda.")
    return True


# ----------------------------------------------------------------------
# Relanzar tras configurar
# ----------------------------------------------------------------------
def relanzar(modulo: str, argumentos: List[str]) -> int:
    """Repite la orden en un proceso nuevo y devuelve su código de salida.

    La configuración se lee al importar `sharky.config`: este proceso ya no
    vería la clave recién guardada en `.env`, uno nuevo sí.
    """
    # Sin shell: el ejecutable es el mismo Python que corre Sharky, el módulo
    # es fijo y los argumentos son los que ya escribió el usuario.
    return subprocess.call([sys.executable, "-m", modulo, *argumentos])  # nosec B603


def abrir_app() -> None:
    """Abre la app en segundo plano, sin consola si se puede (pythonw)."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    ejecutable = pythonw if pythonw.exists() else Path(sys.executable)
    subprocess.Popen([str(ejecutable), "-m", "sharky.app"])  # nosec B603


def abrir_asistente_en_consola() -> bool:
    """Abre el asistente en una consola nueva (Windows).

    Para la app lanzada desde su acceso directo con `pythonw`, que no tiene
    consola donde preguntar. Al terminar, `init --abrir-app` abre la app.
    False si no se pudo (otro sistema operativo, o no hay `python.exe`).
    """
    python = Path(sys.executable).with_name("python.exe")
    if os.name != "nt" or not python.exists():
        return False
    subprocess.Popen(  # nosec B603
        [str(python), "-m", "sharky.cli", "init", "--abrir-app"],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    return True
