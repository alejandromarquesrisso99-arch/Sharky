# Sharky Capital Management: Family Office Autónomo

> Fondo institucional / *family office* digital que gestiona una cartera real
> custodiada en Trade Republic. Combina una **estructura departamental**
> (Macro, Fundamental, Riesgo y Psicología de Mercado), un **libro de posiciones
> contable** como fuente de verdad, un **cortafuegos de riesgo determinista** y
> **Obsidian** como memoria de largo plazo, con **Claude** en el rol de *Chief
> Investment Officer*.

**¿Primera vez?** Empieza por la [guía de nuevo usuario](GUIA_NUEVO_USUARIO.md):
de cero a tener Sharky vigilando tu cartera, paso a paso.

**Divisa base: EUR.** La cartera está denominada en euros; los activos que
cotizan en USD, HKD o GBp se convierten explícitamente. Ninguna cifra mezcla
divisas.

---

## 1. Principios de diseño

Tres reglas gobiernan todo el código, y explican por qué está escrito así:

1. **Una posición es un hecho; una tesis es una opinión.** El NAV, el PnL, los
   pesos y el drawdown se derivan *exclusivamente* del libro de posiciones
   (`vault/00_Sistema/Cartera_Real.md`). Las notas de tesis nunca alimentan la
   contabilidad.
2. **Ningún dato estimado se presenta como medido.** Toda cotización arrastra su
   procedencia (`MERCADO`, `CACHE`, `COSTE`, `SIMULADO`). Si un informe se apoya
   en algo que no es una cotización real, la nota y la CLI lo declaran. Si Claude
   no está disponible, el diario se marca como *simulado* en lugar de imitar un
   análisis.
3. **Los límites de riesgo son código, no prosa.** `RiskGovernor` implementa
   literalmente los axiomas de `vault/00_Sistema/Reglas_De_Supervivencia.md`, y
   ninguna operación entra en el libro sin pasar por él.
4. **La bóveda personal no se versiona.** El repositorio es público y Sharky
   escribe datos de la cartera real en casi toda la bóveda (libro de
   posiciones, estado vital, operaciones, diarios, tesis, rebalanceos), así
   que `.gitignore` la deja fuera entera: sólo se versionan las plantillas y
   las cuatro notas de reglas que los tests contrastan con el código. La
   bóveda vive en local y en `backups/`. Antes de añadir una excepción a
   `.gitignore`, comprueba que la nota no lleva importes, unidades ni
   posiciones: lo que entra en el historial de git ya no sale de él sin
   reescribirlo.

---

## 2. Estructura departamental

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     COMITÉ DE DIRECCIÓN / CIO (Claude)                      │
│     - Deliberación estratégica y resolución ejecutiva                       │
│     - Aprobación del rebalanceo del Día 1                                   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
       ┌───────────────────────────────┼───────────────────────────────┐
       ▼                               ▼                               ▼
┌─────────────────────────┐ ┌──────────────────────────┐ ┌─────────────────────────┐
│  DEPARTAMENTO MACRO     │ │   ANÁLISIS FUNDAMENTAL   │ │   MESA DE RIESGO (CRO)  │
│ - Tipos (TLT)           │ │ - Múltiplos reales (P/E) │ │ - Drawdown vs. máximo   │
│ - Oro y divisas (GLD)   │ │ - Fosos económicos       │ │ - Stop-loss obligatorio │
│ - Geopolítica y cadenas │ │ - Capitalización y caja  │ │ - Topes activo/sector   │
└─────────────────────────┘ └──────────────────────────┘ └─────────────────────────┘
                                       │
                                       ▼
                            ┌─────────────────────────┐
                            │   PSICOLOGÍA & FLUJOS   │
                            │ - Amplitud y dispersión │
                            │ - Detección de FOMO     │
                            │ - Control de sesgos     │
                            └─────────────────────────┘
