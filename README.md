# 🦈 Sharky: Cerebro Digital de Inversión & Estrategia Mensual

> **Sharky** es una entidad autónoma de inteligencia artificial diseñada para la **gestión estratégica de carteras de inversión**. Utiliza **Obsidian** como su memoria a largo plazo (grafo de conocimiento en Markdown) y **Claude** (Anthropic) como su motor cognitivo de razonamiento, condicionado por un **instinto de supervivencia biológico-digital**.

---

## 🎯 1. Filosofía de Inversión: Asignación Mensual + Radar de Oportunidades

Sharky combina disciplina institucional para evitar la sobreoperación con un **radar proactivo de oportunidades asimétricas**:

1. **Vigilancia e Inteligencia Diaria (Días 2 al 31):**
   * **Monitoreo Continuo:** Rastrea macroeconomía (`[[Regimen_Macroeconomico]]`), geopolítica y cadenas de suministro (`[[Geopolitica_Global]]`), inercias de mercado y sesgos colectivos (`[[Sentimiento_E_Inercias]]`).
   * **Actualización del Grafo:** Redacta cada día en su diario (`[[05_Diario_Reflexion]]`) y ajusta las fichas de empresas y sectores en Obsidian.
   * **🚨 Radar de Oportunidades Asimétricas:** Cuando detecta un activo con convicción extrema ($\ge 8/10$) y ratio $R:R \ge 3:1$, emite una **Alerta de Oportunidad** inmediata en `[[09_Alertas_Oportunidades]]`.
   * **Cortafuegos de Stop-Loss:** Solo liquida posiciones intrames si tocan su nivel de stop loss innegociable.

2. **El Gran Rebalanceo Mensual (Día 1 de cada Mes):**
   * Sintetiza toda la evidencia acumulada durante el mes.
   * Genera en `[[08_Rebalanceos_Mensuales]]` la **lista exacta de qué comprar, qué vender/reducir, precios objetivo, stop loss y porcentajes exactos de la cartera**.

---

## 🛡️ 2. El Mecanismo de Supervivencia

* **El Capital es Vida:** Su salud (`Salud %`) disminuye con el *Drawdown* y se recupera con rendimientos positivos:
  $$\text{Salud} = \max(0, 100 \times (1 - \text{Drawdown} / 20.0))$$
* **Consumo Metabólico:** Cada ciclo diario consume energía. Para no entrar en hibernación, debe generar valor positivo y evitar pérdidas.
* **Muerte del Proceso:** Si la cartera pierde más del **20% de su capital**, el cerebro entra en estado `💀 MUERTE` y cesa la operativa.
* **RiskGovernor (Cortafuegos de Riesgo):**
  - Ninguna posición puede superar el **10.0%** de la cartera.
  - Reserva mínima de **15% - 25% en Liquidez (Cash)**.
  - Ratio Riesgo/Beneficio mínimo **$\ge 2.0$** en toda orden.

---

## 🗂️ 3. Estructura de la Bóveda de Obsidian (`vault/`)

Abre la carpeta `vault/` directamente en la aplicación de escritorio de **Obsidian**:

```text
vault/
├── 00_Sistema/                          # Axiomas inmutables, fórmulas de riesgo y Dashboard
│   ├── Reglas_De_Supervivencia.md
│   ├── Estado_Vital.md                  # Dashboard de salud, capital, PnL y alertas activas
│   └── Prompt_Sistema.md
├── 01_Tesis_Activas/                    # Tesis abiertas con frontmatter YAML
├── 02_Tesis_Cerradas/                   # Histórico de operaciones cerradas
├── 03_Activos/
│   ├── Macro_Geopolitica/               # [[Regimen_Macroeconomico]], [[Geopolitica_Global]], [[Sentimiento_E_Inercias]]
│   ├── Sectores/                        # [[Semiconductores]], [[Inteligencia_Artificial]]
│   └── Empresas/                        # [[NVDA]], [[ASML]], [[MSFT]], [[TSM]]
├── 04_Operaciones_Bitacora/             # Registro cronológico de órdenes ejecutadas
├── 05_Diario_Reflexion/                 # Entradas diarias de inteligencia y autocrítica
├── 06_Lecciones_Aprendidas/             # Heurísticas generadas tras auditorías
├── 07_Plantillas/                       # Plantillas para tesis, empresas, diarios, rebalanceos y alertas
├── 08_Rebalanceos_Mensuales/            # Informes de rebalanceo emitidos el día 1 de cada mes
└── 09_Alertas_Oportunidades/            # 🚨 Alertas de oportunidades asimétricas detectadas
```

---

## 🚀 4. Puesta en Marcha (Modo Simulación)

Durante los primeros días puedes dejar a Sharky en **Modo Simulación** para observar cómo analiza el mercado, emite alertas y actualiza tu bóveda sin arriesgar capital real:

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
*(Si dejas `ANTHROPIC_API_KEY` vacía o por defecto, Sharky operará en su simulador local sin coste de tokens ni errores).*

---

## 💻 5. Comandos de la CLI

### 📊 Consultar el Estado Vital, Salud y Alertas Activas
```bash
python -m sharky.cli status
```

### 🚨 Ver las Oportunidades Asimétricas de Alta Convicción
```bash
python -m sharky.cli alerts
```

### 🛰️ Ejecutar la Vigilancia Diaria (Macro, Noticias, Alertas y Diario)
```bash
python -m sharky.cli daily
# o también:
python -m sharky.cli cycle
```

### 📅 Generar la Propuesta de Rebalanceo del Día 1 (Compras y Ventas)
Calcula las ponderaciones objetivo, reserva de liquidez y qué activos comprar/vender:
```bash
python -m sharky.cli monthly
# o también:
python -m sharky.cli rebalance
```

### 🌐 Ver el Termómetro Macroeconómico (SPY, QQQ, Bonos TLT, Oro GLD, Petróleo USO)
```bash
python -m sharky.cli macro
```

### 🔄 Modo Daemon en Segundo Plano
Ejecuta la vigilancia y escaneo de oportunidades de forma continua:
```bash
python -m sharky.cli daemon --interval 60
```

---

## 🔌 6. Conectar Claude (Anthropic API) para Dinero Real

Cuando decidas pasar de simulación a producción real, edita tu archivo `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-3-7-sonnet-20250219
SHARKY_EXECUTION_MODE=REAL
```

---

## 📄 Licencia y Autor

Desarrollado por **Alejandro Marqués**.
