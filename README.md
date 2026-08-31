# 🦈 Sharky Capital Management: Firma de Inversión Autónoma

> **Sharky Capital Management** es un fondo institucional / Family Office digital autónomo dedicado a la gestión estratégica de carteras. Integra una **estructura departamental completa** (Macroeconomía, Análisis Fundamental, Gestión de Riesgo y Psicología de Mercado) conectada a **Obsidian** como memoria de largo plazo y a **Claude** como **Chief Investment Officer (CIO)**.

---

## 🏛️ 1. Estructura Departamental de la Firma

Sharky no es un simple bot de trading: opera como una **empresa entera de gestión de activos** con departamentos especializados:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 👔 COMITÉ DE DIRECCIÓN / CIO (Sharky)                       │
│     - Deliberación estratégica y síntesis ejecutiva                         │
│     - Aprobación final del Rebalanceo del Día 1                             │
│     - Salvaguarda de la supervivencia de la firma                           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
       ┌───────────────────────────────┼───────────────────────────────┐
       ▼                               ▼                               ▼
┌─────────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
│ 🌐 DEPARTAMENTO MACRO   │ │ 🔬 ANÁLISIS FUNDAMENTAL │ │ 🛡️ MESA DE RIESGO (CRO) │
│ - Tipos de interés (TLT)│ │ - Fosos económicos (Moat)│ │ - Control de Drawdowns  │
│ - Oro y divisas (GLD)   │ │ - ROIC > 15%, Caja Libre │ │ - Stop Loss obligatorio │
│ - Geopolítica y Cadenas │ │ - Monopolios y pricing   │ │ - Límite máx. 10% activo│
└─────────────────────────┘ └─────────────────────────┘ └─────────────────────────┘
                                       │
                                       ▼
                            ┌─────────────────────────┐
                            │ 🧠 PSICOLOGÍA & FLUJOS  │
                            │ - Detección de FOMO     │
                            │ - Amplitud de mercado   │
                            │ - Control de sesgos     │
                            └─────────────────────────┘
```

---

## 🗂️ 2. Estructura de la Bóveda Institucional (`vault/`)

Abre la carpeta `vault/` directamente en **Obsidian** para explorar el cerebro corporativo:

```text
vault/
├── 00_Comite_Direccion/                 # Mandato institucional (IPS), Filosofía y Dashboard CIO
│   ├── Mandato_Institucional.md
│   ├── Reglas_De_Supervivencia.md
│   └── Estado_Vital.md
├── 01_Departamento_Macro/               # Informes macro globales, geopolítica y tipos de interés
│   └── Monitor_Macro_Global.md
├── 02_Analisis_Fundamental/             # Metodología de fosos, fichas de empresas y sectores
│   └── Metodologia_Fosos.md
├── 03_Mesa_Cuantitativa_Riesgo/         # Políticas de riesgo del CRO y fórmulas de supervivencia
│   └── Politica_Control_Riesgo.md
├── 04_Sentimiento_Y_Flujos/             # Psicología colectiva, narrativas y control de sesgos
│   └── Psicologia_Y_Narrativas.md
├── 05_Diario_Reflexion/                 # Actas diarias de inteligencia y autocrítica
├── 06_Lecciones_Aprendidas/             # Heurísticas generadas tras auditorías internas
├── 07_Plantillas/                       # Plantillas para deep dives, tesis y rebalanceos
├── 08_Rebalanceos_Mensuales/            # Propuestas maestras de compra/venta del Día 1
└── 09_Alertas_Oportunidades/            # 🚨 Pitches de oportunidades asimétricas detectadas
```

---

## 💻 3. Comandos de la CLI

```bash
# Ver el estado institucional de la firma y salud del capital
python -m sharky.cli status

# Convocar una Sesión Plenaria del Comité de Inversión (con los 4 departamentos y CIO)
python -m sharky.cli committee

# Ver las oportunidades asimétricas de alta convicción activas
python -m sharky.cli alerts

# Ejecutar la vigilancia diaria de mercado e inteligencia
python -m sharky.cli daily

# Generar la propuesta maestra de rebalanceo del Día 1
python -m sharky.cli monthly

# Ver el termómetro macroeconómico global (SPY, QQQ, TLT, GLD, USO)
python -m sharky.cli macro

# Iniciar el servicio continuo 24/7 en Raspberry Pi / Servidor
python -m sharky.cli service --interval 60
```

---

## 🍓 4. Despliegue 24/7 en Raspberry Pi / Docker

```bash
# En Raspberry Pi / Linux (Instalador automático con systemd):
chmod +x scripts/deploy_raspberry.sh
./scripts/deploy_raspberry.sh

# Con Docker Compose:
docker compose up -d
```

---

## 🔌 5. Conectar Claude (Anthropic API)

Edita el archivo `.env` para activar a Claude en el rol de **CIO**:
```env
ANTHROPIC_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-3-7-sonnet-20250219
SHARKY_EXECUTION_MODE=REAL
```

---

## 📄 Licencia y Autor

Desarrollado por **Alejandro Marqués**.
