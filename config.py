#!/usr/bin/env python3
"""Valida actions.json y reporta el campo exacto que falla."""
import json
import re
import sys
from pathlib import Path

ACTIONS_FILE = Path(__file__).parent / "actions.json"

VALID_TYPES = {"command"}
PLACEHOLDER_RE = re.compile(r"\{(\d+)\}")


def validate_action(name: str, action: object) -> list:
    """Valida una acción individual y devuelve los errores encontrados."""
    errors = []

    if not isinstance(action, dict):
        errors.append(f"acciones.{name}: debe ser un objeto, no '{type(action).__name__}'")
        return errors

    if "description" not in action:
        errors.append(f"acciones.{name}.description: campo requerido (falta)")
    elif not isinstance(action["description"], str):
        errors.append(
            f"acciones.{name}.description: debe ser texto, "
            f"no '{type(action['description']).__name__}'"
        )

    if "type" not in action:
        errors.append(f"acciones.{name}.type: campo requerido (falta)")
    elif not isinstance(action["type"], str):
        errors.append(f"acciones.{name}.type: debe ser texto, no '{type(action['type']).__name__}'")
    elif action["type"] not in VALID_TYPES:
        errors.append(
            f"acciones.{name}.type: valor inválido '{action['type']}' "
            f"(permitidos: {', '.join(sorted(VALID_TYPES))})"
        )

    if "command" not in action:
        errors.append(f"acciones.{name}.command: campo requerido (falta)")
    elif not isinstance(action["command"], str):
        errors.append(f"acciones.{name}.command: debe ser texto, no '{type(action['command']).__name__}'")
    elif not action["command"].strip():
        errors.append(f"acciones.{name}.command: no puede estar vacío")

    unknown_keys = set(action) - {"description", "type", "command"}
    for key in sorted(unknown_keys):
        errors.append(f"acciones.{name}.{key}: campo no reconocido")

    return errors


def validate_placeholders(name: str, action: dict) -> list:
    """Comprueba que los marcadores {n} del comando sean consecutivos desde {1}."""
    errors = []
    command = action.get("command")
    if not isinstance(command, str):
        return errors

    used = {int(n) for n in PLACEHOLDER_RE.findall(command)}
    if used and used != set(range(1, max(used) + 1)):
        missing = sorted(set(range(1, max(used) + 1)) - used)
        errors.append(
            f"acciones.{name}.command: los marcadores deben ser consecutivos desde {{1}}; "
            f"faltan {', '.join('{%d}' % m for m in missing)}"
        )
    return errors


def validate(data: object) -> list:
    """Valida la estructura completa del JSON y devuelve todos los errores."""
    errors = []

    if not isinstance(data, dict):
        return [f"raíz: el archivo debe contener un objeto JSON, no '{type(data).__name__}'"]

    if "actions" not in data:
        return ["acciones: campo requerido (falta la clave 'actions')"]

    actions = data["actions"]
    if not isinstance(actions, dict):
        errors.append(f"acciones: debe ser un objeto, no '{type(actions).__name__}'")
        return errors

    if not actions:
        errors.append("acciones: no puede estar vacío")

    for name, action in actions.items():
        if not isinstance(name, str) or not name.strip():
            errors.append(f"acciones.{name!r}: el nombre de la acción debe ser un texto no vacío")
        errors.extend(validate_action(name, action))
        if isinstance(action, dict):
            errors.extend(validate_placeholders(name, action))

    return errors


def load_and_validate(path: Path = ACTIONS_FILE) -> dict:
    """Carga el JSON, lo valida y devuelve las acciones. Lanza SystemExit si es inválido."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: no se encuentra el archivo {path}.")
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        print(f"Error: JSON inválido en {path} (línea {e.lineno}, columna {e.colno}): {e.msg}")
        raise SystemExit(1)

    errors = validate(data)
    if errors:
        print(f"Error: validación fallida en {path} ({len(errors)} error(es)):")
        for err in errors:
            print(f"  - {err}")
        raise SystemExit(1)

    return data.get("actions", {})


def main() -> int:
    path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else ACTIONS_FILE
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"✗ No se encuentra el archivo {path}.")
        return 1
    except json.JSONDecodeError as e:
        print(f"✗ JSON inválido en {path} (línea {e.lineno}, columna {e.colno}): {e.msg}")
        return 1

    errors = validate(data)
    if errors:
        print(f"✗ {path}: {len(errors)} error(es) de validación:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"✓ {path}: válido ({len(data.get('actions', {}))} acción(es)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
