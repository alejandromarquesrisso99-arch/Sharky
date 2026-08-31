---
tipo: alerta_oportunidad
id_alerta: "{{ID_ALERTA}}"
ticker: "{{TICKER}}"
empresa: "{{NOMBRE_EMPRESA}}"
fecha_deteccion: "{{FECHA_HOY}}"
conviccion: {{CONVICCION_1_A_10}}
precio_actual: {{PRECIO_ACTUAL}}
entrada_sugerida: {{ENTRADA_SUGERIDA}}
stop_loss: {{STOP_LOSS}}
target_precio: {{TARGET_PRECIO}}
ratio_rr: {{RATIO_RR}}
potencial_ganancia_pct: {{POTENCIAL_PCT}}
riesgo_maximo_pct: {{RIESGO_PCT}}
estado: ACTIVA
---

# 🚨 ALERTA DE ALTA CONVICCIÓN: {{NOMBRE_EMPRESA}} ({{TICKER}})

> [!WARNING]
> **OPORTUNIDAD ASIMÉTRICA DETECTADA**  
> **Fecha:** {{FECHA_HOY}} | **Convicción:** `{{CONVICCION_1_A_10}}/10` | **Ratio R:R:** `{{RATIO_RR}} : 1`  
> **Potencial Estimado:** `+{{POTENCIAL_PCT}}%` frente a un riesgo controlado de `-{{RIESGO_PCT}}%`.

---

## 💎 1. ¿Por qué es una Oportunidad Extraordinaria? (Tesis Rápida)

{{DESCRIPCION_OPORTUNIDAD}}

---

## ⚡ 2. Catalizadores Inmediatos

1. **[Catalizador Principal]:** {{CATALIZADOR_1}}
2. **[Catalizador Secundario]:** {{CATALIZADOR_2}}

---

## 🎯 3. Plan de Entrada y Protección

| Parámetro | Valor Sugerido | Justificación Técnica / Fundamental |
| :--- | :--- | :--- |
| **Precio Actual** | `${{PRECIO_ACTUAL}}` | Cotización de mercado al momento del radar |
| **Zona de Entrada Ideal** | `${{ENTRADA_SUGERIDA}}` | Punto óptimo de entrada con bajo riesgo |
| **Stop Loss Innegociable** | `${{STOP_LOSS}}` | Invalidación total de la hipótesis de inversión |
| **Target Objetivo (T1)** | `${{TARGET_PRECIO}}` | Primera zona de toma parcial/total de beneficios |
| **Ponderación Máxima Cartera** | `{{PCT_MAX_CARTERA}}%` | Respetando `[[Reglas_De_Supervivencia]]` |

---

## ⚠️ 4. Riesgos Críticos y Puntos Ciegos

* {{RIESGO_1}}
* {{RIESGO_2}}

---

## 📌 5. Acción Recomendada

* [ ] Evaluar inclusión en la cartera para el próximo **Rebalanceo Mensual** (`[[08_Rebalanceos_Mensuales]]`) o ejecución anticipada si el catalizador es de tiempo crítico.
