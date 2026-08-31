---
tipo: plantilla
modulo: rebalanceo_mensual
---

# 📅 Propuesta de Rebalanceo Mensual: {{MES_ANO}}

> [!IMPORTANT]
> **Fecha de Emisión:** {{FECHA_HOY}}  
> **Estado Vital del Cerebro:** `{{ESTADO_VITAL}}` | **Salud:** `{{SALUD_PCT}}%` | **Capital Total:** `${{CAPITAL_TOTAL}}`  
> **Horizonte de Inversión:** Asignación estratégica mensual (revisión diaria de riesgos).

---

## 🌍 1. Diagnóstico Macroeconómico, Geopolítico y Sentimiento

### Régimen Macro Actual
{{REGIMEN_MACRO}}

### Dinámica Geopolítica y Flujos de Capital
{{DINAMICA_GEOPOLITICA}}

### Sentimiento de Mercado, Inercias y Sesgos Detectados
{{SENTIMIENTO_E_INERCIAS}}

---

## 🎯 2. Lista Maestra de Acciones: Día 1 (Compras y Ventas)

### 🔴 Órdenes de Venta / Reducción (Trim / Exit)
| Ticker | Acción | % Actual | % Objetivo | Capital a Liberar | Motivo / Tesis |
| :--- | :--- | :--- | :--- | :--- | :--- |
{{TABLA_VENTAS}}

### 🟢 Órdenes de Compra / Expansión (Buy / Add)
| Ticker | Acción | % Objetivo | Capital Asignado | Acciones Est. | Stop Loss | Target | Tesis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{{TABLA_COMPRAS}}

---

## 💼 3. Composición Objetivo de la Cartera

```
Reserva de Liquidez (Cash) : {{PCT_CASH}}% (${{CASH_USD}})
Renta Variable / Activos    : {{PCT_EQUITY}}% (${{EQUITY_USD}})
```

| Activo / Ticker | Sector | Ponderación (%) | Capital ($) | Rango Stop Loss | Convicción (1-10) |
| :--- | :--- | :--- | :--- | :--- | :--- |
{{TABLA_CARTERA_OBJETIVO}}

---

## 🛡️ 4. Validación del RiskGovernor

* [x] **Límite de Exposición por Activo:** Ningún activo supera el 10% del total.
* [x] **Reserva de Liquidez Mínima:** Al menos 15% en Cash para contingencias.
* [x] **Ratio R:R Promedio:** $\ge 2.0$ en todas las posiciones sugeridas.
* [x] **Plan de Contingencia Intrames:** Las posiciones solo se cerrarán antes de fin de mes si cruzan su `Stop Loss` innegociable.
