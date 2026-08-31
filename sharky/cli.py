"""
Interfaz de Línea de Comandos (CLI) de Sharky.
Permite visualizar el estado vital, ejecutar la vigilancia diaria y generar la lista de compras/ventas del Día 1.
"""

import argparse
import sys
import time
from datetime import datetime

from sharky.agent_loop import SharkyAgent
from sharky.config import DEFAULT_WATCHLIST, VAULT_PATH, ANTHROPIC_API_KEY
from sharky.market_data import CORE_WATCHLIST, MACRO_TICKERS
from sharky.models import VitalState


def print_banner():
    print(r"""
  ███████╗██╗  ██╗ █████╗ ██████╗ ██╗  ██╗██╗   ██╗
  ██╔════╝██║  ██║██╔══██╗██╔══██╗██║ ██╔╝╚██╗ ██╔╝
  ███████╗███████║███████║██████╔╝█████╔╝  ╚████╔╝ 
  ╚════██║██╔══██║██╔══██║██╔══██╗██╔═██╗   ╚██╔╝  
  ███████║██║  ██║██║  ██║██║  ██║██║  ██╗   ██║   
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
    Cerebro Digital de Inversión & Supervivencia
    Estrategia de Asignación Mensual & Vigilancia Diaria
    """)


def cmd_status(agent: SharkyAgent):
    health = agent.get_status_summary()
    print_banner()
    print("=" * 65)
    print(f"  Bóveda de Obsidian : {VAULT_PATH}")
    has_key = bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "TU_ANTHROPIC_API_KEY_AQUI")
    print(f"  Motor de IA        : {'Claude (API Conectada)' if has_key else 'Modo Simulación (Sin API Key)'}")
    print("-" * 65)
    print(f"  Estado Vital       : {health.estado_vital.value}")
    print(f"  Salud Digital      : {health.salud_porcentaje:.1f}%")
    print(f"  Energía Metabólica : {health.energia_actual:.1f} / 100.0")
    print(f"  Capital Total      : ${health.capital_actual:,.2f} USD")
    print(f"  PnL Acumulado      : {'+' if health.pnl_total_usd >= 0 else ''}${health.pnl_total_usd:,.2f} ({'+' if health.pnl_total_pct >= 0 else ''}{health.pnl_total_pct:.2f}%)")
    print(f"  Drawdown Máximo    : {health.drawdown_maximo_pct:.2f}%")
    print("=" * 65)


def cmd_cycle(agent: SharkyAgent):
    print("\n[Sharky] 🛰️ Iniciando vigilancia diaria de mercado, macro y geopolítica...")
    res = agent.run_daily_cycle()
    print("[Sharky] ✅ Sesión de vigilancia completada.")
    print(f"  - Estado Vital      : {res['estado_vital']}")
    print(f"  - Salud             : {res['salud']:.1f}%")
    print(f"  - Capital           : ${res['capital_actual']:,.2f}")
    print(f"  - PnL               : ${res['pnl_total_usd']:+,.2f}")
    print(f"  - Tesis en Cartera  : {res['tesis_activas']}")
    print(f"  - Diario Guardado   : {res['diario_guardado']}")
    if res.get("rebalanceo_generado"):
        print(f"  - 📅 ¡REBALANCEO DÍA 1 GENERADO!: {res['rebalanceo_generado']}")
    if res.get("alertas_stop_loss"):
        for a in res["alertas_stop_loss"]:
            print(f"  {a}")
    print()