```

Cada mesa produce su informe a partir de datos medidos. Cuando un dato falta, el
informe lo enumera en `datos_ausentes` en lugar de rellenarlo.

---

## 3. Módulos

| Módulo | Responsabilidad |
| :--- | :--- |
| `sharky/portfolio.py` | Libro de posiciones y valoración en EUR. **Fuente de verdad.** |
| `sharky/fx.py` | Tipos de cambio a la divisa base. Distingue `GBP` de `GBp`. |
| `sharky/market_data.py` | Cotizaciones con divisa, procedencia, caché y técnicos. |
| `sharky/risk_governor.py` | Cortafuegos determinista: estado vital, auditoría y validación de órdenes. |
| `sharky/level_watch.py` | Vigilancia diaria de stop-loss y take-profit, con el stop dinámico propuesto. |
| `sharky/trade_ledger.py` | Registro de operaciones. Único camino de escritura al libro. |
| `sharky/rebalance_engine.py` | Plan del Día 1 por prioridades del mandato. |
| `sharky/opportunity_detector.py` | Radar de asimetrías con confirmación cuantitativa. |
| `sharky/market_explorer.py` | Búsqueda activa de oportunidades **nuevas** en la web, con el modelo más capaz. |
| `sharky/thesis_review.py` | Revisión mensual de las tesis con novedades. Añade, nunca sobrescribe. |
| `sharky/firm_departments.py` | Las cuatro mesas. |
| `sharky/firm_committee.py` | Comité y resolución del CIO. |
| `sharky/claude_client.py` | Cliente de la API de Claude, con fallback declarado. |
| `sharky/news_scanner.py` | Escaneo semanal de noticias de la cartera vía la tool de búsqueda web de Claude. |
| `sharky/vault_manager.py` | Lectura y escritura de notas de Obsidian. |
| `sharky/agent_loop.py` | Orquestación de los ciclos. |
| `sharky/scheduler.py` | Servicio 24/7. |
| `sharky/app/` | App de gestión: servidor local (librería estándar) + interfaz web adaptable. |

---

## 4. La bóveda (`vault/`)

Abre la carpeta `vault/` en **Obsidian** para explorar el cerebro corporativo.

```text
vault/
├── 00_Sistema/                        # Núcleo operativo
│   ├── Cartera_Real.md                #   ← LIBRO DE POSICIONES (fuente de verdad)
│   ├── Estado_Vital.md                #   Cuadro de mandos: NAV, drawdown, incumplimientos
│   ├── Reglas_De_Supervivencia.md     #   Axiomas inmutables
│   ├── Metricas_Riesgo.md             #   Fórmulas
│   └── Prompt_Sistema.md              #   Metaprompt del CIO (lo lee el motor)
├── 00_Comite_Direccion/               # Mandato institucional y auditoría de origen
├── 01_Departamento_Macro/             # Informes macro y geopolítica
├── 01_Tesis_Activas/                  # Convicciones (con y sin posición abierta)
├── 02_Analisis_Fundamental/           # Metodología de fosos
├── 02_Tesis_Cerradas/                 # Histórico de tesis liquidadas
├── 03_Activos/                        # Fichas de activos
│   ├── Empresas/                      #   Acciones y ETF
│   ├── Sectores/                      #   Sectores temáticos
│   └── Macro_Geopolitica/             #   Referencias e índices
├── 03_Mesa_Cuantitativa_Riesgo/       # Política del CRO
├── 04_Operaciones_Bitacora/           # Operaciones registradas
├── 04_Sentimiento_Y_Flujos/           # Psicología y narrativas
│   └── Noticias_Semanales/            #   Escaneo semanal de noticias por activo
├── 05_Diario_Reflexion/               # Actas diarias
├── 06_Lecciones_Aprendidas/           # Heurísticas
├── 07_Plantillas/                     # Plantillas
├── 08_Rebalanceos_Mensuales/          # Propuestas del Día 1
└── 09_Alertas_Oportunidades/          # Oportunidades asimétricas
    └── Exploraciones/                 #   Búsquedas de ideas nuevas, con su veredicto
```

`Estado_Vital.md` no sólo lista los incumplimientos del mandato vigentes:
recuerda desde cuándo lleva abierto cada uno (`incumplimientos_desde`) y lo
marca como **escalado** si supera `SHARKY_BREACH_ESCALATION_DAYS` (7 días
por defecto) -- para que una brecha que el `RiskGovernor` detecta pero nadie
corrige deje de pasar desapercibida sólo por volver a aparecer, idéntica,
en cada ciclo.

El nombre de una ficha no siempre es el ticker: la de Rheinmetall es
`Rheinmetall`, no `RHM`. La correspondencia la declara el campo `nota_activo` del
libro de posiciones y, para lo que no está en cartera, el `ticker` y los
`aliases` de cada ficha. Ojo: Obsidian usa los `aliases` para *sugerir* la ficha
mientras escribes un enlace, pero un `[[RHM]]` escrito tal cual apunta a una
nota `RHM` que no existe. Por eso `VaultManager` normaliza al escribir todo lo
que redacta Claude, que enlaza por ticker: `[[RHM]]` se guarda como
`[[Rheinmetall|RHM]]`, y un enlace que no resuelve a ninguna nota queda como
texto plano. Y si una posición nueva o una alerta del radar enlaza a un activo o
a un sector sin nota, se crea una ficha mínima en `03_Activos` (apuntada en su
MOC, bajo «Altas Automáticas») en vez de dejar el enlace roto.

---

## 5. Comandos

```bash
# Configuración inicial: clave de Claude y posiciones desde un CSV. Se abre
# sola la primera vez que lanzas cualquier comando (ver §6, «Primeros pasos»)
python -m sharky.cli init

# Estado vital, NAV e incumplimientos del mandato
python -m sharky.cli status

# Cartera valorada a mercado, con exposición sectorial y procedencia de precios
python -m sharky.cli portfolio

# Auditoría de riesgo contra las reglas de supervivencia
python -m sharky.cli risk

# Control diario: valoración, stop-loss, radar y diario en Obsidian. Claude
# sólo razona sobre posiciones, precios, valor de mercado y normas
python -m sharky.cli daily

