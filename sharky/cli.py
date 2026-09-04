"""
Interfaz de línea de comandos de Sharky Capital Management.

Todos los importes se muestran en EUR, la divisa base de la cartera. Cuando un
dato no proviene del mercado, la salida lo señala: es preferible una tabla con
advertencias a una tabla limpia que miente.
"""

import argparse
import sys
from datetime import datetime

from sharky.console import enable_utf8

# Antes de cualquier print: los símbolos € y los emojis fallan en cp1252.
enable_utf8()

from sharky.agent_loop import SharkyAgent  # noqa: E402
from sharky.config import (  # noqa: E402
    BASE_CURRENCY,
    CLAUDE_MODEL,
    EXECUTION_MODE,
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
    VAULT_PATH,
    has_live_api_key,
)
from sharky.models import AssetClass, OrderType  # noqa: E402
from sharky.portfolio import PortfolioStore  # noqa: E402
from sharky.scheduler import SharkyScheduler  # noqa: E402
from sharky.trade_ledger import TradeRecorder  # noqa: E402

SEP = "=" * 78
SUB = "-" * 78


def print_banner() -> None:
    print(r"""
  ███████╗██╗  ██╗ █████╗ ██████╗ ██╗  ██╗██╗   ██╗
  ██╔════╝██║  ██║██╔══██╗██╔══██╗██║ ██╔╝╚██╗ ██╔╝
  ███████╗███████║███████║██████╔╝█████╔╝  ╚████╔╝
  ╚════██║██╔══██║██╔══██║██╔══██╗██╔═██╗   ╚██╔╝
  ███████║██║  ██║██║  ██║██║  ██║██║  ██╗   ██║
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
    SHARKY CAPITAL MANAGEMENT — Family Office Autónomo
    """)


def _valor_enum(v) -> str:
    """Nombre legible de un enum serializado.

    `RebalanceAction` hereda de `str`, así que un `isinstance(v, str)` es cierto
    y formatearlo directamente imprime `RebalanceAction.MANTENER`. Se comprueba
    primero `.value`.
    """
    return str(getattr(v, "value", v))


def _avisos(advertencias) -> None:
    if not advertencias:
        return
    print("\n⚠️  ADVERTENCIAS SOBRE LA CALIDAD DE LOS DATOS:")
    for a in advertencias:
        print(f"   • {a}")


def _incumplimientos(breaches) -> None:
    if not breaches:
        print("\n🛡️  Mandato: sin incumplimientos.")
        return
    print(f"\n🛡️  INCUMPLIMIENTOS DEL MANDATO ({len(breaches)}):")
    for b in breaches:
        sev = "🔴" if (b.get("severidad") if isinstance(b, dict) else b.severidad) == "ALTA" else "🟡"
        d = b if isinstance(b, dict) else b.model_dump()
        print(f"   {sev} [{d['sujeto']}] {d['mensaje']}")
        print(f"      → {d['accion_correctiva']}")


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------
def cmd_status(agent: SharkyAgent) -> None:
    valuation, health, breaches = agent.get_status_summary()
    alertas = agent.get_active_alerts()

    print_banner()
    print(SEP)
    print("  Firma              : Sharky Capital Management")
    print(f"  Bóveda de Obsidian : {VAULT_PATH}")
    print(f"  Divisa base        : {BASE_CURRENCY}")
    print(f"  Modo de ejecución  : {EXECUTION_MODE}")
    print(f"  CIO (Claude)       : {(CLAUDE_MODEL + ' — API conectada') if has_live_api_key() else 'Modo simulación (sin API key)'}")
    print(SUB)
    print(f"  Estado Vital       : {health.estado_vital.value}  (salud {health.salud_porcentaje:.1f}%)")
    print(f"  Energía Operativa  : {health.energia_actual:.1f} / 100.0")
    print(f"  NAV                : {health.nav_actual_eur:,.2f} €")
    print(f"  Máximo histórico   : {health.nav_maximo_historico_eur:,.2f} €")
    print(f"  PnL s/ referencia  : {health.pnl_total_eur:+,.2f} € ({health.pnl_total_pct:+.2f}%)")
    print(f"  PnL latente s/coste: {valuation.pnl_total_eur:+,.2f} € ({valuation.pnl_total_pct:+.2f}%)")
    print(f"  Drawdown           : actual {health.drawdown_actual_pct:.2f}% | máximo {health.drawdown_maximo_pct:.2f}%")
    print(f"  Liquidez           : {valuation.efectivo_eur:,.2f} € ({valuation.peso_efectivo_pct:.2f}%)")
    print(f"  Cobertura de datos : {health.cobertura_datos_pct:.1f}%")
    print(f"  Posiciones         : {len(valuation.posiciones)}")
    print(f"  Alertas activas    : {len(alertas)}")
    print(SEP)

    _incumplimientos(breaches)
    _avisos(valuation.advertencias)

    if alertas:
        print("\n🚨 OPORTUNIDADES EN RADAR:")
        for a in alertas:
            print(
                f"   • [{a.ticker}] {a.empresa} | conv. {a.conviccion}/10 | "
                f"R:R {a.ratio_rr:.2f}:1 | potencial +{a.potencial_ganancia_pct:.1f}%"
            )
    print()


