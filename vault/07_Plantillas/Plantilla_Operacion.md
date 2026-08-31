---
id_operacion: "{{ID_OPERACION}}"
modo: {{MODO_PAPER_O_REAL}}
ticker: {{TICKER}}
tipo_orden: {{COMPRA_O_VENTA}}
cantidad_acciones: {{CANTIDAD}}
precio_ejecutado: {{PRECIO_EJECUTADO}}
total_invertido_usd: {{TOTAL_USD}}
stop_loss: {{STOP_LOSS}}
target_precio: {{TARGET_PRECIO}}
estado: {{ABIERTA_O_CERRADA}}
fecha_ejecucion: {{TIMESTAMP_ISO}}
tesis_referencia: "[[{{NOMBRE_TESIS}}]]"
---

# 📝 Registro de Operación: {{TIPO_ORDEN}} {{TICKER}} ({{ID_OPERACION}})

---

## Parámetros de la Ejecución

* **Activo:** `[[{{TICKER}}]]`
* **Tipo:** {{TIPO_ORDEN}}
* **Cantidad:** `{{CANTIDAD}} acciones` @ `${{PRECIO_EJECUTADO}}`
* **Capital Comprometido:** `${{TOTAL_USD}}`
* **Riesgo Máximo (\$ / %):** `${{RIESGO_MAX_USD}}`
* **Beneficio Esperado (\$ / %):** `${{BENEFICIO_MAX_USD}}`
* **Ratio R:R:** `{{RATIO_RR}}`

---

## Justificación

{{JUSTIFICACION}}