def cmd_monthly(agent: SharkyAgent):
    print("\n[Sharky] 📅 Generando Propuesta Maestra de Rebalanceo Mensual (Día 1)...")
    res = agent.generate_monthly_rebalance()
    print(f"[Sharky] ✅ Propuesta para {res['mes_ano']} generada con éxito.")
    print(f"  - Archivo Obsidian : {res['archivo_informe']}")
    print(f"  - Capital Total    : ${res['capital_total']:,.2f}")
    print(f"  - Reserva de Cash  : {res['reserva_cash_pct']:.1f}% (${res['reserva_cash_usd']:,.2f})")
    print("\n--- 📋 LISTA DE ACCIONES RECOMENDADAS PARA EL DÍA 1 ---")
    print(f"{'TICKER':<8} | {'ACCIÓN':<12} | {'PESO %':<8} | {'CAPITAL ($)':<12} | {'STOP LOSS':<10} | {'TARGET':<10}")
    print("-" * 72)
    for p in res["propuestas"]:
        print(f"{p['ticker']:<8} | {p['accion']:<12} | {p['peso_objetivo_pct']:<7.1f}% | ${p['capital_asignado_usd']:<11,.2f} | ${p['stop_loss_sugerido']:<9,.2f} | ${p['target_sugerido']:<9,.2f}")
    print("-" * 72)
    print("👉 Revisa el informe completo detallado en Obsidian: vault/08_Rebalanceos_Mensuales/\n")


def cmd_macro(agent: SharkyAgent):
    print("\n[Sharky] 🌐 Obteniendo termómetro macroeconómico global...")
    macros = agent.market.get_macro_overview()
    print("-" * 65)
    print(f"{'PROXIE / ETF':<12} | {'PRECIO':<12} | {'CAMBIO (%)':<12} | {'DESCRIPCIÓN':<20}")
    print("-" * 65)
    descriptions = {
        "SPY": "S&P 500 (Renta Variable USA)",
        "QQQ": "Nasdaq 100 (Tecnología / Crecimiento)",
        "TLT": "Bonos 20Y+ (Tipos de Interés)",
        "GLD": "Oro Físico (Cobertura / Refugio)",
        "USO": "Petróleo WTI (Energía / Inflación)",
    }
    for t, s in macros.items():
        sign = "+" if s.cambio_diario_pct >= 0 else ""
        desc = descriptions.get(t, "")
        print(f"{s.ticker:<12} | ${s.precio_actual:<11,.2f} | {sign}{s.cambio_diario_pct:<11.2f}% | {desc:<20}")
    print("-" * 65)


def cmd_daemon(agent: SharkyAgent, interval_minutes: int = 60):
    print_banner()
    print(f"[Sharky] 🔄 Modo Daemon de vigilancia continua iniciado ({interval_minutes} min).")
    print("[Sharky] Presiona Ctrl+C para pausar.\n")
    try:
        while True:
            cmd_cycle(agent)
            print(f"[Sharky] Próxima comprobación en {interval_minutes} minutos...\n")
            time.sleep(interval_minutes * 60)
    except KeyboardInterrupt:
        print("\n[Sharky] 🛑 Daemon detenido. El estado del cerebro se mantiene guardado en Obsidian.")


def main():
    parser = argparse.ArgumentParser(
        description="Sharky: Cerebro de Inversión y Rebalanceo Mensual con Obsidian y Claude"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # Comando status
    subparsers.add_parser("status", help="Muestra el estado vital actual y métricas de salud")

    # Comando cycle / daily
    subparsers.add_parser("cycle", help="Ejecuta la vigilancia diaria de mercado y macro")
    subparsers.add_parser("daily", help="Alias para cycle")

    # Comando monthly / rebalance
    subparsers.add_parser("monthly", help="Genera la propuesta de rebalanceo del Día 1 (qué comprar y qué vender)")
    subparsers.add_parser("rebalance", help="Alias para monthly")

    # Comando macro
    subparsers.add_parser("macro", help="Muestra los indicadores macroeconómicos clave (SPY, QQQ, TLT, GLD, USO)")

    # Comando daemon
    daemon_parser = subparsers.add_parser("daemon", help="Ejecuta el agente de forma continua en segundo plano")
    daemon_parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Intervalo entre ciclos en minutos (por defecto: 60)",
    )

    args = parser.parse_args()
    agent = SharkyAgent()

    if args.command == "status" or args.command is None:
        cmd_status(agent)
    elif args.command in ("cycle", "daily"):
        cmd_cycle(agent)
    elif args.command in ("monthly", "rebalance"):
        cmd_monthly(agent)
    elif args.command == "macro":
        cmd_macro(agent)
    elif args.command == "daemon":
        cmd_daemon(agent, interval_minutes=args.interval)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