# Estudio mensual: plan de rebalanceo del Día 1 + reevaluación de posiciones
# por Claude con todo el contexto del mes (diarios y noticias semanales)
python -m sharky.cli monthly

# Sólo el plan de rebalanceo del Día 1, sin llamar a Claude
python -m sharky.cli rebalance

# Sesión plenaria del Comité de Inversión con los cuatro departamentos
python -m sharky.cli committee

# Stop-loss y take-profit alcanzados hoy (no llama a la API de Claude,
# así que puedes consultarlo tantas veces como quieras)
python -m sharky.cli niveles

# Alertas de oportunidad activas
python -m sharky.cli alerts

# Revisión de las tesis activas que tienen algo que decir este mes. Apila
# una sección fechada sobre cada una sin borrar lo anterior y sin tocar un
# solo nivel. El estudio mensual la lanza sola al terminar
python -m sharky.cli revisar-tesis

# Exploración de mercado: busca en la web oportunidades asimétricas NUEVAS,
# fuera de la cartera y del universo de vigilancia, con el modelo más capaz
# de Claude. Cada candidato pasa después por el mismo filtro cuantitativo
# que el resto (sin ANTHROPIC_API_KEY no se ejecuta)
python -m sharky.cli explorar

# Termómetro macroeconómico (SPY, QQQ, TLT, GLD, USO)
python -m sharky.cli macro

# Escaneo semanal de noticias relevantes para los activos en cartera, con el
# contexto de los últimos 7 controles diarios (usa la tool de búsqueda web
# de Claude; sin ANTHROPIC_API_KEY no se ejecuta)
python -m sharky.cli noticias

# Ciclo para lanzar al encender el ordenador (ver §7): si el control de hoy
# ya se ejecutó, no vuelve a llamar a la API de Claude. Además lanza, si
# toca, el escaneo semanal de noticias y el estudio mensual
python -m sharky.cli startup

# Servicio autónomo 24/7 (para un equipo que permanece siempre encendido)
python -m sharky.cli service --interval 60

# App de gestión (ver «App de gestión» más abajo)
python -m sharky.cli app
```

### App de gestión

Todo lo anterior también se puede hacer desde una app con interfaz gráfica.
Es un servidor local que reutiliza el mismo código que la CLI y se abre en
una ventana propia de Edge (o Chrome):

```powershell
# Una sola vez: accesos directos «Sharky» en el Escritorio y en el menú Inicio
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_app_windows.ps1

# O a mano, sin accesos directos
python -m sharky.app
```

| Pantalla | Qué hace |
| :--- | :--- |
| **Panel** | Estado vital, NAV y drawdown, avisos que requieren atención (stops, incumplimientos, datos), evolución del NAV, los tres niveles de razonamiento con su última conclusión y un botón para lanzarlos, posiciones, exposición sectorial y oportunidades. |
| **Informes** | Lector de todo lo que Sharky escribe en la bóveda (controles diarios, noticias, estudios, rebalanceos, operaciones, tesis, alertas), con los `[[enlaces]]` navegables. |
| **Operar** | Registra una operación ya ejecutada en tu bróker (el del libro de posiciones). Pasa por el RiskGovernor igual que `sharky trade`. |
| **Sistema** | Perfiles de la IA, todas las acciones (con su coste estimado), historial y apagado. |

- Las acciones largas (control diario, noticias, estudio mensual, comité)
  corren en segundo plano, de una en una. Antes de ejecutarlas, la app
  enseña su coste estimado y pide confirmación.
- Escucha solo en `127.0.0.1:8765` (puerto configurable con
  `SHARKY_APP_PORT`). Cada arranque genera un token de sesión que toda llamada
  a la API debe llevar, y se comprueba la cabecera `Host`. Así, ninguna web
  abierta en el navegador puede leer la cartera ni lanzar acciones contra la app.
- Cerrar la ventana no detiene el servidor: usa **Sistema → Apagar la app**.
- La interfaz se adapta a pantallas estrechas (navegación inferior), como
  base para la versión móvil.

### Stop-loss y take-profit

El ciclo diario compara el precio de cada posición con los niveles declarados
en su tesis y avisa **el mismo día en que se cruzan**. Los dos niveles no
pesan lo mismo:

| Nivel | Qué significa | Qué hace Sharky |
| :--- | :--- | :--- |
| **Stop-loss** | Salida obligatoria del mandato | Avisa y exige liquidar. Es la única excepción operativa intrames. |
| **Take-profit** | Objetivo alcanzado | Avisa y **propone subir el stop**. No obliga a vender. |

El stop propuesto al alcanzar el target es el mayor de dos criterios
deterministas, y nunca queda por debajo del stop vigente:

* **break-even** — el precio de entrada de la tesis: a partir de ahí la
  operación ya no puede terminar en pérdida;
* **trailing** — el precio actual menos el riesgo inicial de la tesis
  (`entrada - stop`), que mantiene constante el riesgo abierto que el
  `RiskGovernor` ya aprobó al abrir la posición. Si la tesis no declara
  entrada o stop, cae a `SHARKY_TRAILING_STOP_PCT` (8% por defecto).

La comparación se hace **siempre en EUR**. Una tesis declara sus niveles en la
divisa de su frontmatter, que no tiene por qué ser la de cotización: el stop de
MSFT vino del extracto en euros mientras la acción cotiza en dólares. Comparar
ambos números sin convertirlos ordenaría liquidar posiciones sanas.

Una posición sin cotización fiable **no se declara a salvo**: aparece como
`no verificable`. Que no salte un aviso no puede significar dos cosas
distintas.

Los avisos salen por tres sitios a la vez:

1. La cabecera de `daily` / `startup` en la consola, antes que el NAV.
2. La sección `## 🎯 Niveles Alcanzados` de `Estado_Vital.md`, por delante de
   los incumplimientos del mandato.
