---
ticker: {{TICKER}}
empresa: "{{NOMBRE_EMPRESA}}"
tipo: {{LARGO_O_CORTO}}
estado: Activa
precio_entrada: {{PRECIO_ENTRADA}}
# Divisa de precio_entrada, stop_loss y target_precio. Si falta, Sharky
# entiende EUR: un stop en dólares sin `divisa: USD` se compararía mal.
divisa: {{DIVISA_DE_LOS_NIVELES}}
stop_loss: {{STOP_LOSS}}
target_precio: {{TARGET_PRECIO}}
conviccion: {{CONVICCION_1_A_10}}
capital_asignado: {{CAPITAL_ASIGNADO}}
ratio_rr: {{RATIO_RR}}
fecha_apertura: {{FECHA_HOY}}
sectores: "[[{{SECTOR}}]]"
empresa_nota: "[[{{TICKER}}]]"
---

# 🎯 Tesis de Inversión: {{NOMBRE_EMPRESA}} ({{TICKER}})

---

## 💡 Racional de Inversión (Tesis)

[Describe detalladamente por qué este activo está infravalorado o por qué tiene una oportunidad de crecimiento asimétrico]

---

## 🚀 Catalizadores Principales

1. **[Catalizador 1]:** [Descripción]
2. **[Catalizador 2]:** [Descripción]

---

## ⚠️ Riesgos Monitoreados

* **[Riesgo 1]:** [Descripción]
* **[Riesgo 2]:** [Descripción]

---

## 🛑 Plan de Invalidación y Salida

* **Stop Loss Innegociable:** Si el precio cruza {{STOP_LOSS}} {{DIVISA_DE_LOS_NIVELES}}, se asume la pérdida y se cierra la posición.
* **Target Objetivo:** {{TARGET_PRECIO}} {{DIVISA_DE_LOS_NIVELES}} para toma de beneficios.
* **Criterio de Invalidez Cualitativo:** [Qué evento fundamental haría descartar la tesis inmediatamente]
