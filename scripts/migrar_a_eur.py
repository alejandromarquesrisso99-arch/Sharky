"""
Migración de un solo uso: limpia el estado heredado de la versión en USD.

Contexto
--------
La versión anterior calculaba el NAV mezclando costes en EUR con precios en USD
y contabilizaba una posición inexistente (NVDA), lo que produjo un
`capital_actual` muy por encima del valor real de la cartera.

Esa cifra inventada quedó grabada en `Estado_Vital.md` y, al introducirse el
cálculo correcto de drawdown contra el máximo histórico, se convirtió en un
high-water mark falso: el agente se declaraba en CUIDADOS INTENSIVOS con un
drawdown del 12% que nunca ocurrió.

Qué hace
--------
1. Resiembra `Estado_Vital.md` con el capital de referencia real del extracto y
   un high-water mark igual al NAV realmente medido hoy.
2. Caduca las alertas emitidas por el detector antiguo (incluidos duplicados),
   cuyos niveles venían de multiplicadores fijos y no de datos de mercado.

Es idempotente: si detecta que el capital de referencia ya quedó sembrado en
una ejecución anterior, no vuelve a resembrar `Estado_Vital.md` (lo que sí
tendría "efectos adicionales": borraría el high-water mark y el drawdown
acumulados desde entonces, devolviendo la cartera a OPTIMO aunque haya
habido un drawdown real después de la migración).

Uso:
    python scripts/migrar_a_eur.py --capital-referencia <patrimonio neto en EUR>

El capital de referencia es el patrimonio neto del extracto del bróker en la
fecha en que Sharky asume la gestión. Se pasa como argumento y no se escribe
aquí: el repositorio es público y no puede llevar la cifra de nadie.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sharky.console import enable_utf8  # noqa: E402

enable_utf8()

from sharky.models import HealthStatus, VitalState  # noqa: E402
from sharky.portfolio import PortfolioStore, PortfolioValuator  # noqa: E402
from sharky.risk_governor import RiskGovernor  # noqa: E402
from sharky.vault_manager import VaultManager  # noqa: E402


def caducar_alertas_heredadas(vault: VaultManager) -> int:
    """Marca como EXPIRADA toda alerta sin campo `fuente_precio`.

    Ese campo sólo lo escribe el detector nuevo, así que su ausencia identifica
    exactamente las alertas del motor antiguo.
    """
    caducadas = 0
    for ruta in sorted((vault.vault_path / "09_Alertas_Oportunidades").glob("*.md")):
        contenido = ruta.read_text(encoding="utf-8")
        meta, cuerpo = vault.parse_markdown(contenido)
        if not meta or meta.get("estado") != "ACTIVA":
            continue
        if "fuente_precio" in meta:
            continue  # emitida por el detector actual: se respeta

        meta["estado"] = "EXPIRADA"
        meta["motivo_expiracion"] = (
            "Emitida por el detector heredado, cuyos niveles de stop y target "
            "provenían de multiplicadores fijos en lugar de la estructura real de "
            "precios. Reemplazada por el detector con confirmación cuantitativa."
        )
        ruta.write_text(vault.build_markdown(meta, cuerpo), encoding="utf-8")
        print(f"   • Caducada: {ruta.name}")
        caducadas += 1
    return caducadas


def main() -> int:
    parser = argparse.ArgumentParser(description="Migración del estado heredado en USD a EUR.")
    parser.add_argument(
        "--capital-referencia", type=float, required=True, metavar="EUR",
        help="Patrimonio neto del extracto del bróker cuando Sharky asume la gestión.",
    )
    capital_referencia = parser.parse_args().capital_referencia

    vault = VaultManager()
    store = PortfolioStore()

    if not store.exists():
        print(f"❌ No existe el libro de posiciones en {store.ledger_path}.")
        return 1

    print("🔄 MIGRACIÓN DEL ESTADO HEREDADO (USD ficticio → EUR real)\n")

    print("1. Caducando alertas del detector antiguo:")
    caducadas = caducar_alertas_heredadas(vault)
    if caducadas == 0:
        print("   • Ninguna alerta heredada pendiente.")

    print("\n2. Resembrando el estado vital:")
    anterior = vault.read_health_status()
    print(f"   Antes  → NAV {anterior.nav_actual_eur:,.2f} € | "
          f"HWM {anterior.nav_maximo_historico_eur:,.2f} € | "
          f"estado {anterior.estado_vital.value}")

    # Guarda de idempotencia real: `capital_inicial_eur` sólo lo fija esta
    # migración (o el primer ciclo diario, que hereda el que ya hubiera). Si
    # ya coincide con la referencia, resembrar de nuevo no sería un no-op:
    # machacaría el high-water mark y el drawdown acumulados desde entonces
    # con los de este instante, ocultando un drawdown real posterior a la
    # migración. Ver la nota de idempotencia en el docstring del módulo.
    if abs(anterior.capital_inicial_eur - capital_referencia) < 0.01:
        print(
            "   • Ya migrado (capital_inicial_eur coincide con la referencia): "
            "no se resiembra para no perder el historial de drawdown acumulado."
        )
        print("\n✅ Migración ya aplicada anteriormente; nada que hacer.")
        print(f"   Alertas caducadas     : {caducadas}")
        return 0

    portfolio = store.load()
    valoracion = PortfolioValuator().value(portfolio)

    # Estado limpio: sin drawdown heredado, sin operaciones ficticias.
    semilla = HealthStatus(
        estado_vital=VitalState.OPTIMO,
        salud_porcentaje=100.0,
        energia_actual=100.0,
        capital_inicial_eur=capital_referencia,
        nav_actual_eur=valoracion.nav_eur,
        nav_maximo_historico_eur=max(capital_referencia, valoracion.nav_eur),
        drawdown_actual_pct=0.0,
        drawdown_maximo_pct=0.0,
        operaciones_ganadoras=0,
        operaciones_perdedoras=0,
    )

    governor = RiskGovernor()
    health = governor.calculate_health(
        semilla, valoracion, dias_transcurridos=0.0, actualizar_energia=False
    )
    incumplimientos = governor.audit_portfolio(valoracion, health)
    vault.update_health_status(health, valuation=valoracion, incumplimientos=incumplimientos)

    print(f"   Después → NAV {health.nav_actual_eur:,.2f} € | "
          f"HWM {health.nav_maximo_historico_eur:,.2f} € | "
          f"estado {health.estado_vital.value} | drawdown {health.drawdown_actual_pct:.2f}%")

    print("\n✅ Migración completada.")
    print(f"   Capital de referencia : {capital_referencia:,.2f} €")
    print(f"   NAV real medido       : {valoracion.nav_eur:,.2f} €")
    print(f"   Incumplimientos       : {len(incumplimientos)}")
    print(f"   Alertas caducadas     : {caducadas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