3. Una ventana emergente al encender el ordenador (ver §7).

### Registrar una operación

Sharky **no envía órdenes a ningún broker**. Tú ejecutas en Trade Republic y
registras lo ejecutado; el `RiskGovernor` valida antes de escribir nada:

```bash
# Ampliar una posición existente (stop y target obligatorios en las compras)
python -m sharky.cli trade compra MSFT 1.5 509.40 --stop 460 --target 620 \
    --comision 1.00 --motivo "Ampliación tras rebalanceo del Día 1"

# Reducir o cerrar
python -m sharky.cli trade venta NOK 5 8.80 --motivo "Liquidación de posición residual"

# Abrir una posición nueva: hay que aportar su identidad
python -m sharky.cli trade compra ASML 0.5 720.00 --stop 660 --target 900 \
    --divisa USD --simbolo ASML --isin NL0010273215 \
    --nombre "ASML Holding N.V." --sector Semiconductores --clase ACCION
```

Si la operación rompe un límite, se rechaza con el motivo exacto y **el libro no
se modifica**:

```
⛔ OPERACIÓN RECHAZADA POR EL RISKGOVERNOR
   RECHAZADA: RHM quedaría al 31.33% del NAV (límite 10.0%).
              Máximo invertible ahora: 0.00 €.
```

### Completar el libro de posiciones

```bash
# Sugiere símbolos de cotización para los ISIN sin mapear
python -m sharky.cli resolve-isin
```

Una posición sin `ticker_cotizacion` se valora **a coste de adquisición** y se
señala en todos los informes, junto al porcentaje del NAV que sí está respaldado
por cotizaciones reales (`cobertura_datos_pct`).

---

## 6. Instalación

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux / macOS

pip install -r requirements.txt
pip install -e .

