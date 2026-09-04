---
tipo: sistema
modulo: matematicas_financieras
version: 2.0
divisa_base: EUR
---

# 📐 FÓRMULAS Y MÉTRICAS DE RIESGO DE SHARKY

---

## 1. Ratio Riesgo / Beneficio ($R:R$)

$$\text{R:R} = \frac{\text{Target} - \text{Entrada}}{\text{Entrada} - \text{Stop Loss}}$$

* **Regla estricta:** Si $\text{R:R} < 2.0$, la operación queda automáticamente **rechazada** por el `RiskGovernor`.

---

## 2. Dimensionamiento de Posición por Riesgo Fijo

Para limitar la pérdida máxima de capital al $1.5\%$ del **NAV** por operación. Todos los importes van en **EUR**: los precios en divisa extranjera se convierten antes de aplicar la fórmula.

$$\text{Riesgo en €} = \text{Capital Total} \times 0.015$$
$$\text{Distancia a Stop Loss (\%)} = \frac{\text{Entrada} - \text{Stop Loss}}{\text{Entrada}}$$
$$\text{Tamaño de la Posición (€)} = \min\left( \frac{\text{Riesgo en €}}{\text{Distancia a Stop Loss}}, \ \text{Capital Total} \times 0.10 \right)$$

---

## 3. Función de Salud del Cerebro ($\text{Salud}$)

La salud mide el desgaste acumulado por caídas de capital (*drawdowns*) desde el máximo histórico y se recupera con rendimientos positivos:

$$\text{Drawdown Actual (\%)} = \frac{\text{NAV Máximo Histórico} - \text{NAV Actual}}{\text{NAV Máximo Histórico}} \times 100$$

> [!IMPORTANT]
> El denominador es el **máximo histórico del NAV** (*high-water mark*), nunca el
> capital inicial. Medirlo contra el capital inicial haría que una caída del 8%
> posterior a una subida del 30% se registrase como drawdown cero: es el error
> que hacía que el agente se declarase sano al 100% tras devolver un tercio de
> las ganancias.

$$\text{Salud (\%)} = \max\left(0, \ 100 \times \left(1 - \frac{\text{Drawdown Actual}}{20.0}\right)\right)$$

La `Salud %` es una métrica **continua** de desgaste, no un semáforo:

* **Drawdown = 0%** → Salud = 100%
* **Drawdown = 5%** → Salud = 75%
* **Drawdown = 10%** → Salud = 50%
* **Drawdown ≥ 20%** → Salud = 0%

> [!CAUTION]
> El **estado vital** (Óptimo / Alerta / Cuidados Intensivos / Muerte) NO se deriva
> de esta curva, sino de los cortes de drawdown fijados en
> [[Reglas_De_Supervivencia]] §3, que son la única fuente normativa. La `Salud %`
> sirve para leer la tendencia; el estado vital decide el régimen operativo.

---

## 🔗 Enlaces Bidireccionales del Grafo

* Sistema & Telemetría: [[00_Sistema]], [[Estado_Vital]], [[Reglas_De_Supervivencia]]
* Cartera y valoración: [[Cartera_Real]]
* Departamento de Riesgo (CRO): [[03_Mesa_Cuantitativa_Riesgo]], [[Politica_Control_Riesgo]]
* Gobernanza: [[00_Comite_Direccion]], [[Mandato_Institucional]]
* Rebalanceos & Alertas: [[08_Rebalanceos_Mensuales]], [[09_Alertas_Oportunidades]]
* Heurísticas: [[06_Lecciones_Aprendidas]], [[Heuristica_01_Preservacion_Capital]]
