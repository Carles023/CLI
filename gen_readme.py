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
        else:
            usage += " <directorio>"
        rows.append(f"| `{name}` | {desc} | `{usage}` |")
    return "\n".join(rows)


def main() -> int:
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
        end = readme.index("\n\n", start)
    else:
        print(f"Error: el README debe contener {MARK_START}/{MARK_END} o la tabla generada.")
        return 1

    suffix = readme[end:]
    if suffix.startswith(MARK_END):
        suffix = suffix[len(MARK_END):]
    new_readme = readme[:start] + build_table(actions) + "\n\n" + suffix.lstrip("\n")

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print(f"README actualizado con {len(actions)} comando(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