python -m sharky.cli init     # clave de Claude y posiciones (ver «Primeros pasos»)
```

### Primeros pasos

La [guía de nuevo usuario](GUIA_NUEVO_USUARIO.md) recorre todo esto paso a
paso, desde instalar Python hasta dejar Sharky funcionando solo.

La bóveda y el `.env` no están en el repositorio: cada persona empieza con
los suyos. Al lanzar cualquier comando, o la app, sin libro de posiciones,
Sharky abre un asistente (también se abre a mano con `python -m sharky.cli
init`) que pide tres cosas y no escribe nada hasta que confirmas el resumen:

1. **La clave de la API de Claude** ([console.anthropic.com](https://console.anthropic.com)).
   No se muestra al escribirla y se guarda en `.env`, que es el archivo de
   configuración de usuario (el resto de ajustes están explicados en
   `.env.example`). Si la dejas vacía, Sharky funciona en modo simulado.
2. **Tus posiciones, en un CSV** con estas columnas y en este orden:

   | # | Columna | | Qué va |
   | ---: | :--- | :--- | :--- |
   | 1 | `ticker` | obligatoria | Nombre corto de la posición; da nombre a su ficha (`MSFT`) |
   | 2 | `nombre` | obligatoria | Empresa o fondo |
   | 3 | `isin` | opcional | Con él, `resolve-isin` busca el símbolo de cotización |
   | 4 | `unidades` | obligatoria | Títulos, con decimales si los hay |
   | 5 | `coste_medio_eur` | obligatoria | Precio medio de compra por título, en euros |
   | 6 | `divisa` | obligatoria | Divisa en la que cotiza: `EUR`, `USD`, `GBp`, `HKD`... |
   | 7 | `sector` | opcional | Para el límite de concentración sectorial |
   | 8 | `simbolo` | opcional | Símbolo de Yahoo Finance (`RHM.DE`); vacío = registro de Sharky |
   | 9 | `clase` | opcional | `ACCION` (por defecto), `ETF`, `ETC` o `CRIPTO` |

   ```
   ticker;nombre;isin;unidades;coste_medio_eur;divisa;sector;simbolo;clase
   SAN;Banco Santander;ES0113900J37;200;4,50;EUR;Banca;SAN.MC;ACCION
   ```

   Separa las columnas con `;` y usa coma o punto como decimal; la cabecera
   es opcional. Si pulsas Enter en vez de dar una ruta, el asistente crea una
   plantilla para rellenar. El extracto del bróker se puede convertir a este
   formato con Claude. Si el CSV tiene errores, los enumera todos con su
   línea y vuelve a pedirlo. `.gitignore` excluye los CSV: no se suben al
   repositorio.
3. **El efectivo** en la cuenta y el **bróker**.

Con eso crea el libro de posiciones, una ficha por posición y las notas
índice de la bóveda, y repite el comando que habías lanzado. Después:

* **Escribe una tesis con su stop-loss para cada posición** en
  `vault/01_Tesis_Activas` (plantilla en `vault/07_Plantillas`). Sin tesis,
  Sharky no vigila ningún stop.
* Si alguna posición quedó sin símbolo de cotización, se valora a coste
  hasta que lo añadas; `python -m sharky.cli resolve-isin` sugiere uno.

La tarea programada de Windows no pregunta nunca: sin configurar, deja el
aviso en su log y termina. Nunca sobrescribe un libro que ya existe.

### Tests, lint y tipos

```bash
pip install -r requirements-dev.txt
ruff check sharky/ tests/ scripts/
mypy sharky/
python -m pytest
```

La suite cubre los invariantes del núcleo (divisas, drawdown contra el máximo
histórico, umbrales del mandato, validación de órdenes, rebalanceo), la
**integridad del grafo de Obsidian** (falla si aparece un enlace roto, una
nota huérfana o un callejón sin salida) y la **sincronía entre el código y
el vault** (`tests/test_vault_sync.py`): si `sharky/config.py` y las notas de
gobernanza (`Reglas_De_Supervivencia`, `Politica_Control_Riesgo`,
`Mandato_Institucional`) llegan a citar umbrales de riesgo distintos, la
suite falla en vez de que alguien tenga que descubrirlo a mano.

Los tres comandos corren automáticamente en cada push y pull request a
`main` vía GitHub Actions (`.github/workflows/ci.yml`).

### Seguridad

```bash
pip install -r requirements-security.txt
bandit -c pyproject.toml -r sharky/ scripts/   # análisis estático (SAST)
pip-audit -r requirements.txt                   # CVEs conocidas en dependencias
```

También corre solo en la CI, en un job aparte (`security`) que falla el
workflow igual que lint/tests si aparece algo.

---

## 7. Arranque automático (Windows)

Sharky no corre como servicio permanente: se lanza **una vez al día, al
encender el ordenador e iniciar sesión**. Ejecuta el control diario completo
(cartera, stop-loss, radar de oportunidades y diario en Obsidian) y, cuando
toca, el escaneo semanal de noticias y el estudio mensual.

La IA razona en tres niveles, y cada uno pasa al siguiente sólo su
conclusión (así el contexto de cada llamada no crece sin límite):

| Nivel | Cuándo | Qué razona Claude | Perfil |
| :--- | :--- | :--- | :--- |
| Diario | Primer arranque del día | Posiciones, precios, valor de mercado y cumplimiento de normas | effort `low`, 8000 tokens |
| Semanal | Domingo (o a los 7 días) | Noticias de la cartera + conclusiones de los últimos 7 controles; investiga primero lo que se movió más de ±7% | effort `medium`, 16000 tokens |
| Mensual | Primer arranque del mes | Estudio completo y reevaluación de posiciones con los controles y escaneos del mes, contrastando el plan del motor de rebalanceo | effort `high`, 32000 tokens |

Los perfiles se ajustan en `.env` (ver `.env.example`).

```powershell
# Instalación (una sola vez, desde la carpeta del proyecto):
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_inicio_windows.ps1
```

Esto registra la tarea `SharkyStartup` en el Programador de Tareas de Windows,
disparada al iniciar sesión, sin necesitar permisos de administrador. Ejecuta
`scripts\sharky_windows_startup.bat`, que activa `.venv` y llama a
`python -m sharky.cli startup`.

Si enciendes el ordenador varias veces el mismo día, `startup` detecta que el
ciclo diario ya se completó y **no vuelve a invocar la API de Claude**: sólo
la primera ejecución del día llama al modelo, el resto se limita a mostrar el
estado actual. Los logs de cada arranque quedan en `logs/sharky_startup.log`.

El mismo arranque también comprueba si toca el **escaneo semanal de
noticias** de los activos en cartera (domingo por defecto,
`SHARKY_NEWS_SCAN_WEEKDAY`). Como Sharky no corre como servicio permanente,
`startup` es el único punto de entrada fiable para algo que debe pasar una
vez por semana: si ese domingo no se encendió el ordenador, el escaneo se
lanza igual en el primer arranque en cuanto pasan 7 días desde el último,
para que no quede huérfano indefinidamente.

Con el **estudio mensual** pasa lo mismo: lo lanza el primer arranque de cada
mes, sea el día que sea. Si la API falló y el estudio salió sin Claude, se
reintenta en un arranque posterior (como mucho una vez al día).

```powershell
# Comprobar el registro / desinstalar
schtasks /query /tn SharkyStartup
schtasks /delete /tn SharkyStartup /f
```

Si el ciclo detecta que alguna posición ha cruzado su stop-loss o su
take-profit, `scripts\avisar_niveles_windows.ps1` muestra una **ventana
emergente** con la lista al final del arranque. Lee lo que el propio ciclo
acaba de escribir en `logs\alertas_niveles.json`, así que nunca puede enseñar
números distintos de los del diario, y no vuelve a consultar el mercado. Si no
hay ningún nivel cruzado -- el caso normal -- no aparece nada.

El fichero se ignora si es de un día anterior: que el ciclo de hoy no llegara a
escribirlo es competencia del heartbeat (más abajo), no de este aviso. Repetir
aquí los stops de ayer sólo entrenaría a cerrar la ventana sin leerla.

Encender el ordenador por segunda vez el mismo día no repite el ciclo, pero sí
vuelve a comprobar los niveles: no cuesta una llamada a la API, y un stop
cruzado a media tarde no puede esperar a mañana sólo porque el diario ya
estuviera escrito.

Cada ejecución de `SharkyStartup` termina con un backup local del vault
(`scripts\backup_vault.ps1`, retiene las últimas 14 copias en `backups\`,
fuera de git). Como la bóveda no se versiona (ver principio 4), esa es su
única copia de seguridad: si quieres una copia fuera del equipo, guarda
`backups\` en un disco externo o en un repositorio **privado** aparte.

Como Sharky no es un servicio permanente, un fallo silencioso de
`SharkyStartup` (entorno virtual roto, red caída, una excepción no
capturada) no se nota en ningún sitio hasta que alguien abre el vault a
propósito. Para eso existe una segunda tarea, independiente:

```powershell
# Instalación (una sola vez, después de instalar SharkyStartup):
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_heartbeat_windows.ps1
```

Registra `SharkyHeartbeatCheck`, que comprueba `ultimo_ciclo_diario` de
`Estado_Vital.md` (el timestamp que escribe cada ciclo diario, y sólo él:
`ultima_actualizacion` también lo refresca `sharky trade`, y una operación
registrada taparía un arranque fallido) y, si lleva más de 36 horas sin
refrescarse -- o nunca se escribió --, muestra un aviso emergente además de
registrarlo en `logs\sharky_heartbeat.log`.

```powershell
# Comprobar el registro / desinstalar
schtasks /query /tn SharkyHeartbeatCheck
schtasks /delete /tn SharkyHeartbeatCheck /f
```

Para un equipo que permanece siempre encendido (NAS, servidor, VPS), sigue
disponible el servicio continuo:

```bash
docker compose up -d
# o bien: python -m sharky.cli service --interval 60
```

En ese modo el cierre diario se programa a las **22:00 en hora local**, así
que la zona horaria (`TZ`) es explícita en el contenedor.

---

## 8. Configuración

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-sonnet-5      # o claude-opus-5 para el rol de CIO
```

