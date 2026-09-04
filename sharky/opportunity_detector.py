"""
Detector de Oportunidades Asimétricas.

Combina dos ingredientes que se mantienen deliberadamente separados:

  * **Convicción cualitativa curada** (`UNIVERSO_CONVICCION`): la tesis de foso
    económico de cada candidato. Es juicio humano declarado como tal, no un
    hallazgo del algoritmo.
  * **Confirmación cuantitativa** derivada de precios reales: distancia al máximo
    de 52 semanas, posición frente a la media de 200 sesiones y volatilidad
    reciente, que fijan el stop y el objetivo.

Si no hay datos fiables, **no se emite alerta**. Y no se reemite una alerta que
ya está viva para el mismo activo: el detector consulta la bóveda antes.
"""

from typing import Callable, Dict, List, Optional
from datetime import datetime

from sharky.market_data import MarketDataProvider
from sharky.models import AlertStatus, MarketSnapshot, OpportunityAlert

# Ratio riesgo/beneficio mínimo para que una asimetría merezca una alerta.
RR_MINIMO = 2.8
CONVICCION_MINIMA = 8

# Un retroceso interesante: lo bastante profundo para importar, no tanto como
# para ser un cuchillo cayendo.
CAIDA_MINIMA_PCT = 6.0
CAIDA_MAXIMA_PCT = 35.0

# La tendencia de fondo debe seguir intacta.
MARGEN_SMA200_PCT = -8.0

# Stop derivado de volatilidad, acotado para que no sea absurdo en ninguna dirección.
STOP_MINIMO_PCT = 6.0
STOP_MAXIMO_PCT = 12.0


