#!/usr/bin/env python3
"""Valida actions.json y reporta el campo exacto que falla."""
import json
import os
import re
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
ACTIONS_FILE = next(
    (p for p in (_PKG_DIR / "actions.json", _PKG_DIR.parent / "actions.json") if p.exists()),
    _PKG_DIR.parent / "actions.json",
)

VALID_TYPES = {"command", "python", "ai"}
PLACEHOLDER_RE = re.compile(r"\{(\d+)\}")

AI_SYSTEM_PROMPT = (
    "Eres el asistente de 'fsort', una CLI en Python para organizar archivos.\n"
    "Comandos REALES (usa SOLO estos; NO inventes nombres como sort, dup, big o move):\n"
    "  ordenar <dir>, ordenar-copiar <dir>, ordenar-recursivo <dir>, ordenar-auto <dir>\n"
    "  vaciar <dir> <destino>, vaciar-copiar <dir> <destino>\n"
    "  mover <elem...> <destino>, mover-copiar <elem...> <destino>\n"
    "  duplicados <dir>, duplicados-eliminar <dir>\n"
    "  mas-grandes <dir> [N], mas-grandes-eliminar <dir> [N]\n"
    "  mas-antiguos <dir> [N]  (top N más antiguos, por defecto 15)\n"
    "  por-edad <dir> [días]  (mover a la papelera los más antiguos de N días)\n"
    "  variantes: mas-antiguos-txt <dir> [N], por-edad-txt <dir> [días],\n"
    "    por-edad-eliminar <dir> [días] (borra sin papelera)\n"
    "  vaciar-papelera [papelera], vaciar-papelera-ya [papelera]\n"
    "  resumir <archivo> [destino.txt]\n"
    "  descomprimir-a <archivo> [destino]  (.zip/.tar/.tgz/...; rechaza zip-slip)\n"
    "  info <dir>, tamano <dir>, limpiar <dir>, limpiar-auto <dir>\n"
    "  reporte <dir> [N]  (resumen: tamaño, extensiones, duplicados, temporales)\n"
    "  deshacer-limpieza  (devuelve los archivos de la última 'limpiar')\n"
    "Opciones globales: --dry-run (-d) para simular, --actions para listar comandos,\n"
    "  --ai \"pregunta\" para consultar la IA.\n"
    "Responde SIEMPRE en el mismo idioma que la pregunta del usuario "
    "(valenciano, castellano o inglés).\n"
    "Sé breve y práctico: explica pasos y, si encaja, propón comandos "
    "'fsort.py <comando> [args...]' exactos de la lista.\n"
    "Si la pregunta no tiene relación con organizar archivos, indica que solo "
    "puedes ayudar con eso.\n"
)

SUMMARY_SYSTEM_PROMPT = (
    "Eres un asistente de resumen de documentos. Resume el texto que se te pasa "
    "de forma clara, fiel y sin añadir información que no esté en el original.\n"
    "Formato de la respuesta (usa exactamente estos encabezados):\n"
    "RESUMEN EJECUTIVO\n<1-3 frases con la idea principal>\n\n"
    "PUNTOS CLAVE\n- <punto>\n- <punto>...\n\n"
    "CONCLUSIONES\n<1-3 frases finales>\n\n"
    "Idioma: responde SIEMPRE en el mismo idioma que el texto de origen. "
    "No uses markdown ni comillas alrededor del texto.\n"
)

SUMMARY_MAX_CHARS = int(os.environ.get("FSORT_SUMMARY_MAX_CHARS", "12000"))