El escaneo semanal de noticias (`sharky noticias`) usa `CLAUDE_MODEL` por
defecto; se puede fijar aparte con `SHARKY_NEWS_MODEL`, y el día de la
semana con `SHARKY_NEWS_SCAN_WEEKDAY` (0=lunes ... 6=domingo). Igual que el
resto de la inteligencia de Sharky, sin `ANTHROPIC_API_KEY` no se ejecuta.

### El ciclo de vida de una tesis

Una tesis **nace** de una alerta ejecutada y **muere** en la venta que cierra
la posición. Hasta 2026-09 no hacía ninguna de las dos cosas sola, y las tres
omisiones tenían consecuencias silenciosas:

| Antes | Consecuencia |
| :--- | :--- |
| Comprar desde una alerta no creaba tesis | La posición recién abierta no tenía ningún stop que `level_watch` vigilara, aunque la alerta ya traía uno calculado con precios reales |
| Vender no cerraba la tesis | Una tesis activa **sin posición** es justo la condición que la vuelve candidata de COMPRA: vender por stop dejaba al motor proponiendo **recomprarla** el Día 1 siguiente |
| Ninguna alerta caducaba | Su ticker quedaba vetado para siempre en `has_active_alert`, y sus niveles congelados entraban cada mes en el rebalanceo mientras el motor tomaba precio fresco |

Ahora `TradeRecorder` cierra las dos puntas, en el mismo bloque post-asiento
que el resto de escrituras: si algo de esto falla, la operación **no se
deshace** (no se puede revertir una compra que ya ocurrió en el broker), sólo
se avisa de qué escritura quedó pendiente.

**Al comprar**, si hay una alerta activa para ese ticker: se abre la tesis con
los niveles de la **orden realmente ejecutada** (no los de la alerta: si
compraste a otro precio, manda lo que hiciste) y la alerta pasa a `EJECUTADA`.
Una tesis que ya existía escrita a mano no se sobrescribe — es convicción
propia.

**Al vender toda la posición**, la tesis se archiva en `02_Tesis_Cerradas/`
con `estado: Cerrada`, el PnL realizado y el motivo, que se deduce del
contexto: si hoy saltó un stop-loss de esa posición, lo dice. Una venta
**parcial** no cierra nada: reducir tamaño no invalida la convicción.

