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
- `python -m sharky.app` abre la app, con todo lo anterior en ventanas.
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

La app muestra el coste estimado de cada acción que llama a Claude antes de
lanzarla. Como referencia, una exploración de mercado cuesta de 1 a 2,50 $.

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
