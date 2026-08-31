# 🦈 Sharky: Cerebro Digital de Inversión & Supervivencia

> **Sharky** es una arquitectura de agente autónomo diseñada para operar en los mercados financieros utilizando **Obsidian** como su sistema de memoria a largo plazo (grafo de conocimiento en Markdown) y **Claude** (Anthropic) como su motor cognitivo de razonamiento, condicionado por un **mecanismo de supervivencia biológico-digital**.

---

## 🧭 1. Concepto y Filosofía de Supervivencia

A diferencia de los asistentes genéricos de trading, Sharky opera bajo una **directiva ontológica de supervivencia**:
* **El Capital es Vida:** Su salud (`Salud %`) disminuye ante caídas de capital (*Drawdowns*) y se restablece al cerrar operaciones rentables.
* **Metabolismo y Consumo Energético:** Cada día de cómputo y análisis consume energía metabólica. Para no entrar en *hibernación*, el agente debe generar valor positivo.
* **Muerte del Proceso:** Si la cartera experimenta un drawdown superior al **20%**, el cerebro entra en estado `💀 MUERTE` y cesa permanentemente la apertura de nuevas posiciones.

```
┌─────────────────────────────────────────────────────────────┐
│                 1. FUENTES DE DATOS EXTERNOS                │
│    (Cotizaciones en tiempo real, Ratios P/E, Noticias)      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 2. MOTOR ORQUESTADOR SHARKY                 │
│  - Vault Manager (Lectura/Escritura YAML & Wikilinks)       │
│  - Risk Governor (Cortafuegos determinista no-IA)           │
│  - Claude Brain Client (Razonamiento / Modo Simulación)     │
└───────────────────▲─────────────────────▲───────────────────┘
                    │                     │
                    ▼                     ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│ 3. MEMORIA (Bóveda Obsidian) │ │ 4. ESTADO VITAL            │
│  - 00_Sistema/               │ │  - Salud: 0% - 100%        │
│  - 01_Tesis_Activas/         │ │  - Energía: 0 - 100        │
│  - 03_Activos/ (Sectores)    │ │  - Estado: Óptimo / Alerta │
│  - 04_Operaciones_Bitacora/  │ │             / Cuidados /   │
│  - 05_Diario_Reflexion/      │ │             / Muerte       │
│  - 06_Lecciones_Aprendidas/  │ └────────────────────────────┘
└──────────────────────────────┘
```

---

## 🗂️ 2. Estructura de la Bóveda de Obsidian (`vault/`)

Puedes abrir la carpeta `vault/` directamente como una **Bóveda (Vault)** en la aplicación de escritorio de **Obsidian**:

```text
vault/
├── .obsidian/                           # Ajustes base para Obsidian
├── 00_Sistema/
│   ├── Reglas_De_Supervivencia.md       # Leyes inmutables de riesgo y dimensionamiento
│   ├── Estado_Vital.md                  # Dashboard en tiempo real de salud, capital y PnL
│   ├── Prompt_Sistema.md                # Metaprompt de identidad e instinto de supervivencia
│   └── Metricas_Riesgo.md               # Fórmulas de Kelly, Stop-Loss y Drawdown
├── 01_Tesis_Activas/                   # Tesis de inversión abiertas con frontmatter YAML
│   └── Tesis_NVDA_Ejemplo.md
├── 02_Tesis_Cerradas/                  # Historial archivado de tesis concluidas
├── 03_Activos/                         # Base de datos interconectada de empresas y sectores
│   ├── Sectores/                        # [[Semiconductores]], [[Inteligencia_Artificial]]
│   └── Empresas/                        # [[NVDA]], [[ASML]]
├── 04_Operaciones_Bitacora/            # Registro cronológico de órdenes ejecutadas (Paper/Real)
│   └── 2026-08-31_Paper_NVDA_Compra.md
├── 05_Diario_Reflexion/                # Entradas diarias de autocrítica y cierre de sesión
│   └── 2026-08-31_Genesis_Cerebro.md
├── 06_Lecciones_Aprendidas/            # Heurísticas generadas por el cerebro tras auditorías
│   └── Heuristica_01_Preservacion_Capital.md
└── 07_Plantillas/                      # Plantillas reutilizables para nuevas notas
```

---

## 🚀 3. Puesta en Marcha Rápida

### 1. Clonar el repositorio y acceder a la carpeta
```bash
git clone https://github.com/alejandromarquesrisso99-arch/Sharky.git
cd Sharky
```

### 2. Crear un entorno virtual e instalar dependencias
```bash
python -m venv .venv

# En Windows (PowerShell):
.venv\Scripts\Activate.ps1

# En Linux / macOS:
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
Copia la plantilla `.env.example` a un archivo `.env`:
```bash
cp .env.example .env
```

---

## 🔌 4. Conectar con Claude (Anthropic API)

El sistema viene preparado para funcionar de dos formas:

1. **Modo Simulación (Sin API Key):**
   Si dejas `ANTHROPIC_API_KEY` vacía en tu archivo `.env`, Sharky funcionará con su motor de simulación local, permitiéndote probar la sincronización con Obsidian, los cálculos de salud y las validaciones de riesgo sin coste de tokens ni errores.

2. **Modo Live con Claude:**
   Cuando desees activar el cerebro con Claude, edita el archivo `.env` e introduce tu clave:
   ```env
   ANTHROPIC_API_KEY=sk-ant-api03-...
   CLAUDE_MODEL=claude-3-7-sonnet-20250219
   ```

---

## 💻 5. Comandos de la CLI de Sharky

El ejecutable `sharky` (o `python -m sharky.cli`) incluye los siguientes comandos:

### Ver el Estado Vital y Métricas de Salud
Muestra el panel de control del agente en la terminal:
```bash
python -m sharky.cli status
```

### Ejecutar un Ciclo Diario de Mercado
Evalúa las cotizaciones actuales, calcula el PnL de las tesis activas, actualiza `Estado_Vital.md` y redacta la entrada del día en `05_Diario_Reflexion/`:
```bash
python -m sharky.cli cycle
```

### Consultar Precios de la Watchlist
Muestra una tabla con los activos vigilados y sus métricas financieras:
```bash
python -m sharky.cli market
```

### Iniciar el Modo Daemon (Automático)
Ejecuta el cerebro en segundo plano a intervalos regulares:
```bash
python -m sharky.cli daemon --interval 60
```

---

## 🛡️ 6. Leyes de Gestión de Riesgo (`RiskGovernor`)

El módulo `RiskGovernor` actúa como un **cortafuegos estricto de software** que ninguna alucinación o impulso de la IA puede saltarse:

* **Ratio Riesgo/Beneficio mínimo:** $R:R \ge 2.0$
* **Tamaño máximo por posición:** $\le 10.0\%$ del capital total
* **Riesgo máximo por operación:** $\le 1.5\%$ del capital total
* **Stop Loss:** Obligatorio en el 100% de las órdenes registradas

---

## 📄 Licencia

Desarrollado por **Alejandro Marqués**.