Aquí sí se cambia `estado`, a diferencia de la revisión mensual: cerrar una
tesis no es un juicio de un modelo sino un hecho contable. La prosa, en
cambio, sigue la misma regla — se apila una sección de cierre y no se borra
nada, porque el racional original es el material del post-mortem.

**Las alertas caducan** en el ciclo diario, por tres criterios deterministas
que dicen lo mismo desde ángulos distintos — la asimetría ya no está ahí:

* **Edad** superior a `SHARKY_ALERTA_VIGENCIA_DIAS` (30 por defecto).
* **Stop roto**: el precio cayó por debajo del stop que la propia alerta
  declaró, *antes* siquiera de entrar.
* **Objetivo alcanzado**: el precio llegó al target sin ti.

Los dos criterios de precio sólo se aplican con cotización fiable y en la
misma divisa que declaró la alerta: comparar un stop en EUR contra un precio
en USD es el error de unidades que `level_watch` ya evita en las tesis. La
caducidad corre **antes** del escaneo del radar, para que un ticker que
caduca hoy pueda volver a emitirse en el mismo ciclo con niveles medidos hoy.

---

### La revisión de tesis

Una tesis no es un documento que se escribe y se archiva: su frontmatter mueve
maquinaria viva. `level_watch` compara cada día el precio real contra
`stop_loss`, y el motor de rebalanceo ordena sus candidatos de compra por
`conviccion`. Si nadie vuelve a mirarla, la cartera acaba operando con cifras
que reflejan lo que pensabas hace meses.

Hasta 2026-09 eso pasaba: el estudio mensual dictaba MANTENER / REDUCIR /
CERRAR posición a posición, pero ese veredicto moría en la nota del estudio.
Ahora vuelve al fichero de cada tesis.

```bash
python -m sharky.cli revisar-tesis
```

En la app es la acción **«Revisar tesis»**. El estudio mensual la lanza sola
al terminar, así que en la práctica no hace falta acordarse.

**Se revisa lo que tiene algo que decir**, no las 22 tesis cada mes. La
selección es determinista y no gasta API:

| Señal | Qué detecta |
| :--- | :--- |
| Movimiento del mes ≥ 15% | La deriva lenta que ningún aviso diario marca |
| Nivel alcanzado | Stop o target tocados |
| Incumplimiento abierto | La posición excede un límite del mandato |
| Noticias del mes | El activo tuvo sección propia en algún escaneo semanal |
| **Red de seguridad** | 3 meses sin que nadie la mire, aunque no se haya movido |

Generar prosa sobre una posición donde no pasó nada es justamente donde nace
la deriva narrativa; la red de seguridad evita el problema contrario, que una
tesis tranquila quede olvidada para siempre. Se cuenta desde `fecha_revision`
o, si nunca se revisó, desde `fecha_apertura`: una tesis escrita ayer no
necesita revisión hoy.

**Dos invariantes que el código sostiene, no sólo el prompt:**

**1. Añade, nunca sobrescribe.** Cada revisión apila una sección fechada:

```markdown
## 🔄 Revisión 2026-10-01 — 🟡 REDUCIR

> Seleccionada para revisión porque: nivel alcanzado, noticias del mes.

**Qué ha cambiado:** …
**Qué sigue en pie:** …
**Qué la invalidaría ahora:** …
```

La nota crece hacia abajo y se lee como una cronología. Es deliberado: la
única pregunta que enseña algo es *¿tenía razón mi tesis de agosto?*, y no se
puede responder si la tesis de agosto ya no existe. Una nota reescrita cada
mes acaba explicando lo que el precio ya hizo, que es peor que una tesis
obsoleta porque *parece* vigente.

**2. No toca un solo número.** `stop_loss`, `target_precio`, `conviccion`,
`precio_entrada`, `estado` y el resto de `VaultManager.CAMPOS_INTOCABLES` son
inmutables desde aquí. Sólo se escriben dos campos nuevos, `fecha_revision` y
`veredicto_revision`, y el frontmatter se edita como texto -- no reserializando
el YAML -- para que las líneas que la revisión no escribe queden byte a byte
idénticas. Si la revisión cree que un nivel debería moverse, lo escribe como
propuesta marcada `NO aplicada` y la aplicas tú.

El motivo es concreto: el stop-loss es la única salida obligatoria del
mandato. Si pudiera renegociarse cada mes, una posición que se acerca a su
stop recibiría uno un poco más bajo con una justificación impecable -- "la
tesis sigue intacta" -- y así es como una posición perdedora sobrevive a su
propia invalidación. Mismo reparto que ya aceptas en el take-profit: Sharky
propone, tú decides.

Lo que la revisión **no** hace es cerrar tesis. Un `CERRAR` sigue siendo una
propuesta: la tesis se archiva cuando vendes o cuando aceptas el veredicto.
Que un modelo archive tu convicción sin que hayas tocado la posición deja la
cartera operando con una tesis que ya nadie sostiene.