def cmd_portfolio(agent: SharkyAgent) -> None:
    valuation, health, breaches = agent.get_status_summary()

    print(f"\n📒 CARTERA VALORADA A MERCADO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(SEP)
    print(f"{'ACTIVO':<20} {'SECTOR':<22} {'COTIZACIÓN':>16} {'VALOR €':>11} {'PnL €':>10} {'PnL %':>8} {'PESO':>7}")
    print(SUB)
    for p in sorted(valuation.posiciones, key=lambda x: -x.valor_mercado_eur):
        marca = " " if p.fuente_precio.es_fiable else "⚠"
        cot = f"{p.precio_cotizacion:,.2f} {p.divisa_cotizacion}"
        print(
            f"{marca}{p.ticker:<19} {p.sector[:22]:<22} {cot:>16} "
            f"{p.valor_mercado_eur:>11,.2f} {p.pnl_eur:>+10,.2f} {p.pnl_pct:>+7.2f}% {p.peso_pct:>6.2f}%"
        )
    print(SUB)
    print(f"{'  EFECTIVO':<20} {'Liquidez':<22} {'':>16} {valuation.efectivo_eur:>11,.2f} {'':>10} {'':>8} {valuation.peso_efectivo_pct:>6.2f}%")
    print(f"{'  NAV TOTAL':<20} {'':<22} {'':>16} {valuation.nav_eur:>11,.2f} {valuation.pnl_total_eur:>+10,.2f} {valuation.pnl_total_pct:>+7.2f}% {'100.00':>6}%")
    print(SEP)

    print("\n📊 EXPOSICIÓN SECTORIAL:")
    for sector, peso in sorted(valuation.exposicion_sectorial_pct.items(), key=lambda kv: -kv[1]):
        exceso = " ⛔ EXCEDE EL LÍMITE" if peso > MAX_SECTOR_SIZE_PCT else ""
        barra = "█" * int(peso / 1.5)
        print(f"   {sector:<24} {peso:>6.2f}% {barra}{exceso}")

    print(f"\n   Límites del mandato: activo ≤ {MAX_POSITION_SIZE_PCT:.0f}% | "
          f"sector ≤ {MAX_SECTOR_SIZE_PCT:.0f}% | caja ≥ {MIN_CASH_PCT:.0f}%")

    _incumplimientos(breaches)
    _avisos(valuation.advertencias)
    print()


def cmd_risk(agent: SharkyAgent) -> None:
    valuation, health, breaches = agent.get_status_summary()
    print(f"\n🛡️  AUDITORÍA DE RIESGO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(SEP)
    print(f"  Estado vital      : {health.estado_vital.value}")
    print(f"  NAV / HWM         : {health.nav_actual_eur:,.2f} € / {health.nav_maximo_historico_eur:,.2f} €")
    print(f"  Drawdown actual   : {health.drawdown_actual_pct:.2f}%")
    print(f"  Tope por activo   : {agent.risk.max_position_pct(health.estado_vital):.1f}% (según estado vital)")
    print(f"  Caja objetivo     : {agent.risk.target_cash_pct(health.estado_vital):.1f}%")
    print(SEP)
    _incumplimientos(breaches)
    _avisos(valuation.advertencias)
    print()


def cmd_committee(agent: SharkyAgent) -> None:
    print("\n[Sharky] 🏛️  Convocando sesión plenaria del Comité de Inversión...")
    res = agent.run_investment_committee()
    print_banner()
    print(f"📅 SESIÓN DEL COMITÉ DE INVERSIÓN — {res['fecha']}")
    print(SEP)

    for d in res["departamentos"]:
        print(f"\n📂 {d['departamento']} — {d['responsable']}")
        print(f"   Diagnóstico: {d['diagnostico']}")
        print("   Puntos clave:")
        for p in d["puntos_clave"]:
            print(f"     • {p}")
        if d.get("alertas_o_riesgos"):
            print("   Riesgos:")
            for r in d["alertas_o_riesgos"]:
                print(f"     ! {r}")
        if d.get("datos_ausentes"):
            print("   ⚠️  Datos no disponibles:")
            for x in d["datos_ausentes"]:
                print(f"     ? {x}")
        print(f"   💡 Recomendación: {d['recomendacion_tactica']}")
        print(SUB)

    print("\n" + SEP)
    etiqueta = "SIMULADA (sin Claude)" if res["veredicto_simulado"] else f"por {res['modelo']}"
    print(f"👔 RESOLUCIÓN EJECUTIVA DEL CIO — {etiqueta}")
    print(SEP)
    print(res["veredicto_cio"])
    print(SEP + "\n")


def cmd_startup(agent: SharkyAgent) -> None:
    """Ciclo diario pensado para lanzarse al encender el ordenador.

    Si Sharky ya completó su ciclo diario hoy (p.ej. porque el ordenador se ha
    reiniciado varias veces), no vuelve a ejecutarlo: la API de Claude se
    invoca como máximo una vez al día, sin importar cuántas veces arranque.
    """
    if agent.ya_completo_ciclo_hoy():
        print("\n[Sharky] ℹ️  El ciclo diario de hoy ya se completó. No se vuelve a llamar a la API de Claude.\n")
        cmd_status(agent)
        return
    cmd_cycle(agent)


def cmd_cycle(agent: SharkyAgent) -> None:
    print("\n[Sharky] 🛰️  Iniciando vigilancia diaria...")
    res = agent.run_daily_cycle()
    print("[Sharky] ✅ Sesión completada.\n")
    print(f"  Estado Vital       : {res['estado_vital']} (salud {res['salud']:.1f}%)")
    print(f"  Energía            : {res['energia']:.1f} / 100.0")
    print(f"  NAV                : {res['nav_eur']:,.2f} €")
    print(f"  PnL s/ referencia  : {res['pnl_total_eur']:+,.2f} € ({res['pnl_total_pct']:+.2f}%)")
    print(f"  Drawdown actual    : {res['drawdown_actual_pct']:.2f}%")
    print(f"  Posiciones / Tesis : {res['posiciones']} / {res['tesis_activas']}")
    print(f"  Cobertura de datos : {res['cobertura_datos_pct']:.1f}%")
    print(f"  Diario guardado    : {res['diario_guardado']}")
    if res["inteligencia_simulada"]:
        print("  ⚠️  Inteligencia    : SIMULADA (configura ANTHROPIC_API_KEY para análisis real)")

    _incumplimientos(res["incumplimientos"])

    if res["alertas_nuevas"]:
        print("\n🚨 NUEVAS OPORTUNIDADES DETECTADAS:")
        for a in res["alertas_nuevas"]:
            print(
                f"   ⭐ [{a['ticker']}] {a['empresa']} | conv. {a['conviccion']}/10 | "
                f"R:R {a['ratio_rr']:.2f}:1 | stop {a['stop_loss']:,.2f} {a['divisa']}"
            )
    else:
        print("\n🔍 RADAR: ningún candidato cualifica hoy.")
        for t in res["diagnostico_radar"]:
            print(f"   {t['ticker']:<8} [{t['veredicto']}] {t['detalle']}")

    if res["alertas_stop_loss"]:
        print()
        for a in res["alertas_stop_loss"]:
            print(f"  {a}")

    if res["rebalanceo_generado"]:
        print(f"\n  📅 REBALANCEO DEL DÍA 1 GENERADO: {res['rebalanceo_generado']}")

    _avisos(res["advertencias"])
    print()


def cmd_alerts(agent: SharkyAgent) -> None:
    alertas = agent.get_active_alerts()
    print(f"\n🚨 RADAR DE OPORTUNIDADES — {len(alertas)} activa(s)\n")
    if not alertas:
        print("Sin alertas activas. Ejecuta `daily` para escanear el mercado.")
        print()
        return
    print(SEP)
    print(f"{'TICKER':<8} {'EMPRESA':<26} {'CONV':>5} {'PRECIO':>13} {'STOP':>11} {'TARGET':>11} {'R:R':>6} {'POT.':>7}")
    print(SUB)
    for a in alertas:
        print(
            f"{a.ticker:<8} {a.empresa[:26]:<26} {a.conviccion:>3}/10 "
            f"{a.precio_actual:>9,.2f} {a.divisa:<3} {a.stop_loss:>11,.2f} "
            f"{a.target_precio:>11,.2f} {a.ratio_rr:>6.2f} {a.potencial_ganancia_pct:>+6.1f}%"
        )
    print(SEP)
    print("👉 Detalle y catalizadores en: vault/09_Alertas_Oportunidades/\n")


def cmd_monthly(agent: SharkyAgent) -> None:
    print("\n[Sharky] 📅 Generando propuesta de rebalanceo del Día 1...")
    res = agent.generate_monthly_rebalance()
    print(f"[Sharky] ✅ Propuesta para {res['mes_ano']} generada.\n")
    print(f"  Informe            : {res['archivo_informe']}")
    print(f"  NAV total          : {res['nav_total_eur']:,.2f} €")
    print(f"  Caja objetivo      : {res['cash_objetivo_pct']:.2f}% ({res['cash_objetivo_eur']:,.2f} €)")
    print(f"  Cobertura de datos : {res['cobertura_datos_pct']:.1f}%")

    print("\n--- 📋 ACCIONES PARA EL DÍA 1 ---")
    print(f"{'ACTIVO':<20} {'ACCIÓN':<12} {'ACTUAL':>8} {'OBJETIVO':>9} {'DELTA €':>11} {'STOP':>13}")
    print(SUB)
    for p in res["propuestas"]:
        accion = _valor_enum(p["accion"])
        delta = f"{p['delta_eur']:+,.2f}"
        stop = f"{p['stop_loss_sugerido']:,.2f} {p['divisa_precio']}"
        print(
            f"{p['ticker']:<20} {accion:<12} {p['peso_actual_pct']:>7.2f}% "
            f"{p['peso_objetivo_pct']:>8.2f}% {delta:>11} {stop:>13}"
        )
    print(SUB)
    total_venta = sum(p["delta_eur"] for p in res["propuestas"] if p["delta_eur"] < 0)
    total_compra = sum(p["delta_eur"] for p in res["propuestas"] if p["delta_eur"] > 0)
    print(f"  Capital a liberar : {abs(total_venta):,.2f} €")
    print(f"  Capital a invertir: {total_compra:,.2f} €")

    _incumplimientos(res["incumplimientos"])
    _avisos(res["advertencias"])
    print("\n👉 Informe completo en: vault/08_Rebalanceos_Mensuales/\n")


def cmd_macro(agent: SharkyAgent) -> None:
    print("\n🌐 TERMÓMETRO MACROECONÓMICO")
    macros = agent.market.get_macro_overview()
    descripciones = {
        "SPY": "S&P 500 — renta variable USA",
        "QQQ": "Nasdaq 100 — tecnología",
        "TLT": "Bonos 20Y+ — tipos de interés",
        "GLD": "Oro físico — refugio",
        "USO": "Petróleo WTI — energía",
    }
    print(SEP)
    print(f"{'PROXY':<8} {'PRECIO':>14} {'CAMBIO':>9} {'FUENTE':<10} DESCRIPCIÓN")
    print(SUB)
    for t, s in macros.items():
        marca = "" if s.es_fiable else " ⚠"
        print(
            f"{s.ticker:<8} {s.precio_actual:>10,.2f} {s.divisa:<3} "
            f"{s.cambio_diario_pct:>+8.2f}% {s.fuente.value:<10}{descripciones.get(t, '')}{marca}"
        )
    print(SEP + "\n")


def cmd_trade(agent: SharkyAgent, args) -> None:
    """Registra una operación ya ejecutada en el broker."""
    recorder = TradeRecorder(
        store=agent.store,
        valuator=agent.valuator,
        governor=agent.risk,
        vault=agent.vault,
        fx=agent.fx,
        market=agent.market,
    )
    tipo = OrderType.COMPRA if args.tipo.upper() in ("COMPRA", "BUY", "C") else OrderType.VENTA

    print(f"\n🧾 Registrando {tipo.value} de {args.unidades} × {args.ticker} @ {args.precio}...")
    resultado = recorder.record(
        ticker=args.ticker,
        tipo_orden=tipo,
        unidades=args.unidades,
        precio=args.precio,
        divisa=args.divisa,
        comision_eur=args.comision,
        stop_loss=args.stop or 0.0,
        target_precio=args.target or 0.0,
        tesis_referencia=args.tesis or "",
        justificacion=args.motivo or "",
        nombre=args.nombre,
        isin=args.isin,
        ticker_cotizacion=args.simbolo,
        clase=AssetClass(args.clase.upper()) if args.clase else AssetClass.ACCION,
        sector=args.sector or "",
        forzar=args.forzar,
    )

    print(SEP)
    if resultado.aprobada:
        if resultado.motivo.startswith("⚠️"):
            print("✅ OPERACIÓN REGISTRADA (con incumplimiento del mandato)")
        else:
            print("✅ OPERACIÓN REGISTRADA")
        print(f"   {resultado.motivo}")
        print(f"   NAV posterior      : {resultado.nav_posterior_eur:,.2f} €")
        print(f"   Efectivo posterior : {resultado.efectivo_posterior_eur:,.2f} €")
        if resultado.pnl_realizado_eur is not None:
            print(f"   PnL realizado      : {resultado.pnl_realizado_eur:+,.2f} €")
        print(f"   Nota               : {resultado.nota_operacion}")
    else:
        print("⛔ OPERACIÓN RECHAZADA POR EL RISKGOVERNOR")
        print(f"   {resultado.motivo}")
        print("\n   El libro de posiciones NO se ha modificado.")
    print(SEP + "\n")


def cmd_resolve_isin(agent: SharkyAgent, args) -> None:
    """Sugiere símbolos de cotización para los ISIN del libro."""
    store = PortfolioStore()
    print("\n🔎 RESOLUCIÓN DE ISIN → SÍMBOLO DE COTIZACIÓN")
    print("   Las sugerencias deben confirmarse a mano antes de darlas por buenas.")
    print(SEP)

    if args.isin:
        objetivos = [(args.isin, args.isin)]
    else:
        portfolio = store.load()
        objetivos = [
            (p.ticker, p.isin)
            for p in portfolio.posiciones
            if p.isin and not p.ticker_cotizacion
        ]
        if not objetivos:
            print("   Todas las posiciones con ISIN ya tienen símbolo asignado. ✅")
            print(SEP + "\n")
            return

    for etiqueta, isin in objetivos:
        simbolo = agent.market.find_symbol_by_isin(isin)
        if simbolo:
            snap = agent.market.get_snapshot(etiqueta, symbol=simbolo)
            precio = (
                f"{snap.precio_actual:,.2f} {snap.divisa}" if snap.precio_actual > 0 else "sin cotización"
            )
            print(f"   {etiqueta:<20} {isin:<14} → {simbolo:<12} ({precio})")
        else:
            print(f"   {etiqueta:<20} {isin:<14} → no resuelto")
    print(SEP + "\n")


def cmd_service(interval_minutes: int) -> None:
    print_banner()
    SharkyScheduler(check_interval_minutes=interval_minutes).start()


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharky",
        description="Sharky Capital Management — Family Office autónomo (divisa base: EUR)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Estado vital, NAV y incumplimientos del mandato")
    sub.add_parser("portfolio", help="Cartera valorada a mercado y exposición sectorial")
    sub.add_parser("risk", help="Auditoría de riesgo contra las reglas de supervivencia")
    sub.add_parser("committee", help="Sesión plenaria del Comité de Inversión")
    sub.add_parser("daily", help="Vigilancia diaria: valoración, stop-loss, radar y diario")
    sub.add_parser("cycle", help="Alias de daily")
    sub.add_parser(
        "startup",
        help="Ciclo diario para lanzar al encender el ordenador (omite el ciclo si ya se hizo hoy)",
    )
    sub.add_parser("alerts", help="Alertas de oportunidad activas")
    sub.add_parser("monthly", help="Propuesta de rebalanceo del Día 1")
    sub.add_parser("rebalance", help="Alias de monthly")
    sub.add_parser("macro", help="Termómetro macroeconómico (SPY, QQQ, TLT, GLD, USO)")

    p_trade = sub.add_parser(
        "trade",
        help="Registra una operación YA ejecutada en el broker (pasa por el RiskGovernor)",
    )
    p_trade.add_argument("tipo", choices=["compra", "venta", "COMPRA", "VENTA"], help="Sentido")
    p_trade.add_argument("ticker", help="Ticker interno del activo (p.ej. MSFT)")
    p_trade.add_argument("unidades", type=float, help="Títulos operados")
    p_trade.add_argument("precio", type=float, help="Precio de ejecución en la divisa de cotización")
    p_trade.add_argument("--divisa", help="Divisa de ejecución (por defecto: la de la posición)")
    p_trade.add_argument("--comision", type=float, default=0.0, help="Comisión en EUR")
    p_trade.add_argument("--stop", type=float, help="Stop-loss (obligatorio en compras)")
    p_trade.add_argument("--target", type=float, help="Objetivo (obligatorio en compras)")
    p_trade.add_argument("--tesis", help="Nota de tesis de referencia")
    p_trade.add_argument("--motivo", help="Justificación de la operación")
    p_trade.add_argument("--nombre", help="Nombre completo (para posiciones nuevas)")
    p_trade.add_argument("--isin", help="ISIN (para posiciones nuevas)")
    p_trade.add_argument("--simbolo", help="Símbolo de cotización (para posiciones nuevas)")
    p_trade.add_argument("--sector", help="Sector (para posiciones nuevas)")
    p_trade.add_argument(
        "--forzar",
        action="store_true",
        help=(
            "Registra la operación aunque el RiskGovernor la rechace por "
            "incumplir el mandato (tope de posición/sector, liquidez mínima, "
            "stop-loss/R:R, estado vital). El mandato queda como aviso, no "
            "como bloqueo -- la decisión es del usuario."
        ),
    )
    p_trade.add_argument(
        "--clase", choices=["ACCION", "ETF", "ETC", "CRIPTO"], help="Clase de activo"
    )

    p_isin = sub.add_parser("resolve-isin", help="Sugiere símbolos para los ISIN sin mapear")
    p_isin.add_argument("--isin", help="Resolver un ISIN concreto")

    for nombre in ("service", "daemon"):
        p = sub.add_parser(nombre, help="Servicio autónomo 24/7")
        p.add_argument("--interval", type=int, default=60, help="Minutos entre escaneos (defecto: 60)")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in ("service", "daemon"):
        cmd_service(getattr(args, "interval", 60))
        return 0

    try:
        agent = SharkyAgent()
    except Exception as exc:
        print(f"❌ No se pudo inicializar Sharky: {exc}")
        return 1

    comandos = {
        "status": lambda: cmd_status(agent),
        None: lambda: cmd_status(agent),
        "portfolio": lambda: cmd_portfolio(agent),
        "risk": lambda: cmd_risk(agent),
        "committee": lambda: cmd_committee(agent),
        "daily": lambda: cmd_cycle(agent),
        "cycle": lambda: cmd_cycle(agent),
        "startup": lambda: cmd_startup(agent),
        "alerts": lambda: cmd_alerts(agent),
        "monthly": lambda: cmd_monthly(agent),
        "rebalance": lambda: cmd_monthly(agent),
        "macro": lambda: cmd_macro(agent),
        "trade": lambda: cmd_trade(agent, args),
        "resolve-isin": lambda: cmd_resolve_isin(agent, args),
    }

    accion = comandos.get(args.command)
    if accion is None:
        parser.print_help()
        return 1

    try:
        accion()
    except FileNotFoundError as exc:
        print(f"\n❌ {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