UNIVERSO_CONVICCION: Dict[str, dict] = {
    "ASML": {
        "empresa": "ASML Holding N.V.",
        "conviccion": 9,
        "max_cartera": 8.0,
        "tesis": (
            "Monopolio efectivo en litografía EUV: ningún nodo avanzado puede "
            "fabricarse sin sus máquinas, lo que le concede un poder de fijación de "
            "precios que sobrevive a los ciclos de semiconductores."
        ),
        "catalizadores": [
            "Posición única como proveedor exclusivo de litografía EUV y High-NA.",
            "Cartera de pedidos plurianual que da visibilidad de ingresos.",
            "CapEx de fundiciones sostenido por la demanda de cómputo para IA.",
        ],
        "riesgos": [
            "Controles de exportación hacia China que recortan mercado direccionable.",
            "Concentración extrema de clientes: tres fundiciones deciden su ciclo.",
            "Retrasos de construcción de fabs que desplazan entregas entre ejercicios.",
        ],
    },
    "TSM": {
        "empresa": "Taiwan Semiconductor Manufacturing Co.",
        "conviccion": 9,
        "max_cartera": 7.0,
        "tesis": (
            "Fundición dominante en nodos avanzados con utilización saturada. Su "
            "escala le permite subir precios de oblea sin perder clientes, porque no "
            "existe alternativa con capacidad equivalente."
        ),
        "catalizadores": [
            "Fabricante de facto de los aceleradores de IA líderes del mercado.",
            "Expansión de margen bruto vía precios de obleas avanzadas.",
            "Diversificación geográfica de fabs que reduce la prima de riesgo país.",
        ],
        "riesgos": [
            "Riesgo geopolítico del Estrecho de Taiwán, imposible de cubrir.",
            "Sobrecoste estructural de las fabs fuera de Taiwán.",
            "Ciclicidad de la demanda de electrónica de consumo.",
        ],
    },
    "GOOGL": {
        "empresa": "Alphabet Inc.",
        "conviccion": 8,
        "max_cartera": 8.0,
        "tesis": (
            "Genera caja libre masiva con un múltiplo inferior al de sus pares, y "
            "controla verticalmente su cómputo de IA (TPU) además de la distribución "
            "vía Android, Chrome y Workspace."
        ),
        "catalizadores": [
            "Crecimiento sostenido de Google Cloud con mejora de margen operativo.",
            "Integración de modelos propios en superficies con miles de millones de usuarios.",
            "Recompras agresivas sostenidas por el flujo de caja libre.",
        ],
        "riesgos": [
            "Litigios antimonopolio con remedios estructurales sobre la distribución.",
            "Canibalización del buscador por interfaces conversacionales.",
            "Intensidad de CapEx que presiona el flujo de caja libre a corto plazo.",
        ],
    },
    "NVDA": {
        "empresa": "NVIDIA Corporation",
        "conviccion": 9,
        "max_cartera": 7.0,
        "tesis": (
            "El foso no está en el silicio sino en CUDA y en la pila de red: el coste "
            "de migrar cargas de trabajo entrenadas sobre su ecosistema es el que "
            "sostiene los márgenes."
        ),
        "catalizadores": [
            "Ecosistema de software que fija a los clientes más allá del hardware.",
            "Ciclo de renovación de centros de datos hacia arquitecturas aceleradas.",
            "Integración vertical de red e interconexión.",
        ],
        "riesgos": [
            "Concentración de ingresos en un puñado de hiperescaladores.",
            "Silicio propietario de los propios clientes como sustituto parcial.",
            "Múltiplo exigente: descuenta años de ejecución impecable.",
        ],
    },
    # ------------------------------------------------------------------
    # Ampliación 2026-09: mismos ejes geopolíticos que ya sostienen la
    # cartera real (rearme, minerales críticos, ciclo nuclear, ciber-
    # seguridad como infraestructura crítica) más el cuello de botella de
    # electrificación de la IA, en nombres individuales nuevos -- no ya
    # cubiertos por los ETF que ya tienes (Defense_ETF, Rare_Earths, URNU,
    # Cybersecurity). Convicción cualitativa mía, igual que el resto de
    # este universo: la confirmación cuantitativa la sigue poniendo
    # `_evaluar` con datos reales, esto sólo decide qué se vigila.
    # ------------------------------------------------------------------
    "LDO": {
        "empresa": "Leonardo S.p.A.",
        "conviccion": 8,
        "max_cartera": 6.0,
        "tesis": (
            "Diversificación real dentro del rearme europeo: además de tierra, "
            "Leonardo cubre aeroespacial, electrónica de defensa, ciberseguridad y "
            "el consorcio de caza de sexta generación GCAP junto a Reino Unido y "
            "Japón -- una cartera de programas mucho menos concentrada en un solo "
            "sistema de armas que RHM o LMT."
        ),
        "catalizadores": [
            "Backlog plurianual récord impulsado por los compromisos de gasto de la OTAN.",
            "Participación en GCAP, el caza de sexta generación con Reino Unido y Japón.",
            "Ingresos repartidos entre defensa terrestre, aeroespacial, electrónica y ciberseguridad.",
        ],
        "riesgos": [
            "Ejecución de programas multinacionales complejos, con riesgo de retrasos y sobrecostes.",
            "El Estado italiano es accionista de referencia, con la interferencia política que implica.",
            "Valoración ya exigente tras el rally del sector de defensa desde 2022.",
        ],
    },
    "GEV": {
        "empresa": "GE Vernova Inc.",
        "conviccion": 8,
        "max_cartera": 6.0,
        "tesis": (
            "La demanda eléctrica de los centros de datos de IA choca con una red que "
            "lleva dos décadas sin invertir al ritmo necesario. GE Vernova fabrica las "
            "turbinas de gas, la generación y el equipamiento de red que ese cuello de "
            "botella obliga a construir, en un mercado con muy pocos proveedores capaces "
            "de escalar."
        ),
        "catalizadores": [
            "Cartera de pedidos de turbinas de gas con visibilidad hasta bien entrada la próxima década.",
            "Demanda eléctrica ligada directamente al capex en centros de datos de IA.",
            "Negocio de red y equipamiento eléctrico beneficiado por la electrificación de industria y transporte.",
        ],
        "riesgos": [
            "Ciclo de pedidos de bienes de equipo pesado, sensible a revisiones de capex de IA.",
            "Cuellos de botella propios en la cadena de suministro de turbinas y transformadores.",
            "Negocio eólico dentro del grupo, expuesto a políticas energéticas cambiantes.",
        ],
    },
    "VRT": {
        "empresa": "Vertiv Holdings Co.",
        "conviccion": 8,
        "max_cartera": 5.0,
        "tesis": (
            "Si GE Vernova resuelve el problema de generar la electricidad, Vertiv "
            "resuelve el de moverla y disiparla dentro del centro de datos: energía "
            "crítica y refrigeración líquida para racks de IA de alta densidad, donde "
            "la complejidad térmica ha dejado de ser un detalle de ingeniería para ser "
            "el límite físico del crecimiento del sector."
        ),
        "catalizadores": [
            "Transición de refrigeración por aire a líquida en los nuevos despliegues de IA.",
            "Ingresos recurrentes de servicio y mantenimiento sobre una base instalada creciente.",
            "Relaciones directas con los grandes operadores de centros de datos hiperescala.",
        ],
        "riesgos": [
            "Múltiplo de cotización que ya recoge buena parte del crecimiento esperado.",
            "Competencia creciente de proveedores especializados y de los propios hiperescaladores.",
            "Dependencia del ritmo de construcción de nuevos centros de datos.",
        ],
    },
    "CCJ": {
        "empresa": "Cameco Corporation",
        "conviccion": 8,
        "max_cartera": 6.0,
        "tesis": (
            "Complementa el ETF de uranio que ya tienes ([[URNU]]) con la productora "
            "occidental más grande y líquida del sector: mientras la política "
            "energética se reorienta hacia el reinicio y la construcción de reactores "
            "para sostener la demanda eléctrica de la IA, la oferta minera fuera de "
            "Rusia y Kazajistán sigue siendo escasa y concentrada."
        ),
        "catalizadores": [
            "Reinicio de reactores y extensiones de vida útil en EEUU y Europa.",
            "Participación en Westinghouse, con exposición adicional al ciclo de nuevos reactores.",
            "Oferta minera occidental limitada frente a una demanda que crece por primera vez en una generación.",
        ],
        "riesgos": [
            "Precio del uranio volátil y dependiente de decisiones de política energética ajenas a la empresa.",
            "Concentración geográfica de sus minas en Canadá y Kazajistán (vía participación).",
            "Ciclos de inversión en capacidad minera con largos plazos de maduración.",
        ],
    },
    "MP": {
        "empresa": "MP Materials Corp.",
        "conviccion": 8,
        "max_cartera": 5.0,
        "tesis": (
            "El único productor integrado de tierras raras de EEUU, con el "
            "Departamento de Defensa como accionista directo -- una señal explícita "
            "de que Washington trata la cadena de suministro de imanes de tierras "
            "raras como cuestión de seguridad nacional, no sólo de negocio. "
            "Complementa a [[Rare_Earths]] con exposición directa al productor, no al "
            "índice."
        ),
        "catalizadores": [
            "Participación de capital y contratos de compra garantizada del Departamento de Defensa de EEUU.",
            "Construcción de capacidad de imanes permanentes en EEUU, hoy casi monopolio de China.",
            "Restricciones de exportación de China que empujan a fabricantes occidentales a buscar alternativa.",
        ],
        "riesgos": [
            "Empresa pequeña y de márgenes históricamente volátiles, dependiente del precio de las tierras raras.",
            "Ejecución de la nueva capacidad de procesamiento e imanes, todavía en construcción.",
            "Gran parte de la tesis depende de que el apoyo gubernamental se mantenga en sucesivas administraciones.",
        ],
    },
    "CRWD": {
        "empresa": "CrowdStrike Holdings Inc.",
        "conviccion": 8,
        "max_cartera": 6.0,
        "tesis": (
            "La ciberseguridad ha dejado de ser un gasto de TI para convertirse en "
            "infraestructura crítica nacional: ataques a redes eléctricas, hospitales y "
            "cadenas de suministro por actores estatales han acelerado el gasto en "
            "detección y respuesta. CrowdStrike es la plataforma de referencia en ese "
            "segmento, con un efecto de red de datos de amenazas que se refuerza con "
            "cada cliente nuevo -- complementa a [[Cybersecurity]] con exposición al "
            "líder del segmento, no al índice."
        ),
        "catalizadores": [
            "Migración de presupuestos de seguridad hacia plataformas nativas de nube.",
            "Efecto de red: cada endpoint adicional mejora la detección para el resto de la base de clientes.",
            "Expansión de módulos (identidad, nube, SIEM) sobre la misma base de clientes.",
        ],
        "riesgos": [
            "Múltiplo de cotización elevado, muy sensible a cualquier desaceleración del crecimiento.",
            "Memoria reciente de un fallo operativo propio (la interrupción global de julio de 2024).",
            "Competencia de Microsoft, Palo Alto Networks y SentinelOne en el mismo segmento.",
        ],
    },
}


