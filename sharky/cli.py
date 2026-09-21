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
    MAX_POSITION_SIZE_PCT,
    MAX_SECTOR_SIZE_PCT,
    MIN_CASH_PCT,
    VAULT_PATH,
    has_live_api_key,
)
from sharky.models import AssetClass, OrderType  # noqa: E402
from sharky import primer_arranque  # noqa: E402
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


def _niveles(res: dict) -> None:
    """Bloque de niveles alcanzados, lo primero que se imprime del ciclo.

    Va por delante del NAV y del estado vital a propósito: un stop cruzado es
    lo único de toda la salida que exige actuar hoy, y hasta 2026-09 aparecía
    al final, después de la tabla del radar. Un aviso que hay que buscar
    haciendo scroll no es un aviso.
    """
    avisos = res.get("avisos_niveles") or []
    stops = res.get("stops_alcanzados", 0)
    targets = res.get("targets_alcanzados", 0)

    if not avisos:
        print("\n🎯 NIVELES: ninguna posición ha tocado su stop-loss ni su target.")
        return

    print("\n" + SEP)
    titulo = []
    if stops:
        titulo.append(f"{stops} STOP-LOSS")
    if targets:
        titulo.append(f"{targets} TARGET")
    print(f"🎯 NIVELES ALCANZADOS — {' | '.join(titulo) if titulo else 'REVISAR'}")
    print(SEP)
    for aviso in avisos:
        print(f"  {aviso}")
    if stops:
        print(SUB)
        print("  ⛔ El mandato exige liquidar las posiciones con el stop cruzado.")
        print("     Ejecuta en Trade Republic y regístralo: `sharky trade venta ...`")
    print(SEP)


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

    Además, si toca, lanza en el mismo arranque el escaneo semanal de
    noticias (`SharkyAgent.noticias_semanales_pendiente`) y después el
    estudio mensual (`SharkyAgent.estudio_mensual_pendiente`), en ese orden
    para que el estudio lea las noticias más recientes. Sharky no corre como
    servicio permanente, así que este es el único punto de entrada fiable
    para lo que debe pasar una vez por semana o por mes.
    """
    if agent.ya_completo_ciclo_hoy():
        print("\n[Sharky] ℹ️  El ciclo diario de hoy ya se completó. No se vuelve a llamar a la API de Claude.\n")
        cmd_status(agent)
        # Los niveles sí se revisan otra vez: no cuesta una llamada a la API,
        # y un stop cruzado a media tarde no puede esperar a mañana sólo
        # porque el diario de hoy ya estuviera escrito.
        cmd_niveles(agent)
    else:
        cmd_cycle(agent)

    if agent.noticias_semanales_pendiente():
        cmd_news(agent)

    if agent.estudio_mensual_pendiente():
        cmd_monthly(agent)


def cmd_cycle(agent: SharkyAgent) -> None:
    print("\n[Sharky] 🛰️  Iniciando vigilancia diaria...")
    res = agent.run_daily_cycle()
    print("[Sharky] ✅ Sesión completada.")

    _niveles(res)

    print()
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

    if res.get("alertas_caducadas"):
        print(f"\n⚪ ALERTAS CADUCADAS ({len(res['alertas_caducadas'])}):")
        for c in res["alertas_caducadas"]:
            print(f"   · [{c['ticker']}] {c['motivo']}")
        for t in res["diagnostico_radar"]:
            print(f"   {t['ticker']:<8} [{t['veredicto']}] {t['detalle']}")

    if res["posiciones_a_vigilar"]:
        print(
            "\n  👀 A vigilar en el escaneo semanal: " + ", ".join(res["posiciones_a_vigilar"])
        )

    _avisos(res["advertencias"])
    print()


def cmd_niveles(agent: SharkyAgent) -> None:
    """Comprueba stop-loss y take-profit sin escribir el diario.

    No consume la API de Claude: sólo valora la cartera y compara. Pensado
    para consultarlo tantas veces al día como quieras.
    """
    res = agent.revisar_niveles_ahora()
    _niveles(res)
    if res["cobertura_datos_pct"] < 100.0:
        print(
            f"\n  ⚠️  Sólo el {res['cobertura_datos_pct']:.1f}% del NAV tiene cotización "
            "fiable: los niveles del resto no se han podido comprobar."
        )
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
    """Estudio mensual completo: plan del motor + reevaluación de Claude."""
    print("\n[Sharky] 🧠 Estudio mensual: plan de rebalanceo y reevaluación de posiciones...")
    res = agent.run_monthly_study()
    if res["estudio_simulado"]:
        print(f"[Sharky] ⚠️  Estudio de {res['mes']} SIN Claude: sólo el plan determinista.")
        if res["estudio_error"]:
            print(f"           Motivo: {res['estudio_error']}")
    else:
        print(f"[Sharky] ✅ Estudio de {res['mes']} completado ({res['modelo']}).")
    print(f"  Estudio            : {res['estudio_guardado']}")
    _imprimir_plan(res)

    _revision_tesis(res.get("revision_tesis") or {})


def cmd_rebalance(agent: SharkyAgent) -> None:
    """Sólo el plan determinista del motor, sin llamar a Claude."""
    print("\n[Sharky] 📅 Generando propuesta de rebalanceo del Día 1...")
    res = agent.generate_monthly_rebalance()
    print(f"[Sharky] ✅ Propuesta para {res['mes_ano']} generada.\n")
    _imprimir_plan(res)


def _imprimir_plan(res: dict) -> None:
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


def cmd_news(agent: SharkyAgent) -> None:
    """Escaneo semanal de noticias relevantes para los activos en cartera.

    A diferencia de `daily`, no hay resultado determinista sin API: sin
    `ANTHROPIC_API_KEY` en vivo el escaneo no busca nada y lo dice, en vez de
    fingir un análisis que no ocurrió.
    """
    print("\n[Sharky] 📰 Buscando noticias de la semana para los activos en cartera...")
    res = agent.run_weekly_news_scan()
    if not res["activos_analizados"]:
        print("[Sharky] ℹ️  Sin posiciones en cartera: nada que buscar.\n")
        return
    if not res["disponible"]:
        print(f"[Sharky] ⚠️  Escaneo no disponible: {res['error']}")
        print("           Configura ANTHROPIC_API_KEY en `.env` para que se ejecute de verdad.\n")
        return
    print(f"[Sharky] ✅ Escaneo completado ({res['modelo']}).\n")
    print(f"  Activos analizados : {', '.join(res['activos_analizados'])}")
    print(f"  Contexto           : {res['dias_de_contexto']} control(es) diario(s)")
    if res["prioritarios"]:
        print(f"  Investigados antes : {', '.join(res['prioritarios'])}")
    print(f"  Búsquedas web      : {res['busquedas_realizadas']}")
    print(f"  Fuentes citadas    : {res['num_fuentes']}")
    print(f"  Nota guardada      : {res['nota_guardada']}\n")


def _revision_tesis(res: dict, sangria: str = "  ") -> None:
    """Resumen de una revisión de tesis, compartido por `monthly` y `revisar`."""
    if not res:
        return
    if not res.get("disponible"):
        print(f"{sangria}⚠️  Revisión de tesis no disponible: {res.get('error')}")
        return

    revisadas = res.get("revisadas") or []
    seleccionadas = res.get("seleccionadas") or []
    if not seleccionadas:
        print(f"{sangria}📘 Ninguna tesis necesitaba revisión este mes.")
        return

    print(f"\n{sangria}📘 TESIS REVISADAS ({len(revisadas)} de {res.get('tesis_activas', 0)} activas):")
    iconos = {"MANTENER": "🟢", "AMPLIAR": "🔵", "REDUCIR": "🟡", "CERRAR": "🔴"}
    motivos = {s["ticker"]: s["motivos"] for s in seleccionadas}
    for r in revisadas:
        print(f"{sangria}  {iconos.get(r['veredicto'], '·')} {r['ticker']:<18} {r['veredicto']}")
        print(f"{sangria}     porque: {', '.join(motivos.get(r['ticker'], [])) or 'sin motivo registrado'}")
        if r.get("propuesta_niveles"):
            print(f"{sangria}     ⚠️  Propone (NO aplicado): {r['propuesta_niveles']}")

    if res.get("aviso_parseo"):
        print(f"{sangria}  ⚠️  {res['aviso_parseo']}")

    omitidas = res.get("omitidas") or []
    if omitidas:
        print(f"{sangria}  (Sin revisar, sin novedades este mes: "
              f"{', '.join(o['ticker'] for o in omitidas)})")


def cmd_revisar_tesis(agent: SharkyAgent) -> None:
    """Revisión de las tesis activas que tienen algo que decir.

    No reescribe nada: apila una sección fechada sobre cada tesis revisada y
    deja los niveles intactos. Una propuesta de cambiar un stop se escribe
    como propuesta y la aplicas tú.
    """
    print("\n[Sharky] 📘 Revisando las tesis activas...")
    res = agent.run_thesis_review()

    if not res["disponible"] and not res["seleccionadas"]:
        print("[Sharky] ℹ️  Ninguna tesis necesitaba revisión este mes.\n")
        _seleccion_omitida(res)
        return
    if not res["disponible"]:
        print(f"[Sharky] ⚠️  Revisión no disponible: {res['error']}")
        print("           Configura ANTHROPIC_API_KEY en `.env` para que se ejecute de verdad.\n")
        return

    print(f"[Sharky] ✅ Revisión completada ({res['modelo']}).")
    _revision_tesis(res, sangria="")
    if res.get("sintesis"):
        print(f"\n{res['sintesis'].strip()}")
    print()


def _seleccion_omitida(res: dict) -> None:
    omitidas = res.get("omitidas") or []
    if not omitidas:
        return
    print("  Sin novedades este mes:")
    for o in omitidas:
        print(f"    · {o['ticker']:<18} {o['motivo']}")
    print()


def cmd_explorar(agent: SharkyAgent) -> None:
    """Exploración de mercado: busca oportunidades asimétricas nuevas.

    Como `news`, no hay resultado determinista sin API: sin
    `ANTHROPIC_API_KEY` en vivo no se busca nada y se dice, en vez de fingir
    una idea que nadie tuvo.
    """
    print("\n[Sharky] 🔭 Explorando el mercado en busca de asimetrías nuevas...")
    print("           (búsqueda web con el modelo más capaz: puede tardar varios minutos)")
    res = agent.run_market_exploration()

    if not res["disponible"]:
        print(f"[Sharky] ⚠️  Exploración no disponible: {res['error']}")
        print("           Configura ANTHROPIC_API_KEY en `.env` para que se ejecute de verdad.\n")
        return

    print(f"[Sharky] ✅ Exploración completada ({res['modelo']}).\n")
    print(f"  Candidatos propuestos : {len(res['candidatos'])}")
    print(f"  Búsquedas web         : {res['busquedas_realizadas']}")
    print(f"  Fuentes citadas       : {res['num_fuentes']}")
    print(f"  Activos ya cubiertos  : {len(res['excluidos'])} (excluidos de la búsqueda)")
    print(f"  Informe guardado      : {res['informe_guardado']}")

    if res["aviso_parseo"]:
        print(f"\n⚠️  No se pudo leer la lista de candidatos: {res['aviso_parseo']}")
        print("    El informe está guardado, pero no se ha evaluado ningún candidato.\n")
        return

    if res["candidatos"]:
        print("\n🔎 CANDIDATOS PROPUESTOS:")
        for c in res["candidatos"]:
            print(f"   · [{c['ticker']}] {c['empresa']} | conv. {c['conviccion']}/10 | {c['sector'] or 'sin sector'}")

    if res["alertas_nuevas"]:
        print("\n🚨 CONFIRMADOS POR DATOS (alertas nuevas):")
        for a in res["alertas_nuevas"]:
            print(
                f"   ⭐ [{a['ticker']}] {a['empresa']} | conv. {a['conviccion']}/10 | "
                f"R:R {a['ratio_rr']:.2f}:1 | stop {a['stop_loss']:,.2f} {a['divisa']}"
            )
    elif res["candidatos"]:
        print("\n⚪ Ningún candidato superó el filtro cuantitativo: sin alertas nuevas.")
        print("   Las ideas quedan registradas en el informe para volver a mirarlas.")

    if res["diagnostico_radar"]:
        print("\n📋 Veredicto por candidato:")
        for d in res["diagnostico_radar"]:
            print(f"   {d['ticker']:<8} {d['veredicto']:<14} {d['detalle']}")
    print()


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
        divisa_niveles=args.divisa_niveles,
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
        if resultado.tesis_abierta:
            print(f"   🎯 Tesis abierta   : {resultado.tesis_abierta}")
            print("      (la posición ya tiene stop vigilado por `sharky niveles`)")
        if resultado.tesis_cerrada:
            print(f"   📁 Tesis archivada : {resultado.tesis_cerrada}")
        if resultado.alerta_actualizada:
            print(f"   ✅ Alerta ejecutada: {resultado.alerta_actualizada}")
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
    sub.add_parser(
        "niveles",
        help="Comprueba stop-loss y take-profit de las tesis abiertas (sin llamar a Claude)",
    )
    sub.add_parser("levels", help="Alias de niveles")
    sub.add_parser("alerts", help="Alertas de oportunidad activas")
    for nombre in ("revisar-tesis", "review"):
        sub.add_parser(
            nombre,
            help="Revisa las tesis activas con novedades (añade, nunca sobrescribe)",
        )
    for nombre in ("explorar", "explore"):
        sub.add_parser(
            nombre,
            help="Busca oportunidades asimétricas nuevas en el mercado (web + Claude)",
        )
    sub.add_parser("monthly", help="Estudio mensual: rebalanceo del Día 1 + reevaluación de posiciones con Claude")
    sub.add_parser("rebalance", help="Sólo el plan de rebalanceo del Día 1, sin Claude")
    sub.add_parser("macro", help="Termómetro macroeconómico (SPY, QQQ, TLT, GLD, USO)")
    sub.add_parser(
        "noticias",
        help="Escaneo semanal de noticias relevantes para los activos en cartera",
    )
    sub.add_parser("news", help="Alias de noticias")

    p_trade = sub.add_parser(
        "trade",
        help="Registra una operación YA ejecutada en el broker (pasa por el RiskGovernor)",
    )
    p_trade.add_argument("tipo", choices=["compra", "venta", "COMPRA", "VENTA"], help="Sentido")
    p_trade.add_argument("ticker", help="Ticker interno del activo (p.ej. MSFT)")
    p_trade.add_argument("unidades", type=float, help="Títulos operados")
    p_trade.add_argument("precio", type=float, help="Precio de ejecución en la divisa de cotización")
    p_trade.add_argument("--divisa", help="Divisa de ejecución (por defecto: la de la posición)")
    p_trade.add_argument(
        "--divisa-niveles",
        help="Divisa en la que se han dado --stop/--target, si es distinta de --divisa "
        "(se convierten a la divisa de ejecución antes de validar la orden)",
    )
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

    p_app = sub.add_parser("app", help="Abre la app de gestión (servidor local + ventana)")
    p_app.add_argument("--puerto", type=int, default=None, help="Puerto local (defecto: 8765)")
    p_app.add_argument("--no-abrir", action="store_true", help="Sólo el servidor, sin abrir ventana")

    p_init = sub.add_parser(
        "init", help="Configuración inicial: clave de Claude y posiciones desde un CSV"
    )
    p_init.add_argument(
        "--abrir-app", action="store_true",
        help="Abre la app al terminar (lo usa el acceso directo de la app)",
    )

    return parser


def cmd_init(args) -> int:
    listo = primer_arranque.asistente()
    if args.abrir_app:
        # Consola abierta sólo para el asistente desde el acceso directo de la
        # app: sin esta pausa se cerraría antes de poder leer el resultado.
        if listo:
            primer_arranque.abrir_app()
        try:
            input("\nPulsa Enter para cerrar esta ventana...")
        except (EOFError, KeyboardInterrupt):
            pass
    return 0 if listo else 1


def _configurar_y_repetir(argumentos: list) -> int:
    """Primer arranque desde cualquier comando: asistente y, si termina bien,
    la orden original en un proceso nuevo (que ya lee el `.env` recién escrito)."""
    if not primer_arranque.es_interactivo():
        # La tarea programada no tiene a nadie delante: esperar una respuesta
        # la dejaría colgada. Queda el aviso en su log.
        print(
            "❌ Sharky todavía no está configurado: no hay libro de posiciones en "
            f"{PortfolioStore().ledger_path}.\n"
            "   Abre una terminal en la carpeta de Sharky y ejecuta: python -m sharky.cli init"
        )
        return 2
    if not primer_arranque.asistente():
        return 1
    print("\n▶️  Sigo con lo que habías pedido...\n")
    return primer_arranque.relanzar("sharky.cli", argumentos)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    if primer_arranque.falta_configurar():
        return _configurar_y_repetir(sys.argv[1:])

    if args.command in ("service", "daemon"):
        cmd_service(getattr(args, "interval", 60))
        return 0

    if args.command == "app":
        from sharky.app.servidor import main as app_main

        argumentos = ["--no-abrir"] if args.no_abrir else []
        if args.puerto:
            argumentos += ["--puerto", str(args.puerto)]
        return app_main(argumentos)

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
        "niveles": lambda: cmd_niveles(agent),
        "levels": lambda: cmd_niveles(agent),
        "alerts": lambda: cmd_alerts(agent),
        "revisar-tesis": lambda: cmd_revisar_tesis(agent),
        "review": lambda: cmd_revisar_tesis(agent),
        "explorar": lambda: cmd_explorar(agent),
        "explore": lambda: cmd_explorar(agent),
        "monthly": lambda: cmd_monthly(agent),
        "rebalance": lambda: cmd_rebalance(agent),
        "macro": lambda: cmd_macro(agent),
        "noticias": lambda: cmd_news(agent),
        "news": lambda: cmd_news(agent),
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
