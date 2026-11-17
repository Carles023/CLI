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


def _ensure_ai_section(readme: str) -> str:
    """Garantiza que el README documente el modo IA y sus variables de entorno."""
    if "## IA de Simarro" in readme:
        return readme
    section = """## IA de Simarro

Configuración por variables de entorno:

| Variable | Descripción | Por defecto |
| --- | --- | --- |
| `FSORT_AI_KEY` | Clave de API (obligatoria) | — |
| `FSORT_AI_URL` | URL base de la API compatible con OpenAI | `https://ia.simarro/llmapi/v1` |
| `FSORT_AI_MODEL` | Modelo a usar | `Qwen38-DualSpark-medium` |
| `FSORT_AI_CA` | Ruta al certificado CA de Simarro | `~/.config/opencode/ca-simarro.crt` |
| `FSORT_AI_INSECURE` | `1` para desactivar la verificación TLS | desactivado |

```bash
export FSORT_AI_KEY='sk-...'
python3 fsort.py --ai "¿Cómo busco duplicados en ~/Descargas?"
python3 fsort.py ai "¿Qué comando uso para vaciar subcarpetas?"
```

La IA responde en el idioma de la pregunta y propone comandos `fsort.py` reales.

"""
    marker = "## Errores"
    if marker in readme:
        return readme.replace(marker, section + marker, 1)
    return readme + "\n" + section


if __name__ == "__main__":
    raise SystemExit(main())
