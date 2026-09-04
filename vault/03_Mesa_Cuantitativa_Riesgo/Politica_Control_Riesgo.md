---
tipo: gestion_riesgo
departamento: "Mesa Cuantitativa & Riesgo"
responsable: "Chief Risk Officer (CRO)"
version: 2.1
actualizado: '2026-09-02'
---

# 🛡️ Política Institucional de Control de Riesgos (CRO)

---

## 1. Límites Cuantitativos Obligatorios

* **Límite de Concentración Individual:** Máximo **10.0%** del valor neto de los activos (NAV).
* **Límite Sectorial:** Máximo **25.0%** en cualquier sector económico individual.
* **Reserva de Liquidez (Cash):** Mínimo **15.0%** en todo momento.
* **Stop Loss:** Innegociable y preestablecido antes de la apertura de cualquier posición.

---

## 2. Escalera de Contingencia ante Drawdowns

* **Drawdown < 3% (Estado Óptimo):** Operativa institucional al 100%.
* **Drawdown 3% - 8% (Estado Alerta):** Subida obligatoria de liquidez al 30%. Posiciones nuevas limitadas al 5%.
* **Drawdown 8% - 20% (Cuidados Intensivos):** Congelación total de nuevas inversiones. Sólo desinversión defensiva y auditoría.
* **Drawdown > 20% (Muerte / Liquidación):** Apagado de emergencia del sistema para proteger el patrimonio restante.

> [!CAUTION]
> **Corrección (v2.1):** esta escalera cortaba antes Cuidados Intensivos en el
> 15% y dejaba sin clasificar la franja 15%-20%, en contradicción con
> [[Reglas_De_Supervivencia]] (que ya corrigió el mismo fallo en su v2.1) y con
> `RiskGovernor.clasificar_estado`, que siempre trató 8%-20% como un único
> tramo. Esta nota estaba desincronizada del código: se alinea aquí.

---

## 🔗 Enlaces Bidireccionales del Grafo

* MOC del Departamento: [[03_Mesa_Cuantitativa_Riesgo]]
* Mandato & Gobernanza: [[Mandato_Institucional]], [[00_Comite_Direccion]]
* Axiomas & Fórmulas: [[Reglas_De_Supervivencia]], [[Metricas_Riesgo]], [[Estado_Vital]]
* Auditoría de Cartera: [[Auditoria_Cartera_Inicial_Real]]
* Rebalanceos & Alertas: [[08_Rebalanceos_Mensuales]], [[09_Alertas_Oportunidades]]
* Heurísticas: [[06_Lecciones_Aprendidas]], [[Heuristica_01_Preservacion_Capital]]
