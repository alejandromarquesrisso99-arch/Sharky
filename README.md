# Sharky Capital Management: Family Office Autónomo

> Fondo institucional / *family office* digital que gestiona una cartera real
> custodiada en Trade Republic. Combina una **estructura departamental**
> (Macro, Fundamental, Riesgo y Psicología de Mercado), un **libro de posiciones
> contable** como fuente de verdad, un **cortafuegos de riesgo determinista** y
> **Obsidian** como memoria de largo plazo, con **Claude** en el rol de *Chief
> Investment Officer*.

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
| `sharky/trade_ledger.py` | Registro de operaciones. Único camino de escritura al libro. |
| `sharky/rebalance_engine.py` | Plan del Día 1 por prioridades del mandato. |
| `sharky/opportunity_detector.py` | Radar de asimetrías con confirmación cuantitativa. |
| `sharky/firm_departments.py` | Las cuatro mesas. |
| `sharky/firm_committee.py` | Comité y resolución del CIO. |
| `sharky/claude_client.py` | Cliente de la API de Claude, con fallback declarado. |
| `sharky/vault_manager.py` | Lectura y escritura de notas de Obsidian. |
| `sharky/agent_loop.py` | Orquestación de los ciclos. |
| `sharky/scheduler.py` | Servicio 24/7. |

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
├── 05_Diario_Reflexion/               # Actas diarias
├── 06_Lecciones_Aprendidas/           # Heurísticas
├── 07_Plantillas/                     # Plantillas
├── 08_Rebalanceos_Mensuales/          # Propuestas del Día 1
└── 09_Alertas_Oportunidades/          # Oportunidades asimétricas
```

`Estado_Vital.md` no sólo lista los incumplimientos del mandato vigentes:
recuerda desde cuándo lleva abierto cada uno (`incumplimientos_desde`) y lo
marca como **escalado** si supera `SHARKY_BREACH_ESCALATION_DAYS` (7 días
por defecto) -- para que una brecha que el `RiskGovernor` detecta pero nadie
corrige deje de pasar desapercibida sólo por volver a aparecer, idéntica,
en cada ciclo.

El nombre de una ficha no siempre es el ticker: la de Rheinmetall es
`Rheinmetall`, no `RHM`. La correspondencia la declara el campo `nota_activo` del
libro de posiciones, y los nombres alternativos viven como `aliases`, de modo que
escribir `[[RHM]]` en Obsidian sigue resolviendo.

---

## 5. Comandos

```bash
# Estado vital, NAV e incumplimientos del mandato
python -m sharky.cli status

# Cartera valorada a mercado, con exposición sectorial y procedencia de precios
python -m sharky.cli portfolio

# Auditoría de riesgo contra las reglas de supervivencia
python -m sharky.cli risk

# Vigilancia diaria: valoración, stop-loss, radar y diario en Obsidian
python -m sharky.cli daily

# Propuesta de rebalanceo del Día 1 (qué vender y qué comprar)
python -m sharky.cli monthly

# Sesión plenaria del Comité de Inversión con los cuatro departamentos
python -m sharky.cli committee

# Alertas de oportunidad activas
python -m sharky.cli alerts

# Termómetro macroeconómico (SPY, QQQ, TLT, GLD, USO)
python -m sharky.cli macro

# Ciclo diario para lanzar al encender el ordenador (ver §7): si el ciclo de
# hoy ya se ejecutó, no vuelve a llamar a la API de Claude
python -m sharky.cli startup

# Servicio autónomo 24/7 (para un equipo que permanece siempre encendido)
python -m sharky.cli service --interval 60
```

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

cp .env.example .env          # y añade tu ANTHROPIC_API_KEY
```

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
encender el ordenador e iniciar sesión**. Ejecuta el ciclo diario completo
(mercados, cartera, stop-loss, radar de oportunidades, diario en Obsidian y,
el día 1 de cada mes, la propuesta de rebalanceo) y actualiza la bóveda.

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

```powershell
# Comprobar el registro / desinstalar
schtasks /query /tn SharkyStartup
schtasks /delete /tn SharkyStartup /f
```

Cada ejecución de `SharkyStartup` termina con un backup local del vault
(`scripts\backup_vault.ps1`, retiene las últimas 14 copias en `backups\`,
fuera de git) -- además del propio git, para cubrir un fallo de disco antes
de hacer commit o un `git push` que todavía no se ha ejecutado.

Como Sharky no es un servicio permanente, un fallo silencioso de
`SharkyStartup` (entorno virtual roto, red caída, una excepción no
capturada) no se nota en ningún sitio hasta que alguien abre el vault a
propósito. Para eso existe una segunda tarea, independiente:

```powershell
# Instalación (una sola vez, después de instalar SharkyStartup):
powershell -ExecutionPolicy Bypass -File .\scripts\instalar_heartbeat_windows.ps1
```

Registra `SharkyHeartbeatCheck`, que comprueba `ultima_actualizacion` de
`Estado_Vital.md` (el mismo timestamp que ya escribe cada ciclo) y, si
lleva más de 36 horas sin refrescarse -- o nunca se escribió --, muestra un
aviso emergente además de registrarlo en `logs\sharky_heartbeat.log`.

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
SHARKY_BASE_CURRENCY=EUR
SHARKY_EXECUTION_MODE=PAPER       # PAPER | REAL
```

Sin API key el sistema **sigue siendo funcional**: calcula NAV, riesgo,
incumplimientos y rebalanceo de forma determinista. Lo único que pierde es la
interpretación, y los informes lo indican. Con
`SHARKY_ALLOW_SIMULATED_INTELLIGENCE=false` un fallo de la API interrumpe la
ejecución en lugar de generar prosa de plantilla.

Los límites de riesgo se pueden sobrescribir por variable de entorno, pero sus
valores por defecto replican `Reglas_De_Supervivencia.md`. Si cambias uno,
cambia también la nota: el mandato escrito y el código no deben divergir. Todas
las opciones están documentadas en `.env.example`.

---

## 9. Migraciones

Scripts de un solo uso, idempotentes, en `scripts/`:

| Script | Para qué |
| :--- | :--- |
| `migrar_a_eur.py` | Limpia el estado heredado de la versión en USD: resiembra el máximo histórico del NAV y caduca las alertas del detector antiguo. |
| `consolidar_vault.py` | Fusiona notas duplicadas del mismo activo y reapunta los wikilinks. Admite `--dry-run`. |

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
