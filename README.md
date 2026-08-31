# 🦈 Sharky: Cerebro Digital de Inversión & Estrategia Mensual

> **Sharky** es una entidad autónoma de inteligencia artificial diseñada para la **gestión estratégica de carteras de inversión**. Utiliza **Obsidian** como su memoria a largo plazo (grafo de conocimiento en Markdown) y **Claude** (Anthropic) como su motor cognitivo de razonamiento, condicionado por un **instinto de supervivencia biológico-digital**.

---

## 🎯 1. Filosofía de Inversión: Asignación Mensual + Radar de Oportunidades

Sharky combina disciplina institucional para evitar la sobreoperación con un **radar proactivo de oportunidades asimétricas**:

1. **Vigilancia e Inteligencia Diaria (Días 2 al 31):**
   * **Monitoreo Continuo (24/7):** Rastrea macroeconomía (`[[Regimen_Macroeconomico]]`), geopolítica y cadenas de suministro (`[[Geopolitica_Global]]`), inercias de mercado y sesgos colectivos (`[[Sentimiento_E_Inercias]]`).
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

## 🍓 4. Despliegue 24/7 en Raspberry Pi / Servidor / Docker

Sharky consume menos de **100 MB de memoria RAM** y prácticamente **0% de CPU en reposo**, por lo que es perfecto para funcionar siempre encendido en una **Raspberry Pi (3, 4 o 5)**, Mini PC o servidor local.

### Cadencia Inteligente del Planificador 24/7 (`SharkyScheduler`):
* **Cada 60 minutos:** Escaneo silencioso de cotizaciones, verificación de Stop Loss de emergencia y radar de oportunidades.
* **Cada día a las 22:00 CET:** Cierre diario de mercado, síntesis de noticias, reflexión con Claude y actualización del diario.
* **Día 1 de cada mes a las 08:00:** Generación automática de la propuesta maestra de compras y ventas.

### Opción A: Instalación Automática en Raspberry Pi / Linux
Clona el repositorio en tu Raspberry Pi y ejecuta el script de instalación:
```bash
git clone https://github.com/alejandromarquesrisso99-arch/Sharky.git
cd Sharky
chmod +x scripts/deploy_raspberry.sh
./scripts/deploy_raspberry.sh
```
*Sharky se registrará como un servicio de `systemd` que arrancará automáticamente cada vez que enciendas la Raspberry Pi.*

* **Ver estado:** `sudo systemctl status sharky`
* **Ver logs en vivo:** `journalctl -u sharky -f`

### Opción B: Despliegue con Docker Compose
```bash
docker compose up -d
```

### Opción C: Ejecutar como Servicio en Windows / Mac / Linux
```bash
python -m sharky.cli service --interval 60
```

---

## 📱 5. Cómo ver las notas en tu Móvil u Ordenador en tiempo real

Como la Raspberry Pi o servidor actualiza los archivos Markdown en la carpeta `vault/`, puedes sincronizarla con tus dispositivos:
1. **Obsidian Sync:** La forma oficial y más sencilla.
2. **Git Sync (Plugin de Obsidian):** Sincronización automática gratuita con tu repositorio de GitHub.
3. **Syncthing:** Sincronización P2P gratuita y continua entre la Raspberry Pi, tu PC y tu teléfono móvil.

---

## 💻 6. Comandos de la CLI

```bash
# Ver estado vital, salud y alertas activas
python -m sharky.cli status

# Ver las oportunidades asimétricas de alta convicción detectadas
python -m sharky.cli alerts

# Ejecutar manualmente la vigilancia diaria
python -m sharky.cli daily

# Generar manualmente la propuesta de rebalanceo del Día 1
python -m sharky.cli monthly

# Ver el termómetro macroeconómico (SPY, QQQ, TLT, GLD, USO)
python -m sharky.cli macro

# Iniciar el servicio continuo 24/7
python -m sharky.cli service --interval 60
```

---

## 🔌 7. Conectar Claude (Anthropic API)

Por defecto funciona en **Modo Simulación**. Para activar el razonamiento en vivo con Claude, edita tu archivo `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-3-7-sonnet-20250219
SHARKY_EXECUTION_MODE=REAL
```

---

## 📄 Licencia y Autor

Desarrollado por **Alejandro Marqués**.
