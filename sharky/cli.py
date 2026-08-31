"""
Interfaz de Línea de Comandos (CLI) de Sharky.
Permite visualizar el estado vital, ejecutar ciclos y sincronizar con Obsidian.
"""

import argparse
import sys
import time
from datetime import datetime

from sharky.agent_loop import SharkyAgent
from sharky.config import DEFAULT_WATCHLIST, VAULT_PATH, ANTHROPIC_API_KEY
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
    """)


def cmd_status(agent: SharkyAgent):
    health = agent.get_status_summary()
    print_banner()
    print("=" * 60)
    print(f"  Bóveda de Obsidian : {VAULT_PATH}")
    has_key = bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "TU_ANTHROPIC_API_KEY_AQUI")
    print(f"  Motor de IA        : {'Claude (API Conectada)' if has_key else 'Modo Simulación (Sin API Key)'}")
    print("-" * 60)
    print(f"  Estado Vital       : {health.estado_vital.value}")
    print(f"  Salud Digital      : {health.salud_porcentaje:.1f}%")
    print(f"  Energía Metabólica : {health.energia_actual:.1f} / 100.0")
    print(f"  Capital Actual     : ${health.capital_actual:,.2f} USD")
    print(f"  PnL Acumulado      : {'+' if health.pnl_total_usd >= 0 else ''}${health.pnl_total_usd:,.2f} ({'+' if health.pnl_total_pct >= 0 else ''}{health.pnl_total_pct:.2f}%)")
    print(f"  Drawdown Máximo    : {health.drawdown_maximo_pct:.2f}%")
    print("=" * 60)


def cmd_cycle(agent: SharkyAgent):
    print("\n[Sharky] 🚀 Iniciando ciclo de mercado y supervivencia...")
    res = agent.run_daily_cycle()
    print("[Sharky] ✅ Ciclo completado con éxito.")
    print(f"  - Estado Vital  : {res['estado_vital']}")
    print(f"  - Salud         : {res['salud']:.1f}%")
    print(f"  - Capital       : ${res['capital_actual']:,.2f}")
    print(f"  - PnL           : ${res['pnl_total_usd']:+,.2f}")
    print(f"  - Tesis Activas : {res['tesis_activas']}")
    print(f"  - Diario Creado : {res['diario_guardado']}\n")


def cmd_market(agent: SharkyAgent):
    print("\n[Sharky] 📈 Obteniendo instantánea de mercado...")
    snapshots = agent.market.get_batch_snapshots(DEFAULT_WATCHLIST)
    print("-" * 65)
    print(f"{'TICKER':<8} | {'PRECIO (USD)':<14} | {'CAMBIO (%)':<12} | {'P/E RATIO':<10}")
    print("-" * 65)
    for t, s in snapshots.items():
        pe_str = f"{s.pe_ratio:.1f}" if s.pe_ratio else "N/A"
        sign = "+" if s.cambio_diario_pct >= 0 else ""
        print(f"{s.ticker:<8} | ${s.precio_actual:<13,.2f} | {sign}{s.cambio_diario_pct:<11.2f}% | {pe_str:<10}")
    print("-" * 65)


def cmd_daemon(agent: SharkyAgent, interval_minutes: int = 60):
    print_banner()
    print(f"[Sharky] 🔄 Modo Daemon iniciado. Ejecutando ciclo cada {interval_minutes} minuto(s).")
    print("[Sharky] Presiona Ctrl+C para detener el cerebro.\n")
    try:
        while True:
            cmd_cycle(agent)
            print(f"[Sharky] Esperando {interval_minutes} minuto(s) para el siguiente ciclo...\n")
            time.sleep(interval_minutes * 60)
    except KeyboardInterrupt:
        print("\n[Sharky] 🛑 Daemon detenido por el usuario. El estado vital ha sido preservado.")


def main():
    parser = argparse.ArgumentParser(
        description="Sharky: Cerebro de Inversión Autónomo con Obsidian y Claude"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # Comando status
    subparsers.add_parser("status", help="Muestra el estado vital actual y métricas de salud")

    # Comando cycle
    subparsers.add_parser("cycle", help="Ejecuta un ciclo diario completo y actualiza la bóveda de Obsidian")

    # Comando market
    subparsers.add_parser("market", help="Muestra las cotizaciones actuales de la watchlist")

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
    elif args.command == "cycle":
        cmd_cycle(agent)
    elif args.command == "market":
        cmd_market(agent)
    elif args.command == "daemon":
        cmd_daemon(agent, interval_minutes=args.interval)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
