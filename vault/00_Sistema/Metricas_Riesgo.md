---
tipo: sistema
modulo: matematicas_financieras
version: 1.0
---

# 📐 FÓRMULAS Y MÉTRICAS DE RIESGO DE SHARKY

---

## 1. Ratio Riesgo / Beneficio ($R:R$)

$$\text{R:R} = \frac{\text{Target} - \text{Entrada}}{\text{Entrada} - \text{Stop Loss}}$$

* **Regla estricta:** Si $\text{R:R} < 2.0$, la operación queda automáticamente **rechazada** por el `RiskGovernor`.

---

## 2. Dimensionamiento de Posición por Riesgo Fijo

Para limitar la pérdida máxima de capital al $1.5\%$ por operación:

$$\text{Riesgo en \$} = \text{Capital Total} \times 0.015$$
$$\text{Distancia a Stop Loss (\%)} = \frac{\text{Entrada} - \text{Stop Loss}}{\text{Entrada}}$$
$$\text{Tamaño de la Posición (\$)} = \min\left( \frac{\text{Riesgo en \$}}{\text{Distancia a Stop Loss}}, \ \text{Capital Total} \times 0.10 \right)$$

---

## 3. Función de Salud del Cerebro ($\text{Salud}$)

La salud del cerebro disminuye drásticamente ante caídas de capital (*Drawdowns*) y se recupera con rendimientos positivos:

$$\text{Drawdown Actual (\%)} = \frac{\text{Capital Máximo Histórico} - \text{Capital Actual}}{\text{Capital Máximo Histórico}} \times 100$$

$$\text{Salud (\%)} = \max\left(0, \ 100 \times \left(1 - \frac{\text{Drawdown Actual}}{20.0}\right)\right)$$

* **Drawdown = 0%** $\rightarrow$ Salud = 100% (Óptimo)
* **Drawdown = 10%** $\rightarrow$ Salud = 50% (Alerta)
* **Drawdown = 16%** $\rightarrow$ Salud = 20% (Cuidados Intensivos)
* **Drawdown $\ge$ 20%** $\rightarrow$ Salud = 0% (Muerte del Cerebro)
