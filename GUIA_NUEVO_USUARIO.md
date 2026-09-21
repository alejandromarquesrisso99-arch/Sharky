# Guía para empezar con Sharky

Sharky vigila tu cartera cada día. La valora a precios de mercado, comprueba
tus stop-loss y los límites de riesgo de su mandato, y le pide a Claude que
razone sobre ella: un control diario, un repaso semanal de noticias y un
estudio mensual. Todo queda escrito en una carpeta de notas que puedes leer
con Obsidian.

Dos cosas que conviene saber desde el principio:

- **Sharky no opera por ti.** No se conecta con tu bróker. Tú compras y
  vendes allí, y le cuentas a Sharky lo que has hecho.
- **No es asesoramiento financiero.** Sus propuestas son para que las
  revises; la decisión es siempre tuya.

Esta guía te lleva desde cero hasta tenerlo funcionando. La referencia
completa está en el [README](README.md).

---

## Antes de empezar

- **Windows 10 u 11.** Sharky funciona en cualquier sistema desde la línea
  de comandos, pero el arranque automático y los accesos directos son para
  Windows.
- **Python 3.11 o superior**, de [python.org](https://www.python.org/downloads/).
  Al instalarlo, marca «Add python.exe to PATH».
- **Git**, de [git-scm.com](https://git-scm.com/download/win).
- **Una clave de la API de Claude**, de
  [console.anthropic.com](https://console.anthropic.com). Se paga por uso,
  en tu cuenta. Es opcional: sin ella Sharky funciona en modo simulado, pero
  sin el razonamiento de Claude, sin noticias y sin revisión de tesis.
- **Obsidian** (opcional), de [obsidian.md](https://obsidian.md), para leer
  las notas que escribe Sharky.
- **Tus posiciones:** de cada una, cuántos títulos tienes y a qué precio
  medio los compraste, en euros.

---

## Paso 1 · Descargar e instalar

Abre el «Símbolo del sistema» (cmd) en la carpeta donde quieras tener
Sharky y ejecuta, de una en una:

```bat
git clone https://github.com/alejandromarquesrisso99-arch/Sharky.git
cd Sharky
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Cada vez que abras una terminal nueva para usar Sharky, entra en la carpeta
y vuelve a ejecutar `.venv\Scripts\activate`.

> Usa cmd y no PowerShell: PowerShell suele bloquear el script de
> activación del entorno.

---

## Paso 2 · Preparar el CSV con tus posiciones

Sharky importa tu cartera desde un CSV: un fichero de texto con una
posición por línea y las columnas en este orden, separadas por `;`:

| # | Columna | | Qué va |
| ---: | :--- | :--- | :--- |
| 1 | `ticker` | obligatoria | Nombre corto de la posición, sin espacios (`SAN`) |
| 2 | `nombre` | obligatoria | Empresa o fondo |
| 3 | `isin` | opcional | Código ISIN (`ES0113900J37`) |
| 4 | `unidades` | obligatoria | Títulos que tienes, con decimales si los hay |
| 5 | `coste_medio_eur` | obligatoria | Precio medio **de compra** por título, en euros |
| 6 | `divisa` | obligatoria | Divisa en la que cotiza: `EUR`, `USD`, `GBp`... |
| 7 | `sector` | opcional | Sector, sin espacios (`Banca`, `Tecnologia`) |
| 8 | `simbolo` | opcional | Símbolo en Yahoo Finance (`SAN.MC`) |
| 9 | `clase` | opcional | `ACCION` (por defecto), `ETF`, `ETC` o `CRIPTO` |

Ejemplo, con cifras inventadas:

```
ticker;nombre;isin;unidades;coste_medio_eur;divisa;sector;simbolo;clase
SAN;Banco Santander;ES0113900J37;200;4,50;EUR;Banca;SAN.MC;ACCION
IWDA;iShares Core MSCI World;IE00B4L5Y983;5;80,00;EUR;Renta_Variable_Global;IWDA.AS;ETF
```

Puedes prepararlo con Excel: guárdalo como «CSV (delimitado por punto y
coma)». O pídeselo a Claude a partir del extracto de tu bróker, con algo
como:

> Te paso el extracto de mi cartera. Conviértelo en un CSV separado por
> `;` con estas columnas, en este orden: ticker;nombre;isin;unidades;
> coste_medio_eur;divisa;sector;simbolo;clase. `coste_medio_eur` es el
> precio medio de compra por título en euros, no el precio actual. `divisa`
> es la divisa en la que cotiza cada activo. Si no sabes el símbolo de
> Yahoo Finance, deja la columna vacía.

Dos avisos:

- **El precio medio de compra no suele venir en los extractos**, que
  muestran el valor actual. Sácalo de la app del bróker. Si pones el precio
  actual, Sharky calculará mal tus ganancias.
- **Si le pasas el PDF a Claude, lo estás enviando a Anthropic.** Si
  prefieres no hacerlo, copia los datos a mano desde la app del bróker.

Con el símbolo vacío, Sharky lo busca en su propio registro. Si no lo
encuentra, valora esa posición a su precio de compra hasta que se lo añadas
(ver «Problemas frecuentes»).

---

## Paso 3 · Configurar Sharky

```bat
python -m sharky.cli init
```

El asistente se abre también solo si lanzas cualquier otro comando, o la
app, antes de configurar nada. Te pide:

1. **La clave de Claude.** No se ve al escribirla. Se guarda en el archivo
   `.env` de la carpeta de Sharky, que es tu archivo de configuración: ahí
   puedes cambiarla después, y ajustar el resto de opciones que explica
   `.env.example`.
2. **La ruta de tu CSV.** Si todavía no lo tienes, pulsa Enter y crea una
   plantilla para rellenar. Si el CSV tiene errores, te los enumera con su
   número de línea y vuelve a pedírtelo.
3. **El efectivo** que tienes en la cuenta y **tu bróker**.

No escribe nada hasta que confirmas el resumen final. Después crea tu
libro de posiciones, una ficha por posición y la estructura de notas.

---

## Paso 4 · Una tesis con stop-loss por cada posición

Este paso es el más importante: **sin tesis, Sharky no vigila ningún
stop-loss**. La tesis es una nota que dice por qué tienes esa posición,
dónde sales si va mal (stop) y dónde tomarías beneficios (objetivo).

Crea un fichero por posición en `vault\01_Tesis_Activas\`, por ejemplo
`Tesis_SAN.md`, con este contenido adaptado a la tuya (cifras inventadas):

```markdown
---
ticker: SAN
empresa: "Banco Santander"
tipo: Largo
estado: Activa
precio_entrada: 4.50
divisa: EUR
stop_loss: 4.00
target_precio: 6.00
conviccion: 7
fecha_apertura: 2026-09-22
sectores: "[[Banca]]"
empresa_nota: "[[SAN]]"
---

# 🎯 Tesis: Banco Santander (SAN)

## Por qué la tengo

...

## Qué me haría vender

...
```

- `ticker` debe ser **exactamente** el mismo que en tu CSV.
- `divisa` es la divisa en la que escribes `precio_entrada`, `stop_loss` y
  `target_precio`. Si falta, Sharky entiende EUR: un stop en dólares sin
  `divisa: USD` se compararía mal.
- `estado` tiene que ser `Activa` y `conviccion` un número del 1 al 10.
- También puedes partir de la plantilla
  `vault\07_Plantillas\Plantilla_Tesis.md`: cópiala y sustituye **todos**
  los `{{...}}`. Si queda alguno, Sharky no puede leer la tesis ni vigilar
  su stop, y lo avisa en la consola con «Tesis ilegible».

---

## Paso 5 · Usar Sharky

```bat
python -m sharky.cli status
python -m sharky.cli portfolio
python -m sharky.cli daily
python -m sharky.app
```

- `status` enseña tu estado de salud, el valor de la cartera y los avisos.
- `portfolio` enseña cada posición valorada a mercado.
- `daily` hace el control diario completo y le pide a Claude que lo razone.
- `python -m sharky.app` abre la app, con todo lo anterior en ventanas
  (ver «Cómo funciona la app», justo debajo).
- Para leer las notas, abre la carpeta `vault` de Sharky como bóveda en
  Obsidian («Open folder as vault»).

**Es normal ver avisos el primer día.** Sharky compara tu cartera con su
mandato de riesgo, y lo habitual es que una cartera real no lo cumpla
entero. Los límites por defecto son:

| Regla | Límite |
| :--- | :--- |
| Peso máximo de una posición | 10 % del total (5 % en estado de alerta) |
| Peso máximo de un sector | 25 % |
| Efectivo | entre el 15 % y el 30 % |
| Estado según la caída desde el máximo | Óptimo hasta el 3 %, Alerta hasta el 8 %, Cuidados Intensivos hasta el 20 % |

Si quieres otros, cámbialos en `.env` (`SHARKY_MAX_POS_PCT`,
`SHARKY_MAX_SECTOR_PCT`, `SHARKY_MIN_CASH_PCT`...).

---

## Cómo funciona la app

La app hace lo mismo que los comandos, pero con ventanas y botones. Ábrela
con `python -m sharky.app` o con el acceso directo «Sharky» (ver Paso 7).
Se abre en una ventana propia de Edge o Chrome y sólo funciona en tu
ordenador: nadie más puede entrar en ella, ni siquiera otra web que tengas
abierta en el navegador.

A la izquierda, o abajo si la ventana es estrecha, están sus cuatro
pantallas: **Panel**, **Informes**, **Operar** y **Sistema**. El número rojo
junto a Panel cuenta los avisos graves. Junto al título de cada pantalla
hay un botón para cambiar el tema: claro, oscuro o el del sistema.

### Panel: cómo está tu cartera

De arriba abajo:

- **Estado vital:** Óptimo, Alerta o Cuidados Intensivos, tu patrimonio
  total y una barra con cuánto ha caído desde su máximo, con las marcas del
  3 % y el 8 % donde cambia de estado.
- **Resumen:** ganancias sin realizar, efectivo frente a su objetivo, número
  de posiciones (y cuántas tienen tesis), incumplimientos del mandato, qué
  parte de la cartera tiene precio de mercado fiable y cuándo fue el último
  control diario.
- **Requiere atención:** lo que tienes que mirar. Stops alcanzados (salida
  obligatoria), objetivos alcanzados, incumplimientos del mandato con la
  corrección que propone Sharky y problemas con los datos. Si no hay nada,
  pone «Todo en orden».
- **Evolución del NAV:** un gráfico de tu patrimonio, que aparece a partir
  del segundo control diario.
- **Control diario, Noticias semanales y Estudio mensual:** una tarjeta por
  cada razonamiento de Claude. Dicen si toca hacerlo («Pendiente», «Toca
  hoy», «Hecho hoy»), enseñan su última conclusión y traen un botón para
  lanzarlo y otro para leer el informe completo.
- **Posiciones:** una tabla con la cotización, el valor, el peso, las
  ganancias, cuánto se ha movido cada una desde el último control (resaltado
  a partir del 7 %) y el stop y el objetivo de su tesis. Pulsa una cabecera
  para ordenar por esa columna.
- **Exposición sectorial:** el peso de cada sector frente al límite del 25 %.
- **Oportunidades en radar:** las alertas de compra activas y el botón
  «Buscar oportunidades», que lanza una exploración de mercado.

«Actualizar precios», junto al título, vuelve a valorar la cartera con los
precios del momento. Es gratis: no llama a Claude.

### Informes: todo lo que ha escrito Sharky

Un lector de las notas de la bóveda, para no tener que abrir Obsidian. Las
pestañas separan controles diarios, noticias semanales, estudios mensuales,
planes de rebalanceo, operaciones, tesis activas, alertas de oportunidad y
exploraciones de mercado. Puedes filtrar por título o fecha, y los enlaces
entre notas se pueden pulsar. Si un informe se hizo sin Claude, lo marca con
«Generado sin Claude».

### Operar: registrar una compra o venta

Es lo mismo que `sharky trade`, en un formulario. Rellenas el sentido
(compra o venta), el ticker (te sugiere los de tu cartera), las unidades, el
precio al que se ejecutó, la comisión en euros y, en las compras, el stop y
el objetivo. Aquí los decimales pueden ir con coma. Para una posición nueva,
despliega «Posición nueva o datos adicionales» y añade su nombre, ISIN,
símbolo, sector y clase.

A la derecha ves tu posición actual en ese ticker (unidades, valor, peso,
ganancias y el stop de su tesis) y los límites del mandato. «Revisar y
registrar» te pide confirmación antes de escribir nada:

- **Si la operación rompe una regla del mandato,** Sharky la rechaza, te
  dice por qué y no toca tu libro. La casilla «Registrar aunque incumpla el
  mandato» la registra igualmente, con el aviso.
- **Si compras algo que estaba en el radar,** Sharky abre su tesis con el
  stop y el objetivo que has puesto.
- **Si vendes toda una posición,** archiva su tesis.

La pantalla te enseña en cada caso qué ha cambiado, con un botón para abrir
la nota.

### Sistema: la IA, las acciones y el apagado

Enseña si la clave de Claude está conectada, qué modelo usa cada tipo de
razonamiento y el historial de lo que has lanzado desde que abriste la app.
Desde aquí se lanza cualquier acción:

| Acción | Qué hace | Coste aproximado |
| :--- | :--- | ---: |
| Comprobar niveles | Mira si algún precio ha cruzado su stop u objetivo | Gratis |
| Control diario | Valoración, niveles, radar y el razonamiento del día | 0,02–0,05 $ |
| Escaneo de noticias | Busca en la web noticias de cada posición | 0,70–1,10 $ |
| Estudio mensual | Plan de rebalanceo y repaso de cada posición con todo el mes | 0,80–1,80 $ |
| Plan de rebalanceo | Sólo el plan de ajustes del mes, sin Claude | Gratis |
| Revisar tesis | Añade una revisión fechada a las tesis con novedades; nunca cambia un stop por su cuenta | 0,30–0,80 $ |
| Explorar el mercado | Busca en la web ideas de inversión nuevas y las pasa por el filtro de Sharky | 1–2,50 $ |
| Comité de inversión | Opinión de las cuatro mesas y resolución final sobre la cartera | 0,20 $ |

Los costes se pagan en tu cuenta de Anthropic y son orientativos.

### Cómo se lanza una acción

1. Pulsas su botón y la app te explica qué hace y cuánto cuesta, y te avisa
   si ya se hizo (por ejemplo, si el control de hoy ya está hecho).
2. Si aceptas, corre en segundo plano: puedes seguir usando la app. Un
   recuadro enseña cuánto lleva y lo que va haciendo.
3. Al terminar, el recuadro resume el resultado, con un botón para abrir el
   informe que ha escrito.

Las acciones van de una en una: mientras una está en marcha, la app no deja
lanzar otra.

### Cerrar la app

**Cerrar la ventana no apaga la app:** el servidor sigue funcionando en
segundo plano. Para apagarla, ve a **Sistema** y pulsa «Apagar la app». Si
abres el acceso directo con la app ya en marcha, sólo se abre otra ventana.

---

## Paso 6 · Registrar cada compra y venta

Cuando operes en tu bróker, cuéntaselo a Sharky para que tu libro siga
cuadrando. En la línea de comandos los decimales van con **punto**:

```bat
python -m sharky.cli trade compra SAN 50 4.80 --stop 4.30 --target 6.00 --comision 1.00
python -m sharky.cli trade venta SAN 50 5.20 --motivo "Toma de beneficios"
```

- En las compras, `--stop` y `--target` son obligatorios.
- Para una posición nueva hay que dar su identidad:

  ```bat
  python -m sharky.cli trade compra ASML 0.5 720.00 --stop 660 --target 900 --divisa USD --simbolo ASML --isin NL0010273215 --nombre "ASML Holding N.V." --sector Semiconductores --clase ACCION
  ```

- Si la operación rompe una regla del mandato, Sharky la rechaza y te dice
  por qué. Si aun así es lo que hiciste, `--forzar` la registra con el aviso.
- Lo mismo se puede hacer desde la app, en la pantalla **Operar**.

---

## Paso 7 · Que funcione solo (Windows, opcional)

Tres instaladores, que se ejecutan una sola vez desde la carpeta de Sharky:

```bat
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_inicio_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_heartbeat_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_app_windows.ps1
```

1. **Arranque automático.** Al iniciar sesión cada día, Sharky hace el
   control diario, como mucho una llamada a Claude al día. Los domingos
   hace además el repaso de noticias (o en el primer arranque, si llevaba
   una semana sin hacerlo), y en el primer arranque de cada mes, el estudio
   mensual. Si ve un stop cruzado, te avisa con una ventana emergente.
2. **Vigilante.** Te avisa si el arranque automático lleva más de un día y
   medio sin funcionar.
3. **Accesos directos** «Sharky» en el Escritorio y en el menú Inicio para
   abrir la app.

Ninguno necesita permisos de administrador.

---

## Mantener Sharky al día

```bat
git pull
pip install -r requirements.txt
```

Actualizar no toca tus datos: git ignora tu `.env`, tus CSV y tu bóveda.

---

## Tu privacidad

- **Tus datos no se suben nunca a GitHub.** Git ignora el `.env` (tu clave),
  los CSV, los PDF y toda la bóveda, salvo las plantillas y las notas de
  reglas, que no llevan datos de nadie.
- **La copia de seguridad es cosa tuya.** Con el arranque automático
  instalado, Sharky guarda una copia comprimida de la bóveda en `backups\`
  cada día. Guárdala también fuera del ordenador.
- **Si colaboras en el código,** no uses nunca `git add -f` sobre la
  bóveda, y usa cifras inventadas en tests y ejemplos.

---

## Problemas frecuentes

| Qué ves | Qué hacer |
| :--- | :--- |
| «Sharky todavía no está configurado» | `python -m sharky.cli init` |
| Una posición aparece «sin símbolo» o valorada a coste | `python -m sharky.cli resolve-isin` sugiere su símbolo. Añádelo como `ticker_cotizacion` en `vault\00_Sistema\Cartera_Real.md` |
| El diario dice «simulado» | Falta la clave de Claude: ponla en `.env` (`ANTHROPIC_API_KEY=...`) |
| Sharky no vigila el stop de una posición | Revisa la tesis: el `ticker` igual que en el libro, `estado: Activa`, la `divisa` de sus niveles y ningún `{{...}}` sin rellenar (si la consola dice «Tesis ilegible», es esto último) |
| El arranque automático no hace nada | Mira `logs\sharky_startup.log`. Si pone que no está configurado, ejecuta `init` en una terminal |
| `python` no se reconoce como comando | Reinstala Python marcando «Add python.exe to PATH» |
