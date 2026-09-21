"""
Test de integridad del Grafo de Obsidian en tests/test_vault_graph.py.
Valida que no existan enlaces rotos, notas huérfanas o callejones sin salida en vault/.
"""

import re
from collections import defaultdict
from sharky.config import VAULT_PATH


def test_obsidian_graph_integrity():
    md_files = list(VAULT_PATH.rglob("*.md"))
    assert len(md_files) >= 50, f"Expected >= 50 notes in vault, got {len(md_files)}"

    file_by_stem = {f.stem: f for f in md_files}
    link_pattern = re.compile(r"\[\[([^\]\|#\n\r]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")

    missing_targets = defaultdict(set)
    in_map = defaultdict(set)
    out_map = defaultdict(set)

    for f in md_files:
        content = f.read_text(encoding="utf-8")
        links = link_pattern.findall(content)
        for link in links:
            # Dentro de una tabla el alias va escapado (`[[Nota\\|Alias]]`) para
            # que el `|` no parta la celda. Esa barra invertida la come el
            # renderizador, no es parte del nombre de la nota de destino.
            l_clean = link.strip().rstrip("\\").strip()
            # Ignore template variables like {{TICKER}}
            if not l_clean or "{{" in l_clean:
                continue
            out_map[f.stem].add(l_clean)
            if l_clean in file_by_stem:
                in_map[l_clean].add(f.stem)
            else:
                missing_targets[l_clean].add(f.stem)

    # 1. No debe haber ningún enlace roto
    assert len(missing_targets) == 0, f"Found broken link targets: {dict(missing_targets)}"

    # 2. No debe haber notas huérfanas (fuera de plantillas)
    orphans = [f.stem for f in md_files if "07_Plantillas" not in str(f) and len(in_map[f.stem]) == 0]
    assert len(orphans) == 0, f"Found orphan notes: {orphans}"

    # 3. No debe haber notas sin salida (dead ends fuera de plantillas)
    dead_ends = [f.stem for f in md_files if "07_Plantillas" not in str(f) and len(out_map[f.stem]) == 0]
    assert len(dead_ends) == 0, f"Found dead end notes: {dead_ends}"

    # 4. Ningún enlace wikilink debe estar envuelto en backticks (debe renderizar como enlace real)
    backtick_pattern = re.compile(r"`\[\[[^`\n\r]+?\]\]`")
    backtick_matches = {}
    for f in md_files:
        content = f.read_text(encoding="utf-8")
        matches = backtick_pattern.findall(content)
        if matches:
            backtick_matches[f.stem] = matches
    assert len(backtick_matches) == 0, f"Found backtick-wrapped wikilinks (should be pure [[link]]): {backtick_matches}"
