"""
Planificador Inteligente de Tareas (Scheduler 24/7) para Sharky.
Ejecuta la cadencia óptima de vigilancia sin sobrecargar recursos ni gastar tokens innecesarios:
- Cada 1 hora (o configurable): Escaneo de precios, alertas de stop-loss y radar de oportunidades.
- Al cierre de mercado diario (22:00 CET / 16:00 EST): Informe de inteligencia, diario de reflexión y estado vital.
- Día 1 de cada mes (08:00): Propuesta maestra de rebalanceo de cartera.
"""

import time
import schedule
from datetime import datetime
from sharky.agent_loop import SharkyAgent
from sharky.vault_manager import VaultManager


class SharkyScheduler:
    def __init__(self, check_interval_minutes: int = 60):
        self.agent = SharkyAgent()
        self.check_interval_minutes = check_interval_minutes

    def run_hourly_surveillance(self):
        """Revisión ligera horaria: cotizaciones, stop-loss y radar de oportunidades."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] 🛰️ [24/7] Ejecutando escaneo horario de mercado y oportunidades...")
        try:
            # Comprobar precios y stop loss
            theses = self.agent.vault.list_active_theses()
            snapshots = self.agent.market.get_batch_snapshots([t.ticker for _, t in theses] + ["ASML", "TSM", "GOOGL"])
            
            # Escanear oportunidades
            existing_tickers = [t.ticker for _, t in theses]
            alerts = self.agent.detector.scan_for_opportunities(snapshots, existing_tickers)
            for a in alerts:
                self.agent.vault.write_opportunity_alert(a)

            # Verificar stop losses
            for _, t in theses:
                snap = snapshots.get(t.ticker)
                if snap and snap.precio_actual <= t.stop_loss and t.stop_loss > 0:
                    print(f"[{now_str}] ⚠️ ALERTA CRÍTICA: Stop Loss alcanzado en {t.ticker} (${snap.precio_actual:,.2f})")

            print(f"[{now_str}] ✅ Escaneo horario finalizado con éxito. {len(alerts)} alerta(s) activas.")
        except Exception as e:
            print(f"[{now_str}] ❌ Error en escaneo horario: {e}")

    def run_daily_close(self):
        """Cierre de mercado diario: reflexión completa, diario y actualización de salud."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] 📓 [24/7] Ejecutando informe de cierre diario de mercado...")
        try:
            res = self.agent.run_daily_cycle()
            print(f"[{now_str}] ✅ Diario de reflexión guardado: {res['diario_guardado']}")
            print(f"[{now_str}] 🫀 Salud actual: {res['salud']:.1f}% | Capital: ${res['capital_actual']:,.2f}")
        except Exception as e:
            print(f"[{now_str}] ❌ Error en ciclo diario: {e}")

    def run_monthly_rebalance(self):
        """Día 1 de cada mes: generar informe formal de rebalanceo de cartera."""
        now = datetime.now()
        if now.day == 1:
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now_str}] 📅 [24/7] ¡DÍA 1 DETECTADO! Generando Rebalanceo Mensual...")
            try:
                res = self.agent.generate_monthly_rebalance()
                print(f"[{now_str}] ✅ Informe maestro de rebalanceo generado: {res['archivo_informe']}")
            except Exception as e:
                print(f"[{now_str}] ❌ Error en rebalanceo mensual: {e}")

    def start(self):
        """Inicia el bucle continuo 24/7."""
        print(f"[Sharky 24/7] 🚀 Servicio iniciado. Vigilancia cada {self.check_interval_minutes} min.")
        print("[Sharky 24/7] Rutina diaria programada a las 22:00 CET. Rebalanceo el día 1 a las 08:00.")

        # Programar tareas periódicas
        schedule.every(self.check_interval_minutes).minutes.do(self.run_hourly_surveillance)
        schedule.every().day.at("22:00").do(self.run_daily_close)
        schedule.every().day.at("08:00").do(self.run_monthly_rebalance)

        # Ejecutar una primera pasada al arrancar
        self.run_hourly_surveillance()

        try:
            while True:
                schedule.run_pending()
                time.sleep(10)
        except KeyboardInterrupt:
            print("\n[Sharky 24/7] 🛑 Servicio detenido de forma segura.")