---

### El explorador de mercado

El radar tiene dos piezas con responsabilidades distintas, y conviene no
confundirlas:

| | Detector (`opportunity_detector.py`) | Explorador (`market_explorer.py`) |
| :--- | :--- | :--- |
| **Qué hace** | Confirma o descarta con datos reales | Busca ideas que nadie había escrito |
| **Universo** | `UNIVERSO_CONVICCION`, una lista a mano | El mercado, vía búsqueda web |
| **Cuándo** | En cada control diario y cada vigilancia | Sólo cuando tú lo pides |
| **Coste** | Gratis (determinista, sin API) | ~1–2,50 $ por exploración |

El detector nunca puede encontrar un nombre que no esté ya en su lista: sólo
sabe decir si el precio de un candidato conocido ofrece asimetría hoy. El
explorador es lo que amplía esa lista.

```bash
python -m sharky.cli explorar
```

En la app es el botón **«Buscar oportunidades»** de la tarjeta *Oportunidades
en radar*.

Usa `SHARKY_EXPLORER_MODEL` (Claude Opus 5 por defecto, el modelo más capaz;
**no** hereda `CLAUDE_MODEL`) porque redactar una tesis de inversión desde
cero es el razonamiento más exigente de toda la cadencia. El resto de topes
--presupuesto, búsquedas y número de candidatos-- están en `.env.example`.

**La frontera entre convicción y confirmación no se mueve.** Claude aporta
exactamente lo mismo que aporta `UNIVERSO_CONVICCION`: qué vigilar y por qué
hay foso económico. El prompt le prohíbe proponer precios, stops u objetivos,
y el modelo de datos del candidato ni siquiera tiene dónde guardarlos: esos
números los calcula después el mismo filtro de siempre, con la estructura real
de precios. Un nivel inventado por un modelo tiene el mismo aspecto que uno
medido y ninguna de sus garantías.

La consecuencia es deliberada: **una exploración puede terminar con ocho
candidatos interesantes y cero alertas.** No es un fallo, es el filtro
haciendo su trabajo -- la empresa puede ser excelente y su precio no ofrecer
asimetría hoy. El informe (`09_Alertas_Oportunidades/Exploraciones/`) guarda
el veredicto de cada candidato y su motivo, para poder volver sobre las ideas
cuando el precio acompañe.

Sharky no tiene modo simulación: toda operación registrada con `sharky trade`
es una compra o venta real que ya ejecutaste en Trade Republic, y se asienta
como tal en `Cartera_Real.md`.

Sin API key el sistema **sigue siendo funcional**: calcula NAV, riesgo,
incumplimientos y rebalanceo de forma determinista. Lo único que pierde es la
interpretación, y los informes lo indican. Con
`SHARKY_ALLOW_SIMULATED_INTELLIGENCE=false` un fallo de la API interrumpe la
ejecución en lugar de generar prosa de plantilla.

El trailing de reserva del take-profit se fija con `SHARKY_TRAILING_STOP_PCT`
(8% por defecto); sólo se usa en tesis que no declaran precio de entrada o
stop, porque en el resto el trailing sale del riesgo inicial de la propia
tesis.

Los límites de riesgo se pueden sobrescribir por variable de entorno, pero sus
valores por defecto replican `Reglas_De_Supervivencia.md`. Si cambias uno,
cambia también la nota: el mandato escrito y el código no deben divergir. Todas
las opciones están documentadas en `.env.example`.

---

## 9. Migraciones

Scripts de un solo uso, idempotentes, en `scripts/`:

| Script | Para qué |
| :--- | :--- |
| `migrar_a_eur.py` | Limpia el estado heredado de la versión en USD: resiembra el máximo histórico del NAV y caduca las alertas del detector antiguo. El capital de referencia se pasa con `--capital-referencia`. |
| `consolidar_vault.py` | Fusiona notas duplicadas del mismo activo y reapunta los wikilinks. Admite `--dry-run`. |
| `reparar_enlaces_vault.py` | Crea las fichas y notas de sector que faltan y reapunta a su ficha los enlaces por ticker (`[[RHM]]` → `[[Rheinmetall\|RHM]]`) que dejaba el texto de Claude antes de que `VaultManager` los normalizara al escribir. Lo que no resuelve a nada queda como texto plano. |

---

## 10. Alcance y limitaciones

* **No hay conexión con el broker.** Sharky propone y registra; ejecutar es tuyo.
* **Los datos vienen de Yahoo Finance** vía `yfinance`: suficiente para valorar y
  vigilar, no una fuente institucional. Los múltiplos P/E no están normalizados.
* **El `coste_unitario_eur` del libro usa coste medio ponderado.** Si tu
  fiscalidad requiere FIFO, el PnL realizado que calcula Sharky no coincidirá con
  el fiscal.
* **Esto no es asesoramiento financiero.** Es un sistema de apoyo a la decisión
  cuyas propuestas debes revisar antes de ejecutar.

---

## 11. Licencia y autor

Desarrollado por **Alejandro Marqués**.
