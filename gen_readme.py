#!/usr/bin/env python3
"""Actualiza el README con la tabla de comandos definidos en actions.json."""
import json
from pathlib import Path

BASE = Path(__file__).parent
ACTIONS_FILE = BASE / "actions.json"
README_FILE = BASE / "README.md"
MARK_START = "{{ACCIONES}}"
MARK_END = "{{FIN_ACCIONES}}"
TABLE_HEADER = "| Comando | Descripción | Uso |"


def build_table(actions: dict) -> str:
    rows = ["| Comando | Descripción | Uso |", "| --- | --- | --- |"]
    for name, action in actions.items():
        desc = action.get("description", "").replace("|", "\\|")
        usage = f"fsort.py {name}"
        if action.get("type") == "command":
            command = action.get("command", "")
            used = sorted({int(n) for n in __import__("re").findall(r"\{(\d+)\}", command)})
            if used:
                usage += " " + " ".join(f"<arg{i}>" for i in used)
        elif name in ("vaciar", "vaciar-copiar"):
            usage += " <directorio> <destino>"
        elif name in ("mover", "mover-copiar"):
            usage += " <elemento>... <destino>"
        elif name.startswith("duplicados"):
            usage += " <directorio>"
        elif name.startswith("mas-grandes"):
            usage += " <directorio> [top]"
        elif name.startswith("vaciar-papelera"):
            usage += " [papelera]"
        elif name == "resumir":
            usage += " <archivo> [destino.txt]"
        elif action.get("type") == "ai":
            usage += ' "tu pregunta"'
        else:
            usage += " <directorio>"
        rows.append(f"| `{name}` | {desc} | `{usage}` |")
    return "\n".join(rows)


def _ai_defaults_match_code() -> list:
    """Comprueba que AI_ENV_VARS coincide con los defaults reales de fsort.py.

    Devuelve la lista de discrepancias (vacia si todo cuadra). Evita que el
    README documente defaults que ya no son los del codigo.
    """
    from config import AI_ENV_VARS
    mismatches = []
    try:
        import fsort
        cfg = fsort._ai_config()
        # CA por defecto (fsort._ssl_context)
        expected = {
            "FSORT_AI_URL": f"`{cfg['base_url']}`",
            "FSORT_AI_MODEL": f"`{cfg['model']}`",
            "FSORT_AI_KEY": "—",
        }
        for var, _desc, default in AI_ENV_VARS:
            if var in expected and default != expected[var]:
                mismatches.append(
                    f"{var}: README dice '{default}' pero fsort usa '{expected[var]}'")
    except ImportError:
        mismatches.append("no se pudo importar fsort para verificar defaults")
    return mismatches


def main() -> int:
    mismatches = _ai_defaults_match_code()
    if mismatches:
        print("Error: los defaults IA del README no coinciden con el codigo:")
        for m in mismatches:
            print(f"  - {m}")
        print("Actualiza AI_ENV_VARS en config.py.")
        return 1

    try:
        with open(ACTIONS_FILE, encoding="utf-8") as f:
            actions = json.load(f).get("actions", {})
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error al leer {ACTIONS_FILE}: {e}")
        return 1

    with open(README_FILE, encoding="utf-8") as f:
        readme = f.read()

    if MARK_START in readme and MARK_END in readme:
        start = readme.index(MARK_START)
        end = readme.index(MARK_END)
    elif TABLE_HEADER in readme:
        start = readme.index(TABLE_HEADER)
        end = readme.index("\n\n## Uso", start)
    else:
        print(f"Error: el README debe contener {MARK_START}/{MARK_END} o la tabla generada.")
        return 1

    suffix = readme[end:]
    if suffix.startswith(MARK_END):
        suffix = suffix[len(MARK_END):]
    new_readme = readme[:start] + build_table(actions) + "\n\n" + suffix.lstrip("\n")
    new_readme = _ensure_ai_section(new_readme)

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print(f"README actualizado con {len(actions)} comando(s).")
    return 0


def _ai_table() -> str:
    """Construye la tabla de variables IA desde AI_ENV_VARS (unica fuente de verdad
    en config.py), para no duplicar defaults en dos sitios y desincronizarlos."""
    from config import AI_ENV_VARS
    rows = [
        "| Variable | Descripción | Por defecto |",
        "| --- | --- | --- |",
    ]
    for var, desc, default in AI_ENV_VARS:
        rows.append(f"| `{var}` | {desc} | {default} |")
    return "\n".join(rows)


def _ai_section() -> str:
    return (
        "## IA de Simarro\n\n"
        "Configuración por variables de entorno:\n\n"
        + _ai_table() + "\n\n"
        "```bash\n"
        "export FSORT_AI_KEY='sk-...'\n"
        'python3 fsort.py --ai "¿Cómo busco duplicados en ~/Descargas?"\n'
        'python3 fsort.py ai "¿Qué comando uso para vaciar subcarpetas?"\n'
        "```\n\n"
        "La IA responde en el idioma de la pregunta y propone comandos `fsort.py` reales.\n\n"
    )


def _ensure_ai_section(readme: str) -> str:
    """Garantiza que el README documente el modo IA y sus variables de entorno.

    No duplica los valores por defecto: los genera desde config.AI_ENV_VARS,
    de modo que cambiar el default en config/fsort se refleje al regenerar.
    """
    if "## IA de Simarro" in readme:
        return readme
    section = _ai_section()
    marker = "## Errores"
    if marker in readme:
        return readme.replace(marker, section + marker, 1)
    return readme + "\n" + section


if __name__ == "__main__":
    raise SystemExit(main())
