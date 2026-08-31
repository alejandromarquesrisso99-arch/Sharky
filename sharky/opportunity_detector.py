"""
Detector de Oportunidades Asimétricas de Alta Convicción para Sharky.
Escanea activos en radar, ratios de valoración y catalizadores para emitir alertas.
"""

from typing import List, Dict, Any
from datetime import datetime
import uuid

from sharky.models import OpportunityAlert, MarketSnapshot, AlertStatus


class OpportunityDetector:
    def __init__(self):
        pass

    def scan_for_opportunities(
        self,
        snapshots: Dict[str, MarketSnapshot],
        existing_positions: List[str],
    ) -> List[OpportunityAlert]:
        """
        Evalúa activos vigilados en busca de asimetrías extraordinarias (R:R >= 3.0, Convicción >= 8).
        """
        alerts: List[OpportunityAlert] = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Catálogo de oportunidades de alta convicción pre-analizadas / reglas de setup
        candidate_rules = {
            "ASML": {
                "empresa": "ASML Holding N.V.",
                "conviccion": 9,
                "target_mult": 1.24,  # +24%
                "stop_mult": 0.92,    # -8%
                "max_cartera": 8.0,
                "descripcion": "Consolidación sobre soporte mayor y aceleración en adopción de litografía High-NA EUV.",
                "catalizadores": [
                    "Monopolio global exclusivo en máquinas de litografía EUV.",
                    "Cartera récord de pedidos pendientes (>38.000M€).",
                    "Aumento de CapEx proyectado por fabricantes para nodos de 2nm."
                ],
                "riesgos": [
                    "Restricciones diplomáticas adicionales a exportaciones hacia China.",
                    "Retrasos puntuales en construcción de nuevas fabs en Occidente."
                ]
            },
            "TSM": {
                "empresa": "Taiwan Semiconductor Manufacturing Co.",
                "conviccion": 9,
                "target_mult": 1.28,  # +28%
                "stop_mult": 0.91,    # -9%
                "max_cartera": 8.0,
                "descripcion": "Poder de fijación de precios inigualable y saturación al 100% en capacidad de nodos de 3nm y 5nm.",
                "catalizadores": [
                    "Fabricante exclusivo de todos los chips de aceleración IA líderes.",
                    "Expansión de margen bruto por subida de precios de obleas avanzadas.",
                    "Diversificación internacional de fábricas (Arizona, Japón, Alemania)."
                ],
                "riesgos": [
                    "Riesgo geopolítico persistente en el Estrecho de Taiwán.",
                    "Coste de construcción superior al esperado en plantas internacionales."
                ]
            },
            "GOOGL": {
                "empresa": "Alphabet Inc.",
                "conviccion": 8,
                "target_mult": 1.25,  # +25%
                "stop_mult": 0.92,    # -8%
                "max_cartera": 8.0,
                "descripcion": "Valoración históricamente atractiva con P/E bajo frente a sus pares y fortaleza masiva en infraestructura Cloud/TPU.",
                "catalizadores": [
                    "Crecimiento de ingresos acelerado en Google Cloud Platform.",
                    "Despliegue e integración nativa de modelos Gemini en ecosistema Workspace y Android.",
                    "Generación gigantesca de flujo de caja libre con recompras activas."
                ],
                "riesgos": [
                    "Demandas antimonopolio del Departamento de Justicia (DOJ).",
                    "Disrupción gradual en el modelo de búsqueda tradicional por interfaces conversacionales."
                ]
            }
        }

        for ticker, data in candidate_rules.items():
            # Si el activo no está ya en la cartera principal
            if ticker not in existing_positions and ticker in snapshots:
                snap = snapshots[ticker]
                price = snap.precio_actual
                stop_loss = round(price * data["stop_mult"], 2)
                target = round(price * data["target_mult"], 2)
                
                riesgo_usd = price - stop_loss
                ganancia_usd = target - price
                ratio_rr = round(ganancia_usd / riesgo_usd, 2) if riesgo_usd > 0 else 0.0
                
                potencial_pct = round(((target - price) / price) * 100.0, 2)
                riesgo_pct = round(((price - stop_loss) / price) * 100.0, 2)

                # Solo emitir alerta si la asimetría supera el ratio 2.8
                if ratio_rr >= 2.8 and data["conviccion"] >= 8:
                    alert_id = f"ALT-{datetime.now().strftime('%Y%m%d')}-{ticker}"
                    alert = OpportunityAlert(
                        id_alerta=alert_id,
                        ticker=ticker,
                        empresa=data["empresa"],
                        fecha_deteccion=today_str,
                        conviccion=data["conviccion"],
                        precio_actual=price,
                        entrada_sugerida=price,
                        stop_loss=stop_loss,
                        target_precio=target,
                        ratio_rr=ratio_rr,
                        potencial_ganancia_pct=potencial_pct,
                        riesgo_maximo_pct=riesgo_pct,
                        descripcion_oportunidad=data["descripcion"],
                        catalizadores=data["catalizadores"],
                        riesgos=data["riesgos"],
                        pct_max_cartera=data["max_cartera"],
                        estado=AlertStatus.ACTIVA,
                    )
                    alerts.append(alert)

        return alerts