class OpportunityDetector:
    def __init__(self, market: Optional[MarketDataProvider] = None):
        self.market = market or MarketDataProvider()
        # Traza del último escaneo: por qué cada candidato pasó o no el filtro.
        # Un radar que no encuentra nada tiene que poder explicarse.
        self.ultimo_diagnostico: List[Dict[str, str]] = []

    def scan_for_opportunities(
        self,
        snapshots: Dict[str, MarketSnapshot],
        existing_positions: Optional[List[str]] = None,
        ya_alertado: Optional[Callable[[str], bool]] = None,
    ) -> List[OpportunityAlert]:
        """Escanea el universo curado buscando asimetrías confirmadas por datos.

        `ya_alertado(ticker)` permite al llamador vetar los activos que ya tienen
        una alerta activa en la bóveda, evitando duplicados como los que se
        acumularon con la versión anterior.
        """
        en_cartera = {t.upper().strip() for t in (existing_positions or [])}
        hoy = datetime.now().strftime("%Y-%m-%d")
        alertas: List[OpportunityAlert] = []
        self.ultimo_diagnostico = []

        def traza(ticker: str, veredicto: str, detalle: str) -> None:
            self.ultimo_diagnostico.append(
                {"ticker": ticker, "veredicto": veredicto, "detalle": detalle}
            )

        for ticker, perfil in UNIVERSO_CONVICCION.items():
            if perfil["conviccion"] < CONVICCION_MINIMA:
                traza(ticker, "DESCARTADO", f"convicción {perfil['conviccion']}/10 < {CONVICCION_MINIMA}")
                continue
            if ticker.upper() in en_cartera:
                traza(ticker, "OMITIDO", "ya forma parte de la cartera")
                continue
            if ya_alertado is not None and ya_alertado(ticker):
                traza(ticker, "OMITIDO", "ya tiene una alerta activa en la bóveda")
                continue

            snap = snapshots.get(ticker) or self.market.get_snapshot(ticker)
            # Sin cotización fiable no se emite señal: un precio de referencia no
            # justifica una recomendación de compra.
            if snap is None or snap.precio_actual <= 0:
                traza(ticker, "SIN DATOS", "no hay cotización disponible")
                continue
            if not snap.es_fiable:
                traza(ticker, "SIN DATOS", f"cotización de procedencia {snap.fuente.value}")
                continue

            tecnicos = self.market.get_technicals(ticker)
            if not tecnicos:
                traza(ticker, "SIN DATOS", "histórico insuficiente para medir la estructura anual")
                continue

            alerta, motivo = self._evaluar(ticker, perfil, snap, tecnicos, hoy)
            if alerta is not None:
                alertas.append(alerta)
                traza(ticker, "ALERTA", motivo)
            else:
                traza(ticker, "NO CUALIFICA", motivo)

        alertas.sort(key=lambda a: (-a.conviccion, -a.ratio_rr))
        return alertas

    # ------------------------------------------------------------------
    def _evaluar(
        self,
        ticker: str,
        perfil: dict,
        snap: MarketSnapshot,
        tecnicos: Dict[str, float],
        hoy: str,
    ) -> tuple:
        """Devuelve `(alerta | None, motivo)`. El motivo se traza siempre."""
        precio = snap.precio_actual
        caida = tecnicos["caida_desde_max_pct"]
        sobre_sma = tecnicos["sobre_sma200_pct"]

        # Filtro 1: retroceso significativo pero no estructural.
        if caida < CAIDA_MINIMA_PCT:
            return None, (
                f"sólo un {caida:.2f}% por debajo del máximo anual "
                f"(se exige ≥ {CAIDA_MINIMA_PCT:.0f}%): no hay descuento"
            )
        if caida > CAIDA_MAXIMA_PCT:
            return None, (
                f"un {caida:.2f}% por debajo del máximo anual "
                f"(máximo {CAIDA_MAXIMA_PCT:.0f}%): posible deterioro estructural"
            )
        # Filtro 2: tendencia de fondo intacta.
        if sobre_sma < MARGEN_SMA200_PCT:
            return None, (
                f"cotiza un {sobre_sma:.2f}% respecto a su media de 200 sesiones "
                f"(mínimo {MARGEN_SMA200_PCT:.0f}%): tendencia rota"
            )

        # Stop dimensionado por volatilidad realizada (2 desviaciones diarias
        # llevadas a ~10 sesiones), acotado a un rango razonable.
        stop_pct = tecnicos["vol_diaria"] * 100.0 * 2.0 * (10 ** 0.5)
        stop_pct = max(STOP_MINIMO_PCT, min(STOP_MAXIMO_PCT, stop_pct))
        stop_loss = round(precio * (1.0 - stop_pct / 100.0), 2)

        # Objetivo: recuperar el máximo de 52 semanas. Es una hipótesis
        # verificable, no un múltiplo inventado.
        target = round(tecnicos["max_52s"], 2)
        if target <= precio:
            return None, "el máximo anual no está por encima del precio actual"

        riesgo = precio - stop_loss
        beneficio = target - precio
        if riesgo <= 0:
            return None, "el stop calculado no queda por debajo del precio"

        ratio_rr = round(beneficio / riesgo, 2)
        if ratio_rr < RR_MINIMO:
            return None, (
                f"asimetría insuficiente: R:R {ratio_rr:.2f}:1 frente al mínimo de "
                f"{RR_MINIMO:.1f}:1 (stop {stop_pct:.1f}%, recorrido al máximo anual "
                f"{beneficio / precio * 100:.1f}%)"
            )

        potencial_pct = round(beneficio / precio * 100.0, 2)
        riesgo_pct = round(riesgo / precio * 100.0, 2)

        descripcion = (
            f"{perfil['tesis']}\n\n"
            f"**Confirmación cuantitativa:** cotiza un `{caida:.2f}%` por debajo de su "
            f"máximo de 52 semanas (`{tecnicos['max_52s']:,.2f} {snap.divisa}`) mientras se "
            f"mantiene un `{sobre_sma:+.2f}%` respecto a su media de 200 sesiones, es decir, "
            f"un retroceso dentro de una tendencia intacta. La volatilidad diaria reciente "
            f"(`{tecnicos['vol_diaria'] * 100:.2f}%`) sitúa el stop técnico a un "
            f"`{stop_pct:.1f}%`, lo que produce una asimetría de `{ratio_rr:.2f}:1` "
            f"tomando como objetivo la recuperación del máximo anual."
        )

        alerta = OpportunityAlert(
            id_alerta=f"ALT-{datetime.now().strftime('%Y%m%d')}-{ticker}",
            ticker=ticker,
            empresa=perfil["empresa"],
            fecha_deteccion=hoy,
            conviccion=perfil["conviccion"],
            precio_actual=round(precio, 2),
            divisa=snap.divisa,
            entrada_sugerida=round(precio, 2),
            stop_loss=stop_loss,
            target_precio=target,
            ratio_rr=ratio_rr,
            potencial_ganancia_pct=potencial_pct,
            riesgo_maximo_pct=riesgo_pct,
            descripcion_oportunidad=descripcion,
            catalizadores=list(perfil["catalizadores"]),
            riesgos=list(perfil["riesgos"]),
            pct_max_cartera=perfil["max_cartera"],
            estado=AlertStatus.ACTIVA,
            fuente_precio=snap.fuente,
        )
        return alerta, (
            f"asimetría confirmada: R:R {ratio_rr:.2f}:1 (caída {caida:.2f}% del máximo, "
            f"stop {stop_pct:.1f}%, potencial +{potencial_pct:.1f}%)"
        )