# Unica fuente de verdad para documentar las variables de entorno de la IA.
# Estos valores DEBEN coincidir con los defaults usados en fsort._ai_config() y
# fsort._ssl_context(); gen_readme.py los usa para generar la tabla del README,
# evitando duplicar defaults en dos sitios (riesgo de desincronizacion).
AI_ENV_VARS = [
    ["FSORT_AI_KEY", "Clave de API (obligatoria)", "—"],
    ["FSORT_AI_URL", "URL base de la API compatible con OpenAI",
     "`https://ia.simarro/llmapi/v1`"],
    ["FSORT_AI_MODEL", "Modelo a usar", "`Qwen38-DualSpark-medium`"],
    ["FSORT_AI_CA", "Ruta al certificado CA de Simarro",
     "`~/.config/opencode/ca-simarro.crt`"],
    ["FSORT_AI_INSECURE", "`1` para desactivar la verificación TLS", "desactivado"],
]


if __package__:
    from .errores import (
        ActionsFileInvalidError,
        ActionsFileNotFoundError,
        ActionsValidationError,
    )
else:
    from errores import (
        ActionsFileInvalidError,
        ActionsFileNotFoundError,
        ActionsValidationError,
    )


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

    action_type = action.get("type")

    if "type" not in action:
        errors.append(f"acciones.{name}.type: campo requerido (falta)")
    elif not isinstance(action_type, str):
        errors.append(f"acciones.{name}.type: debe ser texto, no '{type(action_type).__name__}'")
    elif action_type not in VALID_TYPES:
        errors.append(
            f"acciones.{name}.type: valor inválido '{action_type}' "
            f"(permitidos: {', '.join(sorted(VALID_TYPES))})"
        )

    if action_type == "python":
        if "func" not in action:
            errors.append(f"acciones.{name}.func: campo requerido cuando type es 'python' (falta)")
        elif not isinstance(action["func"], str) or not action["func"].strip():
            errors.append(f"acciones.{name}.func: debe ser un texto no vacío")

        kwargs = action.get("kwargs", {})
        if not isinstance(kwargs, dict):
            errors.append(f"acciones.{name}.kwargs: debe ser un objeto, no '{type(kwargs).__name__}'")

        unknown_keys = set(action) - {"description", "type", "func", "kwargs"}
    elif action_type == "ai":
        unknown_keys = set(action) - {"description", "type"}
    else:
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


def validate_func_exists(name: str, action: dict) -> list:
    """Comprueba que la función 'func' exista en fsort.py."""
    import importlib
    errors = []
    func_name = action.get("func")
    if not isinstance(func_name, str) or not func_name.strip():
        return errors
    fsort_name = __package__ + ".fsort" if __package__ else "fsort"
    try:
        fsort = importlib.import_module(fsort_name)
    except ImportError as e:
        return [f"acciones.{name}.func: no se pudo importar fsort.py ({e})"]
    if not callable(getattr(fsort, func_name, None)):
        errors.append(f"acciones.{name}.func: la función '{func_name}' no existe en fsort.py")
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
            if action.get("type") == "python" and not getattr(validate, "_skip_funcs", False):
                errors.extend(validate_func_exists(name, action))

    return errors


def load_and_validate(path: Path = ACTIONS_FILE) -> dict:
    """Carga el JSON, lo valida (incluidas las funciones) y devuelve las acciones. Lanza una excepción si es inválido."""
    if not path.exists():
        if path == ACTIONS_FILE:
            return {}
        raise ActionsFileNotFoundError(
            f"{path} (si esperabas usar el actions.json por defecto, omite --actions-file)")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ActionsFileNotFoundError(str(path))
    except json.JSONDecodeError as e:
        raise ActionsFileInvalidError(f"{path} (línea {e.lineno}, columna {e.colno}): {e.msg}")

    errors = validate(data)
    if errors:
        raise ActionsValidationError([f"{path}: {err}" for err in errors])

    return data.get("actions", {})


def check_actions(actions: dict) -> list:
    """Revalida el mapeo de acciones ya cargado y devuelve los errores encontrados (sin volver a leer el archivo)."""
    return validate({"actions": actions})


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
        try:
            raise ActionsValidationError(errors)
        except ActionsValidationError as e:
            print(f"✗ {path}: {e.detail}:")
            for err in e.errors:
                print(f"  - {err}")
            return 1

    print(f"✓ {path}: válido ({len(data.get('actions', {}))} acción(es)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
