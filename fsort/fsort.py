#!/usr/bin/env python3
import argparse
import glob
import hashlib
import json as jsonlib
import os
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

_IMPORT_ERRS = {
    "ActionCommandMissingError", "ActionFuncMissingError", "ActionFuncNotFoundError",
    "ActionNotExecutableError", "AIError", "DestinationNotFoundError",
    "DirectoryNotFoundError", "FileReadError", "FsortError", "InvalidActionError",
    "InvalidArgumentError", "NotADirectoryError_", "OperationError",
    "UnsupportedFileFormatError",
}
if __package__:
    from . import config as _config
    from . import errores as _errores
else:
    import config as _config
    import errores as _errores

ACTIONS_FILE = _config.ACTIONS_FILE
AI_SYSTEM_PROMPT = _config.AI_SYSTEM_PROMPT
SUMMARY_MAX_CHARS = _config.SUMMARY_MAX_CHARS
SUMMARY_SYSTEM_PROMPT = _config.SUMMARY_SYSTEM_PROMPT
ActionsValidationError = _config.ActionsValidationError
load_and_validate = _config.load_and_validate

_g = globals()
for _n in _IMPORT_ERRS:
    _g[_n] = getattr(_errores, _n)
del _n


# --- Coloreado de salida (ANSI) -------------------------------------------------
_COLORS_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR") \
    and os.environ.get("TERM", "") != "dumb"

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"

# Palabras clave iniciales -> color (se evaluan en orden; la primera que encaja gana)
_KEYWORD_COLORS = (
    ("✗ Error", _RED + _BOLD),
    ("✗", _RED + _BOLD),
    ("✓", _GREEN + _BOLD),
    ("Error", _RED),
    ("Eliminado", _RED),
    ("Eliminada", _RED),
    ("NO vaciada", _YELLOW),
    ("Papelera NO", _YELLOW),
    ("Movido", _GREEN),
    ("Copiado", _GREEN),
    ("Conservar", _CYAN),
    ("Omitido", _DIM),
    ("Duplicado", _DIM),
    ("Completado", _GREEN + _BOLD),
    ("Papelera vaciada", _GREEN + _BOLD),
    ("Encontrados", _CYAN + _BOLD),
    ("Sugerencia", _DIM),
    ("Ejemplo", _DIM),
)

_PREFIX_COLORS = (
    ("[DRY-RUN]", _YELLOW + _BOLD),
    ("Simulación", _YELLOW),
)


def _c(text: str, color: str) -> str:
    """Rodea el texto con el color ANSI indicado si el coloreado está activo."""
    if not _COLORS_ENABLED or not color:
        return text
    return f"{color}{text}{_RESET}"


def _colorize_line(line: str) -> str:
    """Aplica color a una linea segun su prefijo/palabra clave inicial."""
    if not _COLORS_ENABLED:
        return line
    stripped = line.lstrip()
    indent = line[:len(line) - len(stripped)]
    for kw, col in _PREFIX_COLORS:
        if stripped.startswith(kw):
            rest = stripped[len(kw):]
            return indent + _c(kw, col) + rest
    for kw, col in _KEYWORD_COLORS:
        if stripped.startswith(kw):
            return indent + _c(stripped, col)
    return line


def cprint(*args, sep=" ", end="\n", file=None, **kwargs):
    """print() con color: colorea la primera linea segun su palabra clave inicial."""
    text = sep.join(str(a) for a in args)
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln:
            lines[i] = _colorize_line(ln)
            break
    print("\n".join(lines), end=end, file=file, **kwargs)


def _confirm(prompt: str = "Confirmar? [s/N] ", default_no: bool = True) -> bool:
    """Pide confirmacion en un terminal interactivo.

    - Sin TTY (stdin o /dev/tty no disponibles, p. ej. pipeado): avisa y devuelve
      False (medida de seguridad: nunca borra a traicion).
    - Con variable de entorno FSORT_YES=1 (o --yes via kwargs): no pregunta, confirma.
    - Escribe el prompt a /dev/tty (si existe) para que se vea aunque el stdout
      este redirigido, y lee la respuesta de stdin.
    Devuelve True solo con 's'/'si'/'yes'/'y' (o confirmacion automatica).
    """
    if os.environ.get("FSORT_YES") == "1":
        return True
    if not sys.stdin.isatty():
        cprint("  (sin TTY: no se puede confirmar; omitido. Usa FSORT_YES=1 o --yes)")
        return False
    try:
        fd = os.open("/dev/tty", os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as tty:
            tty.write(prompt)
            tty.flush()
    except OSError:
        cprint(prompt, end="", flush=True)
    try:
        ans = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("s", "si", "sí", "yes", "y")


def _suggest(text: str) -> str:
    """Añade una pista de solución al mensaje cuando aplica."""
    lowered = text.lower()
    if "no es un directorio" in lowered:
        return " La ruta indicada es un archivo; necesitas una carpeta (usa por ejemplo 'dirname <ruta>')."
    if "destino no existe" in lowered:
        return " Crea el directorio de destino o indica una ruta existente."
    if "no existe" in lowered and "directorio" in lowered:
        return " Comprueba la ruta; si el directorio aún no existe, créalo antes."
    if "no existe" in lowered and "destino" in lowered:
        return " Crea el directorio de destino o indica una ruta existente."
    if "debe ser un entero" in lowered or "debe ser mayor que 0" in lowered:
        return " Pasa un número entero mayor que cero (ej: '5')."
    if "falta el directorio" in lowered:
        return " Indica el directorio como argumento (ej: 'fsort.py ordenar <directorio>')."
    if "falta el destino" in lowered:
        return " Añade el destino como segundo argumento (ej: 'fsort.py vaciar <origen> <destino>')."
    if "al menos un elemento" in lowered:
        return " Indica al menos un elemento y un directorio destino."
    return ""


def load_actions(path: Path = ACTIONS_FILE) -> dict:
    """Carga y valida (estructura y funciones) las acciones definidas en actions.json."""
    return load_and_validate(path)


def _checked_dir(arg, action_name: str) -> Path:
    """Convierte el argumento en Path (con ~ resuelto) y comprueba que exista con la ruta indicada."""
    if arg is None:
        raise InvalidArgumentError(
            f"'{action_name}': falta el directorio (fsort.py {action_name} <directorio>)")
    p = Path(arg).expanduser()
    if not p.exists():
        raise DirectoryNotFoundError(str(p))
    return p.resolve()


def run_action(name: str, action: dict, args: list, dry_run: bool = False):
    """Ejecuta una acción definida en el JSON. Soporta tipos 'command' y 'python'."""
    if not isinstance(action, dict):
        raise InvalidActionError(
            f"la acción '{name}' debe ser un objeto, no '{type(action).__name__}'")

    action_type = action.get("type")

    if action_type == "python":
        run_python_action(name, action, args, dry_run)
        return

    if action_type == "ai":
        run_ai_action(name, action, args, dry_run)
        return

    if action_type != "command":
        raise ActionNotExecutableError(
            f"el tipo '{action_type}' de la acción '{name}' no está soportado "
            "(válidos: 'command', 'python', 'ai')")

    command = action.get("command")
    if not command:
        raise ActionCommandMissingError(
            f"la acción '{name}' (tipo 'command') no define el campo 'command'")

    plantilla = command

    placeholders = {int(n) for n in re.findall(r"\{(\d+)\}", command)}
    if placeholders and len(args) < max(placeholders):
        faltan = sorted(set(range(1, max(placeholders) + 1)) - set(range(1, len(args) + 1)))
        raise InvalidArgumentError(
            f"'{name}': la acción usa los marcadores "
            f"{', '.join('{%d}' % p for p in sorted(placeholders))} "
            f"pero faltan argumentos (faltan {{{faltan[0]}}}..{{{faltan[-1]}}})"
            if faltan else
            f"'{name}': la acción usa los marcadores "
            f"{', '.join('{%d}' % p for p in sorted(placeholders))} "
            f"pero solo se recibieron {len(args)} argumento(s)")

    # Sustituir {1}, {2}, ... por los argumentos del usuario de forma segura:
    # se tokeniza la plantilla y cada argumento entra como un unico token
    # citado (shlex.quote), de modo que rutas con espacios o caracteres
    # especiales (;, |, $, backticks...) no pueden inyectar ordenes de shell.
    if os.name == "nt":
        # En Windows se ejecuta con shell=True: cita al estilo cmd para
        # evitar al menos el vector mas evidente (comas, & y pipes).
        def _cita(a: str) -> str:
            return '"' + a.replace('"', '""') + '"' if any(c in a for c in ' "&|<>^%') else a

        for i, arg in enumerate(args, 1):
            command = command.replace(f"{{{i}}}", _cita(arg))
        argv = command
    else:
        try:
            tokens = shlex.split(plantilla)
        except ValueError as e:
            raise InvalidArgumentError(
                f"'{name}': la plantilla de la accion es un comando no válido ({e})")

        argv = []
        for tok in tokens:
            if "{" not in tok:
                argv.append(tok)
                continue
            partes = []
            i = 0
            while i < len(tok):
                if tok[i] == "{":
                    m = re.match(r"\{(\d+)\}", tok[i:])
                    if m and 1 <= int(m.group(1)) <= len(args):
                        partes.append(shlex.quote(args[int(m.group(1)) - 1]))
                        i += m.end()
                        continue
                j = tok.find("{", i + 1)
                fin = len(tok) if j == -1 else j
                partes.append(shlex.quote(tok[i:fin]))
                i = fin
            argv.extend(shlex.split(" ".join(partes)))
        command = " ".join(shlex.quote(a) for a in argv)

    if dry_run:
        cprint(f"[DRY-RUN] Ejecutaría: {command}")
        _dry_run_command(command, name=name, action_args=args)
        return

    try:
        if os.name == "nt":
            result = subprocess.run(argv, shell=True)
        else:
            try:
                result = subprocess.run(argv)
            except FileNotFoundError:
                raise ActionNotExecutableError(
                    f"el programa '{argv[0]}' definido por la acción '{name}' "
                    "no está instalado o no está en el PATH")
        sys.exit(result.returncode)
    except PermissionError:
        raise ActionNotExecutableError(
            f"sin permisos para ejecutar '{argv[0]}' (acción '{name}')")
    except OSError as e:
        raise OperationError(f"no se pudo ejecutar '{command}': {e}")


def run_ai_action(name: str, action: dict, args: list, dry_run: bool = False):
    """Acción de tipo 'ai': pregunta a la IA de Simarro y muestra la respuesta."""
    question = " ".join(args).strip()

    if dry_run:
        cprint(f"[DRY-RUN] Consultaría la IA de Simarro con la pregunta: "
              f"'{question or '(interactiva)'}'")
        return

    if not question:
        raise InvalidArgumentError(
            f"'{name}': falta la pregunta "
            f"(fsort.py {name} \"tu pregunta\" o fsort.py --ai \"tu pregunta\")")

    cprint(f"Consultando la IA de Simarro ({_ai_config()['model']})...\n")
    cprint(ask_ai(question))
    cprint()


destructive_commands = ("mv", "rm", "cp", "mkdir", "rmdir", "touch", "truncate",
                        "dd", "tee", "ln", "rsync")



def _dry_run_command(command: str, name: str = "", action_args: list = None):
    """Simula un comando 'type: command' listando lo que tocaría, sin ejecutar nada.

    Para la acción 'limpiar' previsualiza los archivos temporales que se moverían.
    Analiza pipes, '&&' o ';' y muestra los ficheros reales que afectan los
    comandos destructivos (mv, rm, cp, ...) sin alterarlos.
    """
    # Previsualización específica de 'limpiar': lista .tmp/.bak del directorio {1}
    if name == "limpiar" and action_args:
        directory = Path(action_args[0]).expanduser()
        trash = os.environ.get("FSORT_TRASH_DIR", "./trash")
        if not directory.is_dir():
            cprint(f"  [DRY-RUN] el directorio no existe: {directory}")
            return
        matches = sorted(
            [f for f in directory.glob("*") if f.is_file() and f.suffix in (".tmp", ".bak")])
        if not matches:
            cprint(f"  [DRY-RUN] nada que limpiar en {directory} (no hay .tmp ni .bak)")
        else:
            cprint(f"  [DRY-RUN] movería a la papelera ({trash}):")
            for f in matches:
                cprint(f"    - {f}")
            cprint(f"  [DRY-RUN] pediría confirmación interactiva antes de mover.")
        return

    try:
        segments = shlex.split(command)
    except ValueError:
        cprint("  (no se pudo analizar el comando; omite la simulación detallada)")
        return

    # Dividir en segmentos por operadores de shell básicos
    groups, current = [], []
    i = 0
    while i < len(segments):
        tok = segments[i]
        if tok in ("&&", "||", ";", "|"):
            if current:
                groups.append(current)
                current = []
            i += 1
            continue
        current.append(tok)
        i += 1
    if current:
        groups.append(current)

    any_destructive = False
    for group in groups:
        if not group:
            continue
        program = Path(group[0]).name
        if program not in destructive_commands:
            continue
        any_destructive = True
        paths = [a for a in group[1:] if not a.startswith("-")]
        expanded = []
        for a in paths:
            if any(c in a for c in "*?["):
                if os.path.isabs(a):
                    base, pattern = "/", a.lstrip("/")
                else:
                    base, pattern = ".", a
                matched = sorted(
                    os.path.join(base, m) for m in glob.glob(pattern, root_dir=base))
                expanded.extend(matched or [a])
            else:
                expanded.append(a)
        if program in ("mv", "cp", "rsync"):
            if len(expanded) >= 2:
                dest = expanded[-1]
                for src in expanded[:-1]:
                    verb = "movería" if program == "mv" else "copiaría"
                    cprint(f"  [DRY-RUN] {verb}: {src} -> {dest}")
            else:
                cprint(f"  [DRY-RUN] {program} {' '.join(expanded)}")
        elif program in ("rm", "rmdir"):
            for p in expanded:
                cprint(f"  [DRY-RUN] eliminaría: {p}")
        else:
            cprint(f"  [DRY-RUN] {program} {' '.join(expanded)}")

    if not any_destructive:
        cprint("  (el comando no parece modificar archivos; no hay nada que simular)")


def run_python_action(name: str, action: dict, args: list, dry_run: bool = False):
    """Ejecuta una acción de tipo 'python' llamando a la función indicada en 'func'."""
    func_name = action.get("func")
    if not func_name:
        raise ActionFuncMissingError(
            f"la acción '{name}' (tipo 'python') no define el campo 'func'")

    module = sys.modules[__name__]
    func = getattr(module, func_name, None)
    if not callable(func):
        raise ActionFuncNotFoundError(
            f"la función '{func_name}' de la acción '{name}' no existe en fsort.py")

    kwargs = dict(action.get("kwargs") or {})
    kwargs["dry_run"] = dry_run

    if func is move_items:
        if len(args) < 2:
            raise InvalidArgumentError(
                f"'{name}': se necesitan al menos un elemento y un directorio destino")
        items = args[:-1]
        raw_dest = Path(args[-1]).expanduser()
        if not raw_dest.exists():
            raise DestinationNotFoundError(str(raw_dest))
        dest = raw_dest.resolve()
        func(items, dest, **kwargs)
    elif func is empty_trash:
        directory = Path(args[0]).expanduser() if args else None
        func(directory, **kwargs)
    elif func is summarize_file:
        if not args:
            raise InvalidArgumentError(
                f"'{name}': falta el archivo (fsort.py {name} <archivo> [destino.txt])")
        path = Path(args[0]).expanduser()
        output = Path(args[1]).expanduser() if len(args) > 1 else None
        func(path, output, **kwargs)
    elif func in (largest_files, oldest_files, aged_files):
        argname = "días" if func is aged_files else "top"
        if not args:
            raise InvalidArgumentError(
                f"'{name}': falta el directorio (fsort.py {name} <directorio> [{argname}])")
        directory = _checked_dir(args[0], name)
        if len(args) > 1:
            kwargs["top" if func is oldest_files else
                           ("days" if func is aged_files else "top")] = args[1]
        if func is aged_files:
            kwargs["assume_yes"] = (os.environ.get("FSORT_YES") == "1")
        func(directory, **kwargs)
    elif func is sync_dirs:
        if not args:
            raise InvalidArgumentError(
                f"'{name}': falta el origen (fsort.py {name} <origen> [destino])")
        origen = _checked_dir(args[0], name)
        if args[1:2] and args[1] in ("--destino", "-o"):
            if len(args) < 3:
                raise InvalidArgumentError(f"'{name}': falta la ruta tras --destino")
            destino = Path(args[2]).expanduser()
        elif len(args) > 1:
            destino = Path(args[1]).expanduser()
        else:
            destino = None
        kwargs["assume_yes"] = (os.environ.get("FSORT_YES") == "1")
        func(origen, destino, **kwargs)
    elif func is extract_archive:
        if not args:
            raise InvalidArgumentError(
                f"'{name}': falta el archivo (fsort.py {name} <archivo> [destino])")
        archivo = Path(args[0]).expanduser()
        destino = Path(args[1]).expanduser() if len(args) > 1 else None
        func(archivo, destino, **kwargs)
    elif func is undo_clean:
        trash_arg = Path(args[0]).expanduser() if args else None
        kwargs["assume_yes"] = (os.environ.get("FSORT_YES") == "1")
        func(trash_arg, **kwargs)
    elif func in (dir_snapshot, snapshot_diff):
        if not args:
            raise InvalidArgumentError(
                f"'{name}': falta el directorio "
                f"(fsort.py {name} <directorio> [nombre])")
        directory = _checked_dir(args[0], name)
        if len(args) > 1:
            kwargs["name"] = args[1]
        if func is snapshot_diff:
            kwargs["latest"] = ("--latest" in args[2:] or "-L" in args[2:])
        func(directory, **kwargs)
    elif func is snapshot_list:
        directory = _checked_dir(args[0], name) if args else None
        func(directory, **kwargs)
    elif func is clean_temp:
        if not args:
            raise InvalidArgumentError(
                f"'{name}': falta el directorio (fsort.py {name} <directorio>)")
        directory = _checked_dir(args[0], name)
        kwargs["assume_yes"] = (os.environ.get("FSORT_YES") == "1")
        func(directory, **kwargs)
    else:
        directory = _checked_dir(args[0] if args else None, name)
        if func is flatten_dir:
            if len(args) < 2:
                raise InvalidArgumentError(
                    f"'{name}': falta el destino "
                    f"(fsort.py {name} <directorio> <destino>)")
            raw_dest = Path(args[1]).expanduser()
            if not raw_dest.exists():
                raise DestinationNotFoundError(str(raw_dest))
            dest = raw_dest.resolve()
            func(directory, dest, **kwargs)
        else:
            func(directory, **kwargs)


# Categorias humanas para 'ordenar-auto': cada grupo define carpeta y extensiones.
FUNC_GROUPS = (
    ("imagenes", (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp",
                  ".heic", ".heif", ".svg", ".ico", ".cr2", ".nef", ".arw", ".raw",
                  ".psd", ".xcf")),
    ("documentos", (".doc", ".docx", ".odt", ".rtf", ".pages", ".key", ".ppt",
                    ".pptx", ".odp", ".xls", ".xlsx", ".ods", ".csv", ".tsv", ".txt",
                    ".md", ".markdown", ".rst", ".tex", ".org", ".epub", ".mobi",
                    ".azw3", ".djvu")),
    ("pdfs", (".pdf",)),
    ("musica", (".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga", ".opus", ".m4a",
                ".wma", ".aiff", ".aif", ".mid", ".midi", ".mka")),
    ("video", (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
               ".mpg", ".mpeg", ".3gp", ".ts", ".ogv")),
    ("archives", (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst",
                  ".tgz", ".tbz2", ".txz", ".lz4", ".iso")),
    ("programas", (".exe", ".msi", ".apk", ".deb", ".rpm", ".AppImage", ".jar",
                   ".bin")),
    ("codigo", (".py", ".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h", ".hpp",
                ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".swift",
                ".sh", ".bash", ".zsh", ".sql", ".html", ".htm", ".css", ".scss",
                ".less", ".xml", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg",
                ".conf", ".env", ".ipynb", ".r", ".lua", ".pl")),
    ("fuentes", (".ttf", ".otf", ".woff", ".woff2")),
)


def _folder_for(ext: str, mode: str = "ext") -> str:
    """Carpeta destino de una extension: 'ext' => la propia extension;
    'human' => categoria legible (imagenes/, musica/...) o 'otros' si no encaja."""
    if not ext:
        return "sin_extension"
    if mode != "human":
        return ext[1:]
    for name, exts in FUNC_GROUPS:
        if ext in exts:
            return name
    return "otros"


def _dest_for(file_path: Path, dest_folder: Path, mode: str) -> Path:
    """Ruta destino aplicando sufijos _1.. para no sobrescribir en modo humano."""
    dest_file = dest_folder / file_path.name
    if mode != "human" or not dest_file.exists():
        return dest_file
    counter = 1
    while dest_file.exists():
        dest_file = dest_folder / f"{file_path.stem}_{counter}{file_path.suffix}"
        counter += 1
    return dest_file


def _move_no_overwrite(src: Path, dst: Path) -> Path:
    """Mueve src a dst sin sobrescribir. Ni shutil.move ni os.rename/os.replace
    dan esa garantia (ambos pisan el archivo de destino), asi que si dst existe
    se reubica en dst_<n>. Para archivos usa hardlink+unlink (sin copia de
    contenido) con fallback a copy2; para directorios, shutil.move.
    Devuelve la ruta final."""
    def exists_file(p: Path) -> bool:
        try:
            return os.path.isfile(str(p))
        except OSError:
            return False

    def unique(base: Path) -> Path:
        if not base.exists():
            return base
        counter = 1
        cand = base.with_name(f"{base.stem}_{counter}{base.suffix}")
        while cand.exists():
            counter += 1
            cand = base.with_name(f"{base.stem}_{counter}{base.suffix}")
        return cand

    if not exists_file(dst):
        if not dst.is_dir():
            try:
                os.rename(str(src), str(dst))
                return dst
            except OSError:
                pass
        else:
            dest = unique(dst / Path(str(src)).name)
            shutil.move(str(src), str(dest))
            return dest

    final = unique(dst)
    try:
        os.link(str(src), str(final))
        os.unlink(str(src))
    except OSError:
        shutil.copy2(str(src), str(final))
        os.remove(str(src))
    return final


def sort_files(directory: Path, dry_run: bool = False, copy: bool = False, recursive: bool = False,
               folder_mode: str = "ext"):
    """
    Ordena archivos en un directorio por su extensión.
    Crea una carpeta por extensión y mueve/copia los archivos.
    Con folder_mode='human' agrupa en carpetas legibles (imagenes/,
    documentos/, pdfs/, musica/, ...); con sufijos _1, _2 si hay colision
    de nombre.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))

    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))
    
    # Obtener archivos (solo archivos, no directorios)
    if recursive:
        files = [f for f in directory.rglob("*") if f.is_file()]
    else:
        files = [f for f in directory.iterdir() if f.is_file()]
    
    # Excluir el propio script si está en el directorio
    script_name = Path(__file__).name
    files = [f for f in files if f.name != script_name and f.name != "fsort.py"]
    
    if not files:
        cprint("No hay archivos para ordenar.")
        return
    
    moved_count = 0
    for file_path in files:
        # Obtener extensión
        extension = file_path.suffix.lower()
        ext_folder = _folder_for(extension, folder_mode)

        # Crear carpeta destino: en modo recursivo se consolida todo en <raiz>/<carpeta>/
        dest_folder = directory / ext_folder

        # Evitar mover un archivo que ya esta en su carpeta destino
        if file_path.parent == dest_folder:
            continue

        # En recursivo, saltar archivos que ya cuelgan de <raiz>/<carpeta>/ (ya consolidados
        # en una pasada anterior o de un 'ordenar' previo): evita re-mover y bucles.
        if recursive:
            try:
                file_path.relative_to(dest_folder)
                continue
            except ValueError:
                pass

        dest_file = _dest_for(file_path, dest_folder, folder_mode)
        if not dry_run and not dest_file.parent.exists():
            dest_folder.mkdir(parents=True, exist_ok=True)

        if dry_run:
            action = "Copiaría" if copy else "Movería"
            cprint(f"[DRY-RUN] {action}: {file_path} -> {dest_file}")
            continue

        try:
            if copy:
                shutil.copy2(file_path, dest_file)
                cprint(f"Copiado: {file_path.name} -> {ext_folder}/")
            else:
                final = _move_no_overwrite(file_path, dest_file)
                cprint(f"Movido: {file_path.name} -> {ext_folder}/")
                del final
            moved_count += 1
        except Exception as e:
            raise OperationError(f"{file_path}: {e}")
    
    if not dry_run:
        action = "copiados" if copy else "movidos"
        cprint(f"\nCompletado: {moved_count} archivo(s) {action}.")
    else:
        cprint("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")


def flatten_dir(directory: Path, dest: Path, dry_run: bool = False, copy: bool = False, remove_empty: bool = True):
    """
    Vacía las subcarpetas de un directorio moviendo (o copiando) sus archivos
    a un directorio destino.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))

    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    dest.mkdir(parents=True, exist_ok=True)

    subdirs = [d for d in directory.iterdir() if d.is_dir()]
    if not subdirs:
        cprint("No hay subcarpetas que vaciar.")
        return

    moved_count = 0
    for subdir in subdirs:
        for file_path in subdir.rglob("*"):
            if not file_path.is_file():
                continue

            dest_file = dest / file_path.name

            if file_path.parent == dest:
                continue

            if dry_run:
                action = "Copiaría" if copy else "Movería"
                cprint(f"[DRY-RUN] {action}: {file_path} -> {dest_file}")
                continue

            # Manejar colisiones de nombre
            counter = 1
            original_dest = dest_file
            while dest_file.exists():
                stem = original_dest.stem
                suffix = original_dest.suffix
                dest_file = dest / f"{stem}_{counter}{suffix}"
                counter += 1

            try:
                if copy:
                    shutil.copy2(file_path, dest_file)
                    cprint(f"Copiado: {file_path.relative_to(directory)} -> {dest_file.name}")
                else:
                    shutil.move(str(file_path), str(dest_file))
                    cprint(f"Movido: {file_path.relative_to(directory)} -> {dest_file.name}")
                moved_count += 1
            except Exception as e:
                raise OperationError(f"{file_path}: {e}")

    if dry_run:
        cprint("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")
        return

    if remove_empty and not copy:
        for subdir in sorted(subdirs, key=lambda d: len(d.parts), reverse=True):
            leftovers = [f for f in subdir.rglob("*") if f.is_file()]
            if not leftovers:
                try:
                    shutil.rmtree(subdir)
                    cprint(f"Eliminada carpeta vacía: {subdir.relative_to(directory)}/")
                except Exception as e:
                    raise OperationError(f"no se pudo eliminar {subdir}: {e}")

    cprint(f"\nCompletado: {moved_count} archivo(s) {'copiados' if copy else 'movidos'}.")


def move_items(items: list, dest: Path, dry_run: bool = False, copy: bool = False):
    """
    Mueve (o copia) una lista de archivos o carpetas a un directorio destino.
    """
    if not dest.exists():
        raise DestinationNotFoundError(str(dest))

    if not dest.is_dir():
        raise NotADirectoryError_(str(dest))

    moved_count = 0
    for item in items:
        path = Path(item).expanduser()
        if not path.exists():
            cprint(f"Error: {path} no existe.")
            continue

        resolved_item = path.resolve()
        if resolved_item == dest.resolve():
            cprint(f"Omitido: {path.name} ya está en el destino.")
            continue
        if resolved_item.parent == dest.resolve():
            cprint(f"Omitido: {path.name} ya está en el destino.")
            continue

        dest_file = dest / path.name

        if dry_run:
            action = "Copiaría" if copy else "Movería"
            cprint(f"[DRY-RUN] {action}: {path} -> {dest_file}")
            continue

        # Manejar colisiones de nombre
        counter = 1
        original_dest = dest_file
        while dest_file.exists():
            if path.is_dir():
                dest_file = dest / f"{original_dest.name}_{counter}"
            else:
                dest_file = dest / f"{original_dest.stem}_{counter}{original_dest.suffix}"
            counter += 1

        try:
            if copy:
                if path.is_dir():
                    shutil.copytree(path, dest_file)
                else:
                    shutil.copy2(path, dest_file)
                cprint(f"Copiado: {path.name} -> {dest}/")
            else:
                shutil.move(str(path), str(dest_file))
                cprint(f"Movido: {path.name} -> {dest}/")
            moved_count += 1
        except Exception as e:
            raise OperationError(f"{path}: {e}")

    if dry_run:
        cprint("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")
    else:
        cprint(f"\nCompletado: {moved_count} elemento(s) {'copiados' if copy else 'movidos'}.")


def _human_size(num: float) -> str:
    """Formatea un número de bytes a una unidad legible."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} PB"


def find_duplicates(directory: Path, dry_run: bool = False, delete: bool = False,
                    interactive: bool = False, recursive: bool = True, min_size: int = 1,
                    quiet: bool = False):
    """
    Detecta archivos duplicados (mismo contenido) comparando primero el tamaño y
    luego el hash SHA-256. Agrupa los duplicados y muestra cuáles conservar.
    Con 'delete=True' elimina los redundantes (conserva el más antiguo).
    Con 'interactive=True' permite elegir qué copia conservar en cada grupo.
    Con 'quiet=True' no imprime detalle por grupo; devuelve
    {'groups': n, 'wasted': bytes} para reutilizar el resultado (usa 'reporte').
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))

    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    # Excluir el propio script si está en el directorio
    script_name = Path(__file__).name
    if recursive:
        files = [f for f in directory.rglob("*") if f.is_file()]
    else:
        files = [f for f in directory.iterdir() if f.is_file()]
    files = [f for f in files if f.name != script_name and f.name != "fsort.py"]

    # Paso 1: agrupar por tamaño (descarta comparaciones de hash costosas)
    by_size: dict = {}
    for file_path in files:
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size < min_size:
            continue
        by_size.setdefault(size, []).append(file_path)

    # Paso 2: calcular hash solo a los tamaños con más de un candidato
    by_hash: dict = {}
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue
        for file_path in candidates:
            digest = _sha256(file_path)
            if digest is None:
                continue
            by_hash.setdefault((size, digest), []).append(file_path)

    groups = [paths for paths in by_hash.values() if len(paths) > 1]

    if not groups:
        if not quiet:
            cprint("No se encontraron archivos duplicados.")
        return {"groups": 0, "wasted": 0}

    groups.sort(key=lambda paths: paths[0].stat().st_size * (len(paths) - 1), reverse=True)

    interactive = bool(interactive)
    total_groups = len(groups)
    wasted = 0
    deleted_count = 0
    # Sin TTY (p. ej. entrada pipeada) no se puede preguntar: se actúa en lote
    interactive = interactive and not dry_run and sys.stdin.isatty()

    for idx, paths in enumerate(groups, 1):
        size = paths[0].stat().st_size
        paths_sorted = sorted(paths, key=lambda p: p.stat().st_mtime)

        if not quiet:
            cprint(f"[{idx}/{total_groups}] {_human_size(size)} c/u — {len(paths_sorted)} copias:")

        if interactive:
            cprint("  Elige qué copia conservar:")
            for n, p in enumerate(paths_sorted, 1):
                cprint(f"    {n}) {p}")
            while True:
                try:
                    raw = input(f"  Opción [1-{len(paths_sorted)}] "
                                "(Enter=1, s=saltar grupo, q=terminar): ").strip().lower()
                except EOFError:
                    cprint("\nEntrada interrumpida: se detiene la revisión de grupos.")
                    interactive = False
                    raw = "q"
                if raw == "":
                    choice = 1
                    break
                if raw == "q":
                    cprint("\nOperación cancelada por el usuario.")
                    raise SystemExit(0)
                if raw in ("s", "n", "skip"):
                    choice = None
                    break
                if raw.isdigit() and 1 <= int(raw) <= len(paths_sorted):
                    choice = int(raw)
                    break
                cprint(f"  Opción no válida. Elige un número entre 1 y {len(paths_sorted)}, "
                      "'s' para saltar o 'q' para salir.")
            if choice is None:
                if not quiet:
                    for p in paths_sorted:
                        cprint(f"  Duplicado (omitido): {p}")
                    cprint()
                continue
            keep = paths_sorted[choice - 1]
            redundant = [p for p in paths_sorted if p != keep]
            if not quiet:
                cprint(f"  Conservar: {keep}")
        else:
            # Conservar el más antiguo (menor mtime) como "original"
            keep, *redundant = paths_sorted
            if not quiet:
                cprint(f"  Conservar: {keep}")

        wasted += size * len(redundant)

        for dup in redundant:
            if delete or interactive:
                if dry_run:
                    if not quiet:
                        cprint(f"  [DRY-RUN] Eliminaría: {dup}")
                    continue
                try:
                    dup.unlink()
                    if not quiet:
                        cprint(f"  Eliminado: {dup}")
                    deleted_count += 1
                except Exception as e:
                    raise OperationError(f"{dup}: {e}")
            elif not quiet:
                cprint(f"  Duplicado: {dup}")
        if not quiet:
            cprint()

    if not quiet:
        cprint()
        if delete or deleted_count:
            if dry_run:
                cprint(f"[DRY-RUN] {total_groups} grupo(s) de duplicados. "
                      f"Se liberarían {_human_size(wasted)}. "
                      "Usa sin --dry-run para eliminar los duplicados.")
            else:
                cprint(f"Completado: {deleted_count} archivo(s) duplicado(s) eliminados. "
                      f"Liberado: {_human_size(wasted)}.")
        else:
            cprint(f"Encontrados {total_groups} grupo(s) de duplicados. "
                  f"Espacio recuperable: {_human_size(wasted)}.")
            cprint("Usa 'duplicados-eliminar' para eliminar los redundantes.")

    return {"groups": total_groups, "wasted": wasted}


def _sha256(file_path: Path):
    """Devuelve el SHA-256 del contenido del archivo, o None si no se puede leer."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


PLAIN_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
    ".xml", ".html", ".htm", ".tex", ".py", ".js", ".ts", ".c", ".cpp",
    ".h", ".hpp", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".sh",
    ".yml", ".yaml", ".ini", ".cfg", ".conf", ".epub",
}


def _extract_text(file_path: Path) -> str:
    """Extrae el texto del archivo usando el lector adecuado según su extensión."""
    suffix = file_path.suffix.lower()

    if suffix in PLAIN_TEXT_SUFFIXES or suffix == "":
        return _read_text_file(file_path)

    if suffix == ".pdf":
        return _extract_with_tool("pdftotext", ["pdftotext", "-layout", str(file_path), "-"],
                                  file_path)

    if suffix in (".docx", ".odt", ".rtf", ".fodt", ".ott", ".org"):
        return _extract_with_tool("pandoc", ["pandoc", "-t", "plain", str(file_path)],
                                  file_path)

    raise UnsupportedFileFormatError(
        f"{file_path.name} (extensión '{suffix}'). "
        "Formatos compatibles: texto plano (.txt, .md, .csv, .json, .html, ...), "
        ".pdf (con 'pdftotext'), .docx/.odt/.rtf (con 'pandoc').")


def _read_text_file(file_path: Path) -> str:
    try:
        size = file_path.stat().st_size
        if size == 0:
            raise FileReadError(f"{file_path} está vacío")
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise FileReadError(f"{file_path}: {e}")


def _extract_with_tool(program: str, argv: list, file_path: Path) -> str:
    """Ejecuta una herramienta externa (pdftotext, pandoc) y devuelve su stdout."""
    try:
        result = subprocess.run(argv, capture_output=True, timeout=120, check=False)
    except FileNotFoundError:
        raise UnsupportedFileFormatError(
            f"no se encontró la herramienta '{program}' necesaria para leer "
            f"{file_path.name}. Instálala o convierte el archivo a .txt.")
    except PermissionError:
        raise UnsupportedFileFormatError(
            f"sin permisos para ejecutar '{program}'")
    except subprocess.TimeoutExpired:
        raise FileReadError(f"'{program}' tardó demasiado procesando {file_path.name}")

    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", "replace").strip()[:300]
        raise FileReadError(f"'{program}' no pudo con {file_path.name}: "
                            f"{err or f'código {result.returncode}'}")

    out = (result.stdout or b"").decode("utf-8", "replace")
    if not out.strip():
        raise FileReadError(
            f"'{program}' no obtuvo texto de {file_path.name} "
            "(¿PDF escaneado/sin capa de texto?)")
    return out


def summarize_file(file_path: Path, output: Path = None,
                   dry_run: bool = False, max_chars: int = None):
    """
    Resume con la IA de Simarro el contenido de un archivo de texto y guarda el
    resumen en un .txt junto al original (o en la ruta indicada).
    """
    if file_path is None:
        raise InvalidArgumentError("falta el archivo (fsort.py resumir <archivo> [destino.txt])")

    path = Path(file_path).expanduser()
    if not path.exists():
        raise FileReadError(f"{path} no existe")
    if not path.is_file():
        raise InvalidArgumentError(f"{path} no es un archivo")

    limit = max_chars or SUMMARY_MAX_CHARS
    if dry_run:
        dest = output or path.with_name(f"{path.stem}_resumen.txt")
        cprint(f"[DRY-RUN] Leería {path} ({_human_size(path.stat().st_size)}), "
              f"enviaría hasta {limit:,} caracteres a la IA ({_ai_config()['model']}) "
              f"y guardaría el resumen en {dest}.")
        return

    cprint(f"Extrayendo texto de {path}...")
    text = _extract_text(path)

    if not text.strip():
        raise FileReadError(f"{path}: no se encontró texto que resumir")

    truncated = False
    if len(text) > limit:
        cprint(f"Aviso: el documento tiene {len(text):,} caracteres y supera el limite "
               f"de {limit:,} (FSORT_SUMMARY_MAX_CHARS); se resumira solo el inicio. "
               "Sube el limite o reduce el archivo para un resumen completo.")
        text = text[:limit]
        truncated = True

    cprint(f"Resumiendo {len(text):,} caracteres con la IA "
          f"({_ai_config()['model']})...")

    prompt = (
        "Resume el siguiente documento. "
        "Sigue EXACTAMENTE el formato de encabezados que se te indica en las "
        "instrucciones de sistema.\n\n"
        "--- INICIO DOCUMENTO ---\n"
        f"{text}\n"
        "--- FIN DOCUMENTO ---\n"
    )
    if truncated:
        prompt += ("\n(El documento se truncó por límite de tamaño; resume solo "
                   "lo visible sin mencionarlo.)\n")

    summary = ask_ai(prompt, system_prompt=SUMMARY_SYSTEM_PROMPT)
    if not summary.strip():
        raise AIError("la IA devolvió un resumen vacío")

    dest = Path(output).expanduser() if output else path.with_name(f"{path.stem}_resumen.txt")
    if dest.suffix.lower() != ".txt":
        dest = dest.with_suffix(".txt")
    if dest.exists() and not dry_run:
        counter = 1
        original = dest
        while dest.exists():
            dest = original.with_name(f"{original.stem}_{counter}{original.suffix}")
            counter += 1

    header = (
        f"Resumen de: {path.name}\n"
        f"Generado: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Modelo: {_ai_config()['model']}\n"
        + ("Advertencia: el documento original se truncó para el análisis.\n"
           if truncated else "")
        + "-" * 70 + "\n\n"
    )

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(header + summary.strip() + "\n")
    except OSError as e:
        raise OperationError(f"no se pudo escribir {dest}: {e}")

    cprint()
    cprint(summary.strip())
    cprint()
    cprint(f"✓ Resumen guardado en {dest}")


def _sha256(file_path: Path):
    """Devuelve el SHA-256 del contenido del archivo, o None si no se puede leer."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _dir_size(path: Path) -> int:
    """Suma el tamaño en bytes de todos los archivos dentro de un archivo o carpeta."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _match_name(name: str, pattern: str) -> bool:
    """Indica si un nombre coincide con un patron glob (nombre o *.ext).

    Un patron sin comodines ('pdf') coincide con la extension; uno con
    comodines ('*.pdf', 'foto*') se evalua como glob sobre el nombre.
    """
    import fnmatch
    lowered = name.lower()
    p = pattern.lower()
    if p.startswith("*"):
        return lowered.endswith(p[1:])
    if any(c in p for c in "*?["):
        return fnmatch.fnmatch(lowered, p)
    return lowered == p or lowered == f".{p.lstrip('.')}" or lowered.endswith(f".{p.lstrip('.')}")


def _iter_files_sorted_by_mtime(directory: Path, ext: str = "*", recursive: bool = True) -> list:
    """Archivos del directorio ordenados por mtime (mas antiguos primero).

    Excluye el propio script. 'ext' filtra por extension (ver _match_name).
    """
    script_name = Path(__file__).name
    walker = directory.rglob("*") if recursive else directory.iterdir()
    entries = []
    for file_path in walker:
        try:
            if not file_path.is_file():
                continue
            if file_path.name == script_name or file_path.name == "fsort.py":
                continue
            if not _match_name(file_path.name, ext):
                continue
            entries.append((file_path.stat().st_mtime, file_path))
        except OSError:
            continue
    entries.sort(key=lambda item: item[0])
    return entries


def oldest_files(directory: Path, top: int = 15, dry_run: bool = False,
                 ext: str = "*", recursive: bool = True):
    """
    Lista los archivos mas antiguos de un directorio (por defecto los 15 primeros,
    ordenados del mas viejo al mas nuevo). 'ext' permite filtrar por extension.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    try:
        top = int(top)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"el número de archivos debe ser un entero, no '{top}'")
    if top <= 0:
        raise InvalidArgumentError(f"el número de archivos debe ser mayor que 0, no '{top}'")

    import datetime as _dt
    entries = _iter_files_sorted_by_mtime(directory, ext, recursive)
    if not entries:
        cprint("No hay archivos que analizar.")
        return

    selected = entries[:top]
    cprint(f"Top {len(selected)} archivo(s) mas antiguos en {directory}"
          + (f" (extensión: {ext})" if ext != "*" else "") + ":")
    for rank, (mtime, file_path) in enumerate(selected, 1):
        days = int((_dt.datetime.now().timestamp() - mtime) // 86400)
        fecha = _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        cprint(f"  {rank:>2}. {fecha}  {days:>4} d  {_human_size(file_path.stat().st_size):>9}  {file_path}")
    cprint()
    cprint(f"Total listados: {len(selected)}. Usa 'por-edad <directorio> [días]' para mover los viejos a la papelera.")


def aged_files(directory: Path, days: int = 365, dry_run: bool = False,
               ext: str = "*", assume_yes: bool = False, delete: bool = False):
    """
    Mueve a la papelera (o elimina con delete=True) los archivos con mas de N dias
    desde su ultima modificacion. Recursivo. Pide confirmacion salvo --yes/--dry-run.
    Registra los movidos en el log: se pueden recuperar con 'deshacer-limpieza'.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    try:
        days = int(days)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"el número de días debe ser un entero, no '{days}'")
    if days < 0:
        raise InvalidArgumentError(f"el número de días debe ser 0 o más, no '{days}'")

    import datetime as _dt
    umbral = _dt.datetime.now().timestamp() - days * 86400
    entries = [(m, f) for m, f in _iter_files_sorted_by_mtime(directory, ext) if m < umbral]

    if not entries:
        cprint(f"Ningun archivo con mas de {days} dia(s) de modificacion en {directory}.")
        return

    total_size = sum(f.stat().st_size for _, f in entries if f.exists())
    cprint(f"{len(entries)} archivo(s) con mas de {days} dia(s) ({_human_size(total_size)}):")
    for mtime, file_path in entries:
        fecha = _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        cprint(f"  {fecha}  {file_path}")
    cprint()

    if dry_run:
        verbo = "eliminaria" if delete else "moveria a la papelera"
        cprint(f"[DRY-RUN] Se {verbo} {len(entries)} archivo(s). "
               "Usa sin --dry-run para aplicar.")
        return

    if not (assume_yes or os.environ.get("FSORT_YES") == "1"):
        if not _confirm("Confirmar? [s/N] "):
            cprint("Cancelado: no se ha movido nada.")
            return
    else:
        cprint("  (--yes/FSORT_YES: confirmado automaticamente)")

    if delete:
        removed = 0
        for _, file_path in entries:
            try:
                file_path.unlink()
                cprint(f"Eliminado: {file_path}")
                removed += 1
            except Exception as e:
                raise OperationError(f"{file_path}: {e}")
        cprint(f"\nCompletado: {removed} archivo(s) eliminados. "
              f"Liberado: {_human_size(total_size)}.")
        return

    trash = Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser()
    trash.mkdir(parents=True, exist_ok=True)
    moved = 0
    logged = []
    for _, file_path in entries:
        dest = trash / file_path.name
        if dest.exists():
            counter = 1
            original = dest
            while dest.exists():
                dest = original.with_name(f"{original.stem}_{counter}{original.suffix}")
                counter += 1
        try:
            shutil.move(str(file_path), str(dest))
            cprint(f"Movido: {file_path} -> {trash}/")
            logged.append((str(file_path), str(dest)))
            moved += 1
        except Exception as e:
            raise OperationError(f"{file_path}: {e}")
    if logged:
        _append_move_log(logged)
    cprint(f"\nCompletado: {moved} archivo(s) movidos a {trash} "
          "(recuperables con 'deshacer-limpieza').")


def largest_files(directory: Path, top: int = 10, dry_run: bool = False,
                  delete: bool = False, ext: str = "*", assume_yes: bool = False):
    """
    Lista los archivos más grandes de un directorio (ordenados por tamaño).
    'ext' permite filtrar por extensión (ej: 'pdf'). Con 'delete=True' elimina los N.
    Con 'delete=True' pide confirmacion salvo dry_run o assume_yes (o FSORT_YES=1).
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))

    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    try:
        top = int(top)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"el número de archivos debe ser un entero, no '{top}'")

    if top <= 0:
        raise InvalidArgumentError(f"el número de archivos debe ser mayor que 0, no '{top}'")

    script_name = Path(__file__).name

    entries = []
    for file_path in directory.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name == script_name or file_path.name == "fsort.py":
            continue
        if not _match_name(file_path.name, ext):
            continue
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        entries.append((size, file_path))

    if not entries:
        cprint("No hay archivos que analizar.")
        return

    entries.sort(key=lambda item: item[0], reverse=True)
    selected = entries[:top]
    total = sum(size for size, _ in selected)

    cprint(f"Top {len(selected)} archivo(s) más grandes en {directory}"
          + (f" (extensión: {ext})" if ext != "*" else "") + ":")
    for rank, (size, file_path) in enumerate(selected, 1):
        cprint(f"  {rank:>2}. {_human_size(size):>9}  {file_path}")

    cprint()
    if delete and not dry_run:
        cprint(f"Se eliminaran {len(selected)} archivo(s) ({_human_size(total)}).")
        if not (assume_yes or os.environ.get("FSORT_YES") == "1"):
            if not _confirm("Confirmar eliminacion? [s/N] "):
                cprint("Cancelado: no se ha eliminado nada.")
                return
        else:
            cprint("  (--yes/FSORT_YES: confirmado automaticamente)")
    for size, file_path in selected:
        if delete:
            if dry_run:
                cprint(f"[DRY-RUN] Eliminaría: {file_path}")
                continue
            try:
                file_path.unlink()
                cprint(f"Eliminado: {file_path}")
            except Exception as e:
                raise OperationError(f"{file_path}: {e}")

    if delete:
        if dry_run:
            cprint(f"[DRY-RUN] Se liberarían {_human_size(total)}. "
                   "Usa sin --dry-run para eliminar.")
        else:
            cprint(f"Completado: liberado {_human_size(total)}.")
    else:
        cprint(f"Tamaño total de los seleccionados: {_human_size(total)}.")


# Patrones de basura reconocidos por 'limpiar' (nombre glob o sufijo si empieza por '*')
TEMP_PATTERNS = (
    "*.tmp", "*.temp", "*~", "*.bak", "*.old",
    "*.swp", "*.swo", "*.swn",
    "*.log",
    ".DS_Store", "Thumbs.db", "desktop.ini",
)


def _log_path() -> Path:
    """Ruta del log de operaciones de 'limpiar' (JSONL, una línea por archivo)."""
    if os.environ.get("FSORT_LOG_FILE"):
        return Path(os.environ["FSORT_LOG_FILE"]).expanduser()
    return Path.home() / ".fsort" / "clean_log.jsonl"


def _append_move_log(entries: list):
    """Registra (origen, destino) de cada movido por 'limpiar' para poder deshacer."""
    log = _log_path()
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            for src, dst in entries:
                rec = {"src": str(src), "dst": str(dst)}
                f.write(jsonlib.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        cprint("  Aviso: no se pudo escribir el log de limpieza; 'deshacer-limpieza' no recuperará estos archivos.")


def undo_clean(trash: Path = None, dry_run: bool = False, assume_yes: bool = False):
    """
    Deshace la última limpieza ('limpiar'): devuelve de la papelera al origen
    los archivos movidos, en orden inverso. Quita del log las entradas restauradas.
    Con FSORT_TRASH_DIR / papelera movida manualmente, usa el 'dst' registrado.
    """
    log = _log_path()
    if not log.exists():
        cprint("No hay registros de limpieza que deshacer.")
        return

    try:
        with open(log, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        raise FileReadError(f"{log}: {e}")

    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = jsonlib.loads(line)
            entries.append((Path(rec["src"]), Path(rec["dst"])))
        except (ValueError, TypeError, KeyError):
            entries.append(None)

    # Última limpieza = bloque contiguo final con src y dst comunes
    def base_of(p: Path) -> Path:
        return p.parent

    i = len(entries)
    while i > 0 and entries[i - 1] is None:
        i -= 1
    if i == 0:
        cprint("No hay registros de limpieza que deshacer.")
        return
    batch = [entries[i - 1]]
    batch_src = base_of(entries[i - 1][0])
    j = i - 1
    while j > 0 and entries[j - 1] is not None and base_of(entries[j - 1][0]) == batch_src:
        batch.append(entries[j - 1])
        j -= 1
    batch.reverse()
    keep = entries[:j]
    restore_to = batch_src
    trash_dir = base_of(batch[-1][1])

    disponibles = [(src, dst) for src, dst in batch if dst.exists()]
    perdidos = [(src, dst) for src, dst in batch if not dst.exists()]

    cprint(f"Última limpieza deshecha: {len(disponibles)} archivo(s) de "
          f"{restore_to} (papelera: {trash_dir})")
    for src, _ in perdidos:
        cprint(f"  Aviso: ya no está en la papelera, no se puede recuperar: {src}")
    if not disponibles:
        return

    if dry_run:
        for src, dst in disponibles:
            cprint(f"  [DRY-RUN] Restauraría: {dst} -> {src}")
        cprint("[DRY-RUN] Nada restaurado. Usa sin --dry-run para deshacer.")
        return

    if not (assume_yes or os.environ.get("FSORT_YES") == "1"):
        if not _confirm("¿Deshacer la última limpieza? [s/N] "):
            cprint("Cancelado: no se ha restaurado nada.")
            return
    else:
        cprint("  (--yes/FSORT_YES: confirmado automaticamente)")

    restored = 0
    for src, dst in reversed(disponibles):
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            final = src
            counter = 1
            while final.exists():
                final = src.with_name(f"{src.stem}_{counter}{src.suffix}")
                counter += 1
            shutil.move(str(dst), str(final))
            cprint(f"  Restaurado: {dst.name} -> {final}")
            restored += 1
        except Exception as e:
            cprint(f"  Error al restaurar {dst}: {e}")

    # Reescribir el log sin las entradas restauradas
    try:
        with open(log, "w", encoding="utf-8") as f:
            for e in keep:
                if e is not None:
                    f.write(jsonlib.dumps({"src": str(e[0]), "dst": str(e[1])},
                                          ensure_ascii=False) + "\n")
    except OSError as e:
        cprint(f"  Aviso: entradas restauradas pero el log no se pudo actualizar: {e}")

    cprint(f"\nCompletado: {restored} archivo(s) restaurados en {restore_to}.")


def clean_temp(directory: Path, dry_run: bool = False, assume_yes: bool = False,
               recursive: bool = True):
    """
    Mueve archivos temporales y de respaldo del directorio (recursivo por defecto)
    a la papelera (FSORT_TRASH_DIR o ./trash, que se crea si falta).

    Reconoce: .tmp .temp ~ .bak .old .swp .swo .swn .log y basura de sistema
    (.DS_Store, Thumbs.db, desktop.ini). Pide confirmacion salvo --dry-run,
    --yes/-y o FSORT_YES=1. Sin TTY no confirma: no mueve nada.
    """
    import fnmatch
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    trash = Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser()

    def is_temp(p: Path) -> bool:
        for pat in TEMP_PATTERNS:
            if pat.startswith("*"):
                if p.name.lower().endswith(pat[1:].lstrip("*")):
                    return True
            elif fnmatch.fnmatch(p.name.lower(), pat.lower()):
                return True
        return False

    walker = directory.rglob("*") if recursive else directory.iterdir()
    candidates = [p for p in walker if p.is_file() and is_temp(p)]

    # No tocar la propia papelera si cuelga del directorio
    try:
        trash_res = trash.resolve()
    except OSError:
        trash_res = trash

    def in_trash(p: Path) -> bool:
        try:
            p.resolve().relative_to(trash_res)
            return True
        except (ValueError, OSError):
            return False

    candidates = [p for p in candidates if not in_trash(p)]

    if not candidates:
        cprint(f"Nada que limpiar en {directory} (no hay archivos temporales).")
        return

    cprint(f"Se moverian a la papelera ({trash}) {len(candidates)} archivo(s):")
    for p in sorted(candidates):
        cprint(f"  {p}")
    cprint()

    if dry_run:
        cprint(f"[DRY-RUN] {len(candidates)} archivo(s) se moverian a {trash}. "
               "Usa sin --dry-run para aplicar.")
        return

    if not (assume_yes or os.environ.get("FSORT_YES") == "1"):
        if not _confirm("Confirmar? [s/N] "):
            cprint("Cancelado: no se ha movido nada.")
            return
    elif assume_yes and not os.environ.get("FSORT_YES") and not sys.stdin.isatty():
        # 'assume_yes' via kwargs (limpiar-auto) en entorno sin TTY: no mueve nada
        # a traicion. Para automatizaciones sin TTY, usa FSORT_YES=1 (o --yes).
        cprint("  (sin TTY: 'limpiar-auto' no actua sin FSORT_YES=1 ni --yes; cancelado)")
        return
    else:
        cprint("  (--yes/FSORT_YES: confirmado automaticamente)")

    trash.mkdir(parents=True, exist_ok=True)
    moved = 0
    logged = []
    for p in candidates:
        dest = trash / p.name
        if dest.exists():
            counter = 1
            original = dest
            while dest.exists():
                dest = original.with_name(f"{original.stem}_{counter}{original.suffix}")
                counter += 1
        try:
            shutil.move(str(p), str(dest))
            cprint(f"Movido: {p} -> {trash}/")
            logged.append((str(p), str(dest)))
            moved += 1
        except Exception as e:
            raise OperationError(f"{p}: {e}")

    if logged:
        _append_move_log(logged)

    cprint(f"\nCompletado: {moved} archivo(s) movidos a {trash}.")


def dir_report(directory: Path, dry_run: bool = False, top: int = 10):
    """
    Resumen de un directorio: archivos, tamaños, top de extensiones,
    archivos temporales (limpiadores con 'limpiar') y duplicados.
    Solo lectura: no mueve ni elimina nada.
    """
    try:
        top = int(top)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"el número de extensiones debe ser un entero, no '{top}'")
    if top <= 0:
        raise InvalidArgumentError(f"el número de extensiones debe ser mayor que 0, no '{top}'")

    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    import fnmatch

    script_name = Path(__file__).name

    def is_temp(p: Path) -> bool:
        for pat in TEMP_PATTERNS:
            if pat.startswith("*"):
                if p.name.lower().endswith(pat[1:].lstrip("*")):
                    return True
            elif fnmatch.fnmatch(p.name.lower(), pat.lower()):
                return True
        return False

    files = []
    subdirs = 0
    total_size = 0
    ext_size: dict = {}
    ext_count: dict = {}
    temp_files = []

    for entry in directory.rglob("*"):
        try:
            if entry.is_dir():
                subdirs += 1
                continue
            if not entry.is_file() or entry.name in (script_name, "fsort.py"):
                continue
            size = entry.stat().st_size
        except OSError:
            continue
        files.append(entry)
        total_size += size
        ext = entry.suffix.lower() or "sin_extension"
        ext_size[ext] = ext_size.get(ext, 0) + size
        ext_count[ext] = ext_count.get(ext, 0) + 1
        if is_temp(entry):
            temp_files.append(entry)

    cprint(f"Reporte de: {directory}")
    cprint("-" * 70)
    cprint(f"  Archivos:        {len(files)}")
    cprint(f"  Subcarpetas:     {subdirs}")
    cprint(f"  Tamaño total:    {_human_size(total_size)}")

    if ext_size:
        top_ext = sorted(ext_size.items(), key=lambda kv: kv[1], reverse=True)[:top]
        cprint(f"\n  Top {len(top_ext)} extensiones por tamaño:")
        for rank, (ext, size) in enumerate(top_ext, 1):
            cprint(f"    {rank:>2}. {ext:<14} {_human_size(size):>10}  "
                  f"({ext_count[ext]} archivo(s))")

    if temp_files:
        temp_size = sum(f.stat().st_size for f in temp_files if f.exists())
        cprint(f"\n  Temporales/basura detectados: {len(temp_files)} "
              f"({_human_size(temp_size)}) — usa 'limpiar {directory}'")

    dups = find_duplicates(directory, dry_run=True, quiet=True)
    if dups.get("groups"):
        cprint(f"\n  Duplicados: {dups['groups']} grupo(s), "
              f"recuperable {_human_size(dups['wasted'])} — usa 'duplicados {directory}'")

    cprint()


ARCHIVE_SUFFIXES = (".zip", ".rar", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                    ".tar.xz", ".txz", ".gz", ".bz2", ".xz")


def _unpack_members(archivo: Path):
    """Clasifica un archivo comprimido y lista sus miembros como (nombre, es_dir),
    o None si no es un formato reconocible. Para .gz/.bz2/.xz sueltos devuelve
    ([('nombre-descomprimido', False)], tipo='gzip'). Rechaza miembros con rutas
    absolutas o travesias '..' (proteccion anti zip-slip).

    Devuelve (miembros, tipo) con tipo en {'zip', 'tar', 'gz'} o None.
    """
    nombre = archivo.name.lower()

    if nombre.endswith(".zip") or zipfile.is_zipfile(str(archivo)):
        try:
            with zipfile.ZipFile(str(archivo)) as zf:
                membros = [(info.filename, info.is_dir()) for info in zf.infolist()]
        except (zipfile.BadZipFile, OSError):
            raise FileReadError(f"{archivo}: no es un ZIP válido")
        tipo = "zip"
    elif tarfile.is_tarfile(str(archivo)):
        try:
            with tarfile.open(str(archivo)) as tf:
                membros = [(m.name, m.isdir()) for m in tf.getmembers()]
        except tarfile.TarError as e:
            raise FileReadError(f"{archivo}: no es un TAR válido ({e})")
        tipo = "tar"
    else:
        import gzip as _gzip
        import bz2 as _bz2
        import lzma as _lzma
        abierto = None
        try:
            with open(archivo, "rb") as f:
                magic = f.read(6)
            if magic[:2] == b"\x1f\x8b":
                with _gzip.open(str(archivo), "rb") as abierto:
                    abierto.read(1)
                tipo = "gz"
            elif magic[:3] == b"BZh":
                with _bz2.open(str(archivo), "rb") as abierto:
                    abierto.read(1)
                tipo = "gz"
            elif magic[:6] == b"\xfd7zXZ\x00":
                with _lzma.open(str(archivo), "rb") as abierto:
                    abierto.read(1)
                tipo = "gz"
            else:
                return None
        except OSError:
            return None
        except Exception:
            return None
        stem = nombre
        for s in (".gz", ".bz2", ".xz"):
            if stem.endswith(s):
                stem = stem[:-len(s)]
                break
        membros = [(archivo.name or "contenido", False)]
    if membros is None:
        return None

    # Validacion de seguridad: sin rutas absolutas ni escapes '..'
    for nombre_member, _ in membros:
        n = nombre_member.replace("\\", "/")
        if n.startswith("/") or (os.path.isabs(n) and not n.startswith("//")):
            raise OperationError(f"{archivo}: miembro con ruta absoluta '{nombre_member}' "
                                 "(posible zip-slip); extraccion abortada")
        partes = [p for p in n.split("/") if p not in ("", ".")]
        if ".." in partes:
            raise OperationError(f"{archivo}: miembro que escapa del destino "
                                 f"('{nombre_member}'); extraccion abortada")
    return (membros, tipo)


def _destino_unico(dest: Path) -> Path:
    """evita pisar: si destino existe, anade _1, _2..."""
    if not dest.exists():
        return dest
    counter = 1
    cand = dest.with_name(f"{dest.name}_{counter}")
    while cand.exists():
        counter += 1
        cand = dest.with_name(f"{dest.name}_{counter}")
    return cand


def extract_archive(archivo: Path, destino: Path = None, dry_run: bool = False):
    """
    Extrae un archivo comprimido (.zip, .tar y variantes .gz/.bz2/.xz, .tgz,
    .txz, y .gz/.bz2/.xz sueltos) a <destino> (por defecto una subcarpeta junto
    al original con el nombre del archivo, sin extension). Nunca sobrescribe:
    si el destino existe se crea <destino>_1. Rechaza archivos ZIP/TAR con
    rutas maliciosas (zip-slip). .rar requiere herramienta externa.
    """
    if archivo is None:
        raise InvalidArgumentError("falta el archivo (fsort.py descomprimir-a <archivo> [destino])")
    path = Path(archivo).expanduser()
    if not path.exists():
        raise FileReadError(f"{path} no existe")
    if not path.is_file():
        raise InvalidArgumentError(f"{path} no es un archivo")

    es_rar = path.name.lower().endswith(".rar")

    resu = None if es_rar else _unpack_members(path)
    if resu is None:
        if es_rar:
            raise UnsupportedFileFormatError(
                f"{path.name}: el formato .rar no está soportado de forma nativa. "
                "Conviértelo a .zip/.tar o usa una herramienta externa.")
        raise UnsupportedFileFormatError(
            f"{path.name}: formato no reconocido. Compatibles: .zip, .tar, .tar.gz/.tgz, "
            ".tar.bz2/.tbz2, .tar.xz/.txz y .gz/.bz2/.xz sueltos.")
    membros, tipo = resu

    if destino is None:
        stem = path.name
        for s in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz",
                  ".zip", ".tar", ".gz", ".bz2", ".xz"):
            if stem.lower().endswith(s):
                stem = stem[:-len(s)]
                break
        destino = path.with_name(stem)
    dest = Path(destino).expanduser()

    if dry_run:
        dirs = sum(1 for _, d in membros if d)
        ficheros = len(membros) - dirs
        cprint(f"[DRY-RUN] Extraería {len(membros)} miembro(s) de {path.name} "
              f"({ficheros} archivo(s), {dirs} carpeta(s)) en {dest}. "
              "Usa sin --dry-run para extraer.")
        return

    final = _destino_unico(dest)
    final.mkdir(parents=True, exist_ok=True)

    try:
        if tipo == "zip":
            with zipfile.ZipFile(str(path)) as zf:
                zf.extractall(str(final))
        elif tipo == "tar":
            with tarfile.open(str(path)) as tf:
                try:
                    tf.extractall(str(final), filter="data")
                except TypeError:  # Python < 3.12 sin filter
                    tf.extractall(str(final))
        else:  # gz/bz2/xz sueltos: un unico archivo descomprimido
            import gzip as _gzip
            import bz2 as _bz2
            import lzma as _lzma
            sueltos = {"gz": _gzip.open, "bz2": _bz2.open, "xz": _lzma.open}
            modo = _gzip.open
            for s, op in ((".gz", _gzip.open), (".bz2", _bz2.open), (".xz", _lzma.open)):
                if path.name.lower().endswith(s):
                    modo = op
                    break
            miembro = membros[0][0]
            out = final / miembro
            with modo(str(path), "rb") as f_in, open(out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
        raise OperationError(f"no se pudo extraer {path.name}: {e}")

    cprint(f"✓ Extraído {path.name} en {final}/ ({len(membros)} miembro(s)).")


def _arbol(dir_base: Path, raiz: Path):
    """Genera (ruta_relativa, Path_absoluto, es_dir) de todo el arbol de dir_base."""
    for ruta in sorted(dir_base.rglob("*")):
        try:
            if not (ruta.is_file() or ruta.is_dir()):
                continue
            yield ruta.relative_to(dir_base), ruta, ruta.is_dir()
        except OSError:
            continue


def _borrar_a_papelera(ruta: Path, trash: Path, dry_run: bool, logged: list) -> bool:
    """Mueve un archivo o carpeta (recursivo) a la papelera. Dry-run no toca nada."""
    if dry_run:
        return True
    try:
        trash.mkdir(parents=True, exist_ok=True)
        destino = trash / ruta.name
        if destino.exists():
            destino = _destino_unico(destino)
        if ruta.is_dir():
            for f in sorted(ruta.rglob("*")):
                if f.is_file():
                    rel = f.parent.relative_to(ruta)
                    (destino / rel).mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(destino / rel))
                    logged.append((str(f), str(destino / rel)))
            shutil.rmtree(ruta)
        else:
            shutil.move(str(ruta), str(destino))
            logged.append((str(ruta), str(destino)))
        return True
    except OSError:
        return False


def sync_dirs(origen: Path, destino: Path = None, dry_run: bool = False,
              delete: bool = False, assume_yes: bool = False):
    """
    Sincroniza el arbol de <origen> en <destino> (mirror, respetando
    subcarpetas) sin borrar en el destino salvo con 'borrar' (que manda a la
    papelera lo que ya no existe en el origen y es recuperable con
    'deshacer-limpieza'). Copia archivos nuevos o mas recientes (mtime) y
    nunca toca los que ya cuadran. Sin --dry-run pide confirmacion (salvo
    --yes/FSORT_YES=1). Sin destino se sincroniza con ./<nombre-origen>.
    """
    if origen is None:
        raise InvalidArgumentError("falta el origen (fsort.py sincronizar <origen> [destino])")
    if not origen.exists():
        raise DirectoryNotFoundError(str(origen))
    if not origen.is_dir():
        raise NotADirectoryError_(str(origen))

    if destino is None:
        destino = Path(origen.resolve().name)
    dst = Path(destino).expanduser()
    if not dst.exists():
        raise DestinationNotFoundError(str(dst))
    if not dst.is_dir():
        raise NotADirectoryError_(str(dst))
    if origen.resolve() == dst.resolve():
        raise InvalidArgumentError("origen y destino son el mismo directorio")
    try:
        dst.resolve().relative_to(origen.resolve())
        raise InvalidArgumentError("el destino esta dentro del origen; elegiria otra ruta")
    except ValueError:
        pass

    script_name = Path(__file__).name

    # Estado de origen y destino
    src_files = {}
    src_dirs = set()
    for rel, ruta, es_dir in _arbol(origen, origen):
        if not es_dir and (ruta.name == script_name or ruta.name == "fsort.py"):
            continue
        if es_dir:
            src_dirs.add(rel)
        else:
            st = ruta.stat()
            src_files[rel] = (st.st_size, int(st.st_mtime))

    dst_files = {}
    dst_dirs = set()
    for rel, ruta, es_dir in _arbol(dst, dst):
        if es_dir:
            dst_dirs.add(rel)
        else:
            st = ruta.stat()
            dst_files[rel] = (st.st_size, int(st.st_mtime))

    a_copiar = []
    for rel, (size, mtime) in src_files.items():
        if rel not in dst_files or dst_files[rel][0] != size or dst_files[rel][1] < mtime - 1:
            a_copiar.append(rel)

    a_crear_dirs = sorted(d for d in src_dirs if d not in dst_dirs)
    borrar = []
    if delete:
        borrar = sorted(rel for rel in dst_files if rel not in src_files)

    if not a_copiar and not a_crear_dirs and not borrar:
        cprint("Ya sincronizado: no hay cambios.")
        return

    cprint(f"Sincronizar {origen} -> {dst}")
    if a_crear_dirs:
        cprint(f"  Crear carpetas: {len(a_crear_dirs)}")
    if a_copiar:
        total_copiar = sum(origen.joinpath(r).stat().st_size for r in a_copiar if origen.joinpath(r).exists())
        cprint(f"  Copiar/actualizar archivos: {len(a_copiar)} ({_human_size(total_copiar)})")
    if delete:
        total_borrar = sum(dst.joinpath(r).stat().st_size for r in borrar if dst.joinpath(r).exists())
        cprint(f"  Borrar de la papelera (sobrantes en destino): {len(borrar)} ({_human_size(total_borrar)})")

    if dry_run:
        for rel in a_crear_dirs:
            cprint(f"  [DRY-RUN] mkdir: {rel}/")
        for rel in a_copiar:
            cprint(f"  [DRY-RUN] copiar: {rel}")
        if delete:
            for rel in borrar:
                cprint(f"  [DRY-RUN] a papelera: {rel}")
        cprint("[DRY-RUN] Nada sincronizado. Usa sin --dry-run para aplicar.")
        return

    if not (assume_yes or os.environ.get("FSORT_YES") == "1"):
        if not _confirm("¿Sincronizar? [s/N] "):
            cprint("Cancelado: no se ha copiado nada.")
            return
    else:
        cprint("  (--yes/FSORT_YES: confirmado automaticamente)")

    copiados = 0
    creados = 0
    eliminados = 0
    logged = []
    trash = Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser()

    for rel in a_crear_dirs:
        (dst / rel).mkdir(parents=True, exist_ok=True)
        creados += 1

    for rel in a_copiar:
        try:
            src = origen / rel
            final = dst / rel
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists() and final.is_file():
                # el preexistente va a la papelera (nunca se pisa)
                if _borrar_a_papelera(final, trash, False, logged):
                    shutil.copy2(str(src), str(final))
                    st = src.stat()
                    os.utime(final, (st.st_atime, st.st_mtime))
                    logged.append((str(src), str(final)))
                    cprint(f"  Actualizado (anterior a papelera): {rel}")
                else:
                    cprint(f"  Omitido (no se pudo apartar el preexistente): {rel}")
                    continue
            else:
                shutil.copy2(str(src), str(final))
                logged.append((str(src), str(final)))
                cprint(f"  Copiado: {rel}")
            copiados += 1
        except OSError as e:
            cprint(f"  Error al copiar {rel}: {e}")

    if delete:
        for rel in reversed(borrar):
            if _borrar_a_papelera(dst / rel, trash, False, logged):
                cprint(f"  A papelera: {rel}")
                eliminados += 1
            else:
                cprint(f"  Aviso: no se pudo mover a la papelera {rel}; se conserva")

    if logged:
        _append_move_log(logged)

    partes = []
    if creados:
        partes.append(f"{creados} carpeta(s) creadas")
    if copiados:
        partes.append(f"{copiados} archivo(s) copiados")
    if delete:
        partes.append(f"{eliminados} sobrante(s) a la papelera")
    cprint(f"\nCompletado: {', '.join(partes)}.")


def dedup_hardlink(directory: Path, dry_run: bool = False, delete: bool = False,
                   min_size: int = 1, recursive: bool = True, assume_yes: bool = False):
    """
    Convierte los archivos duplicados (mismo contenido) en hardlinks a una copia
    'canonica' (la mas antigua), liberando espacio sin perder ninguna ruta.
    Recupera el espacio como 'duplicados-eliminar' pero conservando todos los
    caminos. Con 'delete=True' elimina en vez de hardlinkear (igual que
    'duplicados-eliminar' pero en lote, sin preguntar grupo a grupo).

    Solo actua sobre grupos cuyo canonico y redundantes estan en el mismo
    filesystem (st_dev); los demas se listan pero no se tocan. Pide
    confirmacion salvo --dry-run / --yes / FSORT_YES=1.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    script_name = Path(__file__).name
    walker = directory.rglob("*") if recursive else directory.iterdir()
    files = [f for f in walker if f.is_file()
             and f.name != script_name and f.name != "fsort.py"]

    # No deduplicar lo que ya esta en la papelera (los .bak son copias de seguridad)
    trash_probe = Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser()
    try:
        trash_res = trash_probe.resolve()
    except OSError:
        trash_res = trash_probe

    def en_trash(p: Path) -> bool:
        try:
            p.resolve().relative_to(trash_res)
            return True
        except (ValueError, OSError):
            return False

    files = [f for f in files if not en_trash(f)]

    # Paso 1: agrupar por tamano
    by_size: dict = {}
    for file_path in files:
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size < min_size:
            continue
        by_size.setdefault(size, []).append(file_path)

    # Paso 2: hash solo a candidatos
    by_hash: dict = {}
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue
        for file_path in candidates:
            digest = _sha256(file_path)
            if digest is None:
                continue
            by_hash.setdefault((size, digest), []).append(file_path)

    grupos = [ps for ps in by_hash.values() if len(ps) > 1]
    if not grupos:
        cprint("No hay duplicados que deduplicar.")
        return

    grupos.sort(key=lambda ps: ps[0].stat().st_size * (len(ps) - 1), reverse=True)

    # Paso 3: filtrar por filesystem comun (st_dev) y clasificar
    accionables = []
    total_recuperable = 0
    omitidos_fs = 0
    ya_hardlink = 0
    for paths in grupos:
        try:
            st = paths[0].stat()
        except OSError:
            continue
        dev = st.st_dev
        mismo = [p for p in paths if p.stat().st_dev == dev]
        omitidos_fs += len(paths) - len(mismo)
        if len(mismo) < 2:
            continue
        canon = min(mismo, key=lambda p: p.stat().st_mtime)
        redundantes = []
        for p in mismo:
            if p == canon:
                continue
            st_p = p.stat()
            st_c = canon.stat()
            if st_p.st_ino == st_c.st_ino:
                ya_hardlink += 1
                continue
            redundantes.append(p)
        if not redundantes:
            continue
        accionables.append((canon, redundantes, canon.stat().st_size))
        total_recuperable += canon.stat().st_size * len(redundantes)

    if not accionables:
        if ya_hardlink:
            cprint(f"Sin cambios: {ya_hardlink} duplicado(s) ya estan hardlinkeados.")
        else:
            cprint("Sin cambios: no hay duplicados deduplicables en un mismo filesystem.")
        return

    n_total = sum(len(r) for _, r, _ in accionables)
    if delete:
        cprint(f"{len(accionables)} grupo(s): {n_total} duplicado(s) a eliminar "
              f"(liberará {_human_size(total_recuperable)}).")
    else:
        cprint(f"{len(accionables)} grupo(s): {n_total} duplicado(s) a enlazar "
              f"(liberará {_human_size(total_recuperable)}).")
    for canon, redundantes, size in accionables[:20]:
        cprint(f"  {_human_size(size)} c/u  canonico: {canon}")
        for r in redundantes:
            cprint(f"    -> {r}")
    if len(accionables) > 20:
        cprint(f"  ... y {len(accionables) - 20} grupo(s) mas.")
    if omitidos_fs:
        cprint(f"  Omitidos por estar en otro filesystem: {omitidos_fs}.")
    if ya_hardlink:
        cprint(f"  Ya hardlinkeados (se conservan): {ya_hardlink}.")
    cprint()

    if dry_run:
        cprint("[DRY-RUN] No se ha tocado nada. Usa sin --dry-run para aplicar y "
               "liberar el espacio.")
        return

    if not (assume_yes or os.environ.get("FSORT_YES") == "1"):
        if not _confirm("Confirmar? [s/N] "):
            cprint("Cancelado: no se ha tocado nada.")
            return
    else:
        cprint("  (--yes/FSORT_YES: confirmado automaticamente)")

    trash = Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser()
    processed = 0
    freed = 0
    errores = 0
    if not delete:
        trash.mkdir(parents=True, exist_ok=True)
    for canon, redundantes, size in accionables:
        for r in redundantes:
            if delete:
                try:
                    r.unlink()
                    processed += 1
                    freed += size
                except OSError as e:
                    errores += 1
                    cprint(f"  Error al eliminar {r}: {e}")
                continue
            try:
                backup = trash / f"{r.name}.bak"
                if backup.exists():
                    backup = _destino_unico(backup)
                shutil.move(str(r), str(backup))
                try:
                    os.link(str(canon), str(r))
                    processed += 1
                    freed += size
                except OSError:
                    # restaurar el original si el hardlink fallo
                    try:
                        shutil.move(str(backup), str(r))
                    except OSError:
                        pass
                    raise
            except OSError as e:
                errores += 1
                cprint(f"  Error con {r}: {e}")

    cprint()
    if delete:
        cprint(f"Completado: {processed} archivo(s) eliminados. "
              f"Liberado: {_human_size(freed)}.")
    else:
        cprint(f"Completado: {processed} duplicado(s) hardlinkeados. "
              f"Liberado: {_human_size(freed)}. "
              "(Backups .bak en la papelera; 'deshacer-limpieza' no los usa: "
              "borralos a mano cuando quieras).")
    if errores:
        cprint(f"  Errores: {errores} (sin contar).")


def empty_trash(directory: Path = None, dry_run: bool = False,
                top: int = 0, delete: bool = False, ext: str = "*"):
    """
    Vacía la papelera eliminando de forma permanente su contenido.
    Por defecto usa FSORT_TRASH_DIR o './trash'. Con 'top=N' solo los N más grandes.
    Con 'delete=False' (vista por defecto) solo lista el contenido sin borrar.
    """
    trash = directory or Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser()

    if not trash.exists():
        cprint(f"La papelera ({trash}) no existe. Nada que vaciar.")
        return

    trash = trash.resolve()

    if not trash.is_dir():
        raise NotADirectoryError_(str(trash))

    # Contenido de primer nivel (no la carpeta raíz de la papelera)
    all_entries = list(trash.iterdir())
    entries = [p for p in all_entries if _match_name(p.name, ext)]
    skipped_by_ext = [p for p in all_entries if not _match_name(p.name, ext)]

    if not entries:
        if skipped_by_ext:
            cprint(f"La papelera ({trash}) no está vacía, pero ningún elemento coincide "
                  f"con el filtro '{ext}' ({len(skipped_by_ext)} dentro).")
        else:
            cprint(f"La papelera ({trash}) ya está vacía.")
        return

    sized = [(_dir_size(p), p) for p in entries]
    sized.sort(key=lambda item: item[0], reverse=True)

    try:
        top = int(top)
    except (TypeError, ValueError):
        raise InvalidArgumentError(f"el número de archivos debe ser un entero, no '{top}'")

    # Que se queda fuera de esta pasada (para no afirmar 'vaciada' en falso)
    if top > 0:
        skipped = [p for _, p in sized[top:]]
        sized = sized[:top]
    else:
        skipped = []
    skipped += skipped_by_ext

    do_delete = delete

    if do_delete:
        cprint(f"Vaciando la papelera ({trash}):")
    else:
        cprint(f"Contenido de la papelera ({trash}):")

    freed = 0
    count = 0
    for size, entry in sized:
        label = f"{entry.name}/" if entry.is_dir() else entry.name
        if do_delete:
            if dry_run:
                cprint(f"  [DRY-RUN] Eliminaría: {label} ({_human_size(size)})")
                freed += size
                count += 1
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                cprint(f"  Eliminado: {label} ({_human_size(size)})")
                freed += size
                count += 1
            except Exception as e:
                raise OperationError(f"{entry}: {e}")
        else:
            cprint(f"  {label} ({_human_size(size)})")
            freed += size
            count += 1

    cprint()
    # ¿Queda algo dentro tras la pasada? (no afirmar 'vaciada' en falso con filtros/top)
    if do_delete and dry_run:
        remaining_count = len(skipped)          # no se ha borrado nada realmente
    elif do_delete:
        try:
            remaining_count = sum(1 for _ in trash.iterdir())
        except OSError:
            remaining_count = 0
    else:
        remaining_count = len(skipped)

    if not do_delete:
        total_all = sum(_dir_size(p) for p in all_entries)
        cprint(f"{count} elemento(s) listados. Total papelera: {_human_size(total_all)}. "
              "Usa 'vaciar-papelera-ya' para eliminar el contenido.")
    elif dry_run:
        base = f"[DRY-RUN] {count} elemento(s). Se liberarían {_human_size(freed)}."
        base += (f" Quedarían {remaining_count} elemento(s) sin tocar "
                 "(filtrados por 'ext' o fuera del top)." if remaining_count
                 else " La papelera quedaría vacía.")
        cprint(base + " Usa sin --dry-run para vaciar la papelera.")
    else:
        if remaining_count:
            cprint(f"Papelera NO vaciada por completo: {count} elemento(s) eliminados "
                  f"(liberado {_human_size(freed)}); quedan {remaining_count} dentro "
                  "(filtrados o fuera del top). Repite sin filtros para vaciar del todo.")
        else:
            cprint(f"Papelera vaciada: {count} elemento(s) eliminados. Liberado: {_human_size(freed)}.")


SNAPSHOT_DATE_FMT = "%Y%m%d-%H%M%S"


def _snapshot_root() -> Path:
    """Carpeta raiz de las instantaneas (FSORT_SNAPSHOT_DIR o ~/.fsort/snapshots)."""
    if os.environ.get("FSORT_SNAPSHOT_DIR"):
        return Path(os.environ["FSORT_SNAPSHOT_DIR"]).expanduser()
    return Path.home() / ".fsort" / "snapshots"


def _snapshot_slug(directory: Path) -> str:
    """Nombre base del archivo de instantanea a partir del directorio."""
    slug = re.sub(r"[^\w.-]+", "_", directory.resolve().name).strip("._")
    return slug or "directorio"


def _snapshot_files_of(dir_json: Path) -> list:
    """Rutas .json de instantaneas de un directorio (excluye backups _1, _2...)."""
    return sorted(p for p in dir_json.glob("*.json")
                  if not re.search(r"_\d+$", p.stem))


def _resolve_snapshot_files(directory: Path, name: str = None) -> list:
    """Lista de archivos-json de instantaneas del directorio (o del nombre indicado).

    Con 'name' puede ser un slug (busqueda exacta) o una ruta .json directa.
    Sin 'name' devuelve todas las del directorio ordenadas por fecha (la ultima
    es la mas reciente, porque el prefijo temporal es ordenable).
    """
    if name:
        if name.endswith(".json") and os.path.isfile(name):
            return [Path(name)]
        slug = _snapshot_slug(directory)
        exact = _snapshot_files_of(_snapshot_root() / slug / name)
        if exact:
            return exact
        files = _snapshot_files_of(_snapshot_root() / slug)
        por_nombre = [p for p in files if p.stem == name
                      or p.stem.startswith(f"{name}-")]
        if por_nombre:
            return por_nombre
        raise InvalidArgumentError(
            f"no hay instantanea '{name}' para {directory} "
            "(usa 'snapshot-list' para ver las disponibles)")
    files = _snapshot_files_of(_snapshot_root() / _snapshot_slug(directory))
    if not files:
        raise InvalidArgumentError(
            f"no hay instantaneas para {directory} "
            "(crea una con 'fsort.py snapshot <directorio>')")
    return files


def _load_snapshot(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            snap = jsonlib.load(f)
    except FileNotFoundError:
        raise FileReadError(str(path))
    except json.JSONDecodeError as e:
        raise FileReadError(f"{path} (línea {e.lineno}, columna {e.colno}): {e.msg}")
    if not isinstance(snap, dict) or "files" not in snap:
        raise FileReadError(f"{path}: no es una instantanea valida")
    return snap


def _inventory_directory(directory: Path, hash_max_mb: float = 25.0) -> dict:
    """Inventario del directorio (recursivo): ruta relativa -> {size, mtime, sha256}.

    Solo hashea archivos de hasta 'hash_max_mb' MB (los grandes se comparan por
    tamano+mtime); omite symlinks y errores de lectura, y excluye el arbol de
    instantaneas si cae dentro del directorio inventoryado.
    """
    files = {}
    snap_root = _snapshot_root()
    for f in sorted(directory.rglob("*"), key=lambda p: str(p)):
        try:
            if f.is_symlink() or not f.is_file():
                continue
            if f.resolve() == snap_root or snap_root in f.parents:
                continue
            st = f.stat()
        except OSError:
            continue
        entry = {"size": st.st_size, "mtime": int(st.st_mtime)}
        if st.st_size <= int(hash_max_mb * 1024 * 1024):
            digest = _sha256(f)
            if digest:
                entry["sha256"] = digest
        files[f.relative_to(directory).as_posix()] = entry
    return files


def dir_snapshot(directory: Path, dry_run: bool = False, name: str = None,
                 label: str = ""):
    """Guarda una instantanea (inventario con hash) del directorio en ~/.fsort/snapshots.

    Nombre generado: <slug>-<YYYYmmdd-HHMMSS>.json dentro de la carpeta del
    directorio; se conserva el ultimo SNAPSHOT_KEEP (por defecto 20; 0 = todos).
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    try:
        keep = int(os.environ.get("SNAPSHOT_KEEP", "20"))
    except ValueError:
        keep = 20

    if dry_run:
        n = sum(1 for _ in directory.rglob("*"))
        cprint(f"[DRY-RUN] Crearía una instantánea de {directory} "
               f"(~{n} elemento(s)) en {_snapshot_root() / _snapshot_slug(directory)}. "
               "No se ha guardado nada.")
        return

    files = _inventory_directory(directory)
    now = datetime.now()
    stamp = now.strftime(SNAPSHOT_DATE_FMT)
    base = name or _snapshot_slug(directory)
    dir_json = _snapshot_root() / _snapshot_slug(directory)
    try:
        dir_json.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OperationError(f"{dir_json}: {e}")

    path = dir_json / f"{base}-{stamp}.json"
    counter = 1
    while path.exists():
        path = dir_json / f"{base}-{stamp}_{counter}.json"
        counter += 1
    record = {
        "version": 1,
        "dir": str(directory.resolve()),
        "created": now.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label or "",
        "count": len(files),
        "files": files,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            jsonlib.dump(record, f, ensure_ascii=False, indent=1)
    except OSError as e:
        raise OperationError(f"{path}: {e}")

    cprint(f"Instantanea guardada: {path} "
           f"({len(files)} archivo(s), {_human_size(path.stat().st_size)}).")

    if keep > 0:
        olds = _snapshot_files_of(dir_json)[:-keep]
        for old in olds:
            try:
                old.unlink()
                cprint(f"  Antigua purgada: {old.name}")
            except OSError:
                pass


def _match_name_any(name: str, patterns: list) -> bool:
    """True si el nombre encaja con algun patron _match_name (lista de extensiones)."""
    return any(_match_name(name, p) for p in patterns)


def _diff_snapshots(old: dict, new: dict, ext_filter: str = "*"):
    """Calcula creados/borrados/modificados/renombrados entre dos inventarios."""
    old_f, new_f = old["files"], new["files"]
    comunes = old_f.keys() & new_f.keys()
    creados = sorted(new_f.keys() - old_f.keys())
    borrados = sorted(old_f.keys() - new_f.keys())

    modificados = []
    for rel in sorted(comunes):
        o, n = old_f[rel], new_f[rel]
        if o["size"] != n["size"] or o.get("sha256") != n.get("sha256"):
            modificados.append(rel)

    # Renombrados/movidos: mismo hash (tamano+hash si no se hahea) en rutas distintas
    moved_pairs = []
    if borrados and creados:
        def key(e):
            return (e.get("sha256") or ("", e["size"]), e["size"])
        by_hash_old = {}
        for rel in borrados:
            by_hash_old.setdefault(key(old_f[rel]), []).append(rel)
        asignados = set()
        for rel in creados:
            grupo = by_hash_old.get(key(new_f[rel]))
            if not grupo:
                continue
            src = next((r for r in grupo if r not in asignados), None)
            if src is None:
                continue
            asignados.add(src)
            moved_pairs.append((src, rel))
        borrados = [r for r in borrados if r not in asignados]
        creados = [r for r in creados if r not in set(m for _, m in moved_pairs)]

    if ext_filter != "*":
        modificados = [r for r in modificados if _match_name_any(Path(r).name, [ext_filter])]
        creados = [r for r in creados if _match_name_any(Path(r).name, [ext_filter])]
        borrados = [r for r in borrados if _match_name_any(Path(r).name, [ext_filter])]
        moved_pairs = [(a, b) for a, b in moved_pairs
                       if _match_name_any(Path(b).name, [ext_filter])]

    moved_pairs.sort(key=lambda p: p[0])
    return {"created": creados, "deleted": borrados, "modified": modificados,
            "moved": moved_pairs,
            "unchanged": len(comunes) - len(modificados)}


def snapshot_diff(directory: Path, name: str = None, dry_run: bool = False,
                  ext: str = "*", latest: bool = False):
    """Compara el directorio actual con una instantanea (la ultima por defecto).

    Con 'latest=True' compara las dos ultimas instantaneas guardadas.
    Detecta creados/borrados/modificados y renombrados-movidos (por hash).
    Solo lectura: no modifica archivos. Con --dry-run solo muestra el resumen.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))
    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    files = _resolve_snapshot_files(directory, None if latest else name)
    if latest:
        files = _snapshot_files_of(_snapshot_root() / _snapshot_slug(directory))
        if len(files) < 2:
            raise InvalidArgumentError(
                f"hay {len(files)} instantanea(s) de {directory}; se necesitan al menos 2 "
                "para comparar (crea otra con 'snapshot')")
        old_snap = _load_snapshot(files[-2])
        new_snap = _load_snapshot(files[-1])
        cprint(f"Compara instantáneas de {directory}: "
               f"{files[-2].stem} -> {files[-1].stem}")
    else:
        old_snap = _load_snapshot(files[-1])
        new_snap = {"files": _inventory_directory(directory)}
        cprint(f"Directorio {directory} vs instantánea {files[-1].name} "
               f"({old_snap.get('created', 'sin fecha')}):")

    d = _diff_snapshots(old_snap, new_snap, ext_filter=ext)
    for rel in d["created"]:
        cprint(f"  + Añadido: {rel}")
    for rel in d["modified"]:
        cprint(f"  ~ Modificado: {rel}")
    for rel in d["deleted"]:
        cprint(f"  - Eliminado: {rel}")
    for src, dst in d["moved"]:
        cprint(f"  > Movido/renombrado: {src} -> {dst}")

    partes = [f"+{len(d['created'])}", f"~{len(d['modified'])}",
              f"-{len(d['deleted'])}",
              f">{len(d['moved'])} movido(s)", f"={d['unchanged']} sin cambios"]
    if any(parte not in ("+0", "~0", "-0") for parte in partes[:3]) or d["moved"]:
        cprint(f"\nResumen: {'; '.join(partes)}.")
    else:
        cprint("\nSin cambios desde la instantánea.")
    if dry_run:
        cprint("[DRY-RUN] Solo lectura: no se ha modificado nada.")


def snapshot_list(directory: Path = None, dry_run: bool = False):
    """Lista las instantaneas guardadas (todas los directorios o las de uno)."""
    root = _snapshot_root()
    if not root.exists():
        cprint(f"No hay instantaneas (carpeta {root} vacia o inexistente). "
               "Crea la primera con 'snapshot <directorio>'.")
        return

    if directory:
        dirs = [_snapshot_slug(directory)]
    else:
        dirs = sorted(p.name for p in root.iterdir() if p.is_dir())

    total = 0
    for slug in dirs:
        dir_json = root / slug
        files = _snapshot_files_of(dir_json)
        if not files:
            continue
        first = _load_snapshot(files[0]).get("dir", slug)
        cprint(f"{first} ({len(files)} instantanea(s)):")
        for p in files:
            try:
                snap = _load_snapshot(p)
            except FsortError:
                cprint(f"  - {p.name}  (ilegible)")
                continue
            extra = f" — {snap['label']}" if snap.get("label") else ""
            cprint(f"  - {p.name}  {snap.get('created', '?')}  "
                   f"({snap.get('count', '?')} archivo(s), "
                   f"{_human_size(p.stat().st_size)}){extra}")
            total += 1
    if not total:
        where = f" para {directory}" if directory else ""
        cprint(f"No hay instantaneas{where}. Crea alguna con 'snapshot <directorio>'.")
        return
    cprint()
    cprint(f"{total} instantanea(s) en {root}. Usa 'diff <directorio> [nombre]' "
           "para comparar (sin nombre, contra la ultima).")


def _extract_actions_file(argv: list):
    """Extrae el valor de --actions-file de argv sin usar argparse (argparse lo confundiría con --actions)."""
    path = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--actions-file":
            if i + 1 < len(argv):
                path = argv[i + 1]
                i += 2
                continue
            i += 1
            continue
        if a.startswith("--actions-file="):
            path = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return path, rest


def _extract_assistant(argv: list):
    """Extrae el texto de --ai/--pregunta (o --ia) de argv, sin usar argparse.

    Si '--ai' aparece sin texto, devuelve '' (cadena vacía) para indicar que se
    debe preguntar de forma interactiva.
    """
    text = None
    rest = []
    i = 0
    flags = ("--ai", "--ia", "--pregunta", "--pregunta-ia", "-P")
    prefixes = ("--ai=", "--ia=", "--pregunta=", "--pregunta-ia=", "-P=")
    while i < len(argv):
        a = argv[i]
        if a in flags:
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is not None and not nxt.startswith("-"):
                text = nxt
                i += 2
                continue
            if text is None:
                text = ""
            i += 1
            continue
        if a.startswith(prefixes):
            text = a.split("=", 1)[1] or ""
            i += 1
            continue
        rest.append(a)
        i += 1
    return text, rest


def _ssl_context():
    """Devuelve un SSLContext que confía en el CA de Simarro si está disponible."""
    ca = Path(os.environ.get("FSORT_AI_CA", Path.home() / ".config/opencode/ca-simarro.crt"))
    ca = Path(ca).expanduser() if not os.environ.get("FSORT_AI_CA") else Path(ca)
    if ca.exists():
        ctx = ssl.create_default_context(cafile=str(ca))
    else:
        ctx = ssl.create_default_context()
    if os.environ.get("FSORT_AI_INSECURE") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _ai_config() -> dict:
    return {
        "base_url": os.environ.get("FSORT_AI_URL", "https://ia.simarro/llmapi/v1"),
        "api_key": os.environ.get("FSORT_AI_KEY", ""),
        "model": os.environ.get("FSORT_AI_MODEL", "Qwen38-DualSpark-medium"),
    }


def ask_ai(question: str, system_prompt: str = AI_SYSTEM_PROMPT) -> str:
    """Envía la pregunta a la IA de Simarro (API OpenAI-compatible) y devuelve su respuesta."""
    cfg = _ai_config()
    if not cfg["api_key"]:
        raise AIError("falta la clave de API. Define FSORT_AI_KEY con tu clave "
                      "(ej: export FSORT_AI_KEY='sk-...')")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})
    body = jsonlib.dumps({
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.6,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    })
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=120) as resp:
            payload = jsonlib.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            detail += " — revisa que FSORT_AI_KEY sea correcta"
        raise AIError(f"HTTP {e.code} al consultar {url}: {detail}")
    except urllib.error.URLError as e:
        raise AIError(f"no se pudo conectar con {url} ({e.reason}). "
                      "Comprueba tu conexión y FSORT_AI_URL")
    except jsonlib.JSONDecodeError as e:
        raise AIError(f"respuesta no es JSON válido: {e}")

    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"respuesta inesperada de la API: {e}")


def ai_assistant(question: str):
    """Modo asistente (--ai): pregunta a la IA de Simarro y muestra la respuesta."""
    cprint(f"Consultando la IA de Simarro ({_ai_config()['model']})...\n")
    cprint(ask_ai(question))
    cprint()


def _is_dry(args, extra: list) -> bool:
    """Detecta el modo simulación en cualquier posición (argparse o extra)."""
    return bool(getattr(args, "dry_run", False)) or "-d" in extra or "--dry-run" in extra


def main():
    pre_ai, rest_argv = _extract_assistant(sys.argv[1:])
    actions_file, rest_argv = _extract_actions_file(rest_argv)
    actions_path = Path(actions_file).expanduser() if actions_file else ACTIONS_FILE
    try:
        actions = load_actions(actions_path)
    except ActionsValidationError as e:
        cprint(f"✗ Error: {e.message} ({e.detail}):")
        for err in e.errors:
            cprint(f"  - {err}")
        cprint("\nCorrige el archivo de acciones y vuelve a intentarlo.")
        raise SystemExit(1)
    except FsortError as e:
        _print_error(e)
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="Ejecuta comandos definidos en actions.json (ordenar, vaciar, mover, info, ...) "
                    "o consulta la IA de Simarro.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s <comando> [args...]   # Ejecuta un comando de actions.json
  %(prog)s ordenar ~/Descargas   # Ordena archivos por extensión
  %(prog)s info ~/Descargas      # Lista el directorio
  %(prog)s descomprimir-a a.zip ./out # Extrae el ZIP en ./out
  %(prog)s --actions             # Lista los comandos disponibles
  %(prog)s ordenar . --dry-run   # Simula sin aplicar cambios
  %(prog)s --ai "¿Cómo ordeno mis descargas?"  # Pregunta a la IA de Simarro
        """
    )
    parser.add_argument("command", nargs="*", metavar="COMANDO",
                        help="Comando de actions.json seguido de sus argumentos")
    parser.add_argument("--actions-file", metavar="RUTA", default=None,
                        help="Usar un actions.json alternativo (por defecto, actions.json junto al script)")
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Simular la operación sin mover/copiar archivos")
    parser.add_argument("--actions", action="store_true",
                        help="Listar los comandos personalizados de actions.json")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="No pedir confirmacion en acciones destructivas "
                             "(equivale a FSORT_YES=1)")
    parser.add_argument("--ai", "--ia", "--pregunta", "-P", metavar="TEXTO",
                        nargs="?", const="", default=None,
                        help="Pregunta a la IA de Simarro y muestra la respuesta "
                             "(requiere FSORT_AI_KEY; alias: -P/--ia/--pregunta)")

    args, extra = parser.parse_known_args(rest_argv)

    # --yes/-y global: confirma acciones destructivas sin preguntar
    if getattr(args, "yes", False):
        os.environ["FSORT_YES"] = "1"

    # Combinar --ai/--ia/--pregunta: puede venir de argparse o del preprocesador.
    question = args.ai if args.ai is not None else pre_ai
    if question is not None:
        if _is_dry(args, extra):
            cprint(f"[DRY-RUN] Consultaría la IA de Simarro con la pregunta: "
                  f"'{question.strip() or '(interactiva)'}'")
            return
        if not question.strip():
            try:
                question = input("Pregunta para la IA: ")
            except EOFError:
                cprint("✗ Error: no se recibió ninguna pregunta. "
                      "Pásala como texto: fsort.py --ai \"tu pregunta\"",
                      file=sys.stderr)
                raise SystemExit(1)
            if not question.strip():
                cprint("✗ Error: la pregunta no puede estar vacía.", file=sys.stderr)
                raise SystemExit(1)
        try:
            ai_assistant(question.strip())
        except AIError as e:
            _print_error(e)
            raise SystemExit(1)
        return

    if not args.actions and not args.command:
        parser.error("falta el comando (usa --actions para ver los disponibles)")

    try:
        dispatch(args, extra, actions)
    except SystemExit:
        raise
    except (FsortError, InvalidArgumentError) as e:
        _print_error(e)
        raise SystemExit(1)
    except Exception as e:
        cprint(f"✗ Error inesperado ({e.__class__.__name__}): {e} "
              "(revisa el comando o ejecuta con --actions para ver los disponibles)")
        raise SystemExit(1)


def _print_error(exc: FsortError):
    cprint(f"✗ Error: {exc}")
    hint = _suggest(str(exc))
    if hint:
        cprint(f"  Sugerencia:{hint}")


def dispatch(args, extra: list, actions: dict):
    # Las acciones ya se validaron (estructura, marcadores y funciones) al cargar el
    # JSON en main()/load_actions(); no hace falta revalidar aqui (evita re-importar
    # fsort.py por cada accion, que era el coste de la doble validacion).
    if args.actions:
        if not actions:
            cprint("No hay acciones definidas en actions.json.")
        else:
            cprint("Acciones disponibles (actions.json):")
            for name, action in actions.items():
                desc = action.get("description", "") if isinstance(action, dict) else ""
                cprint(f"  {name}: {desc}")
        return

    command, *action_args = args.command
    action_args.extend(extra)

    if command not in actions:
        disponible = ", ".join(sorted(actions)) or "ninguna"
        cprint(f"✗ Error: el comando '{command}' no existe en actions.json. "
              f"Comandos disponibles: {disponible}.")
        raise SystemExit(1)

    dry_run = _is_dry(args, extra)
    if dry_run and "-d" in extra:
        action_args.remove("-d")

    action = actions[command]
    if not isinstance(action, dict):
        raise InvalidActionError(
            f"la acción '{command}' debe ser un objeto JSON, "
            f"no '{type(action).__name__}'")

    action_type = action.get("type")
    if action_type == "python":
        if action.get("func") == "move_items":
            example = f"fsort.py {command} <elemento1> [elemento2 ...] <destino>"
        elif action.get("func") == "flatten_dir":
            example = f"fsort.py {command} <directorio> <destino>"
        elif action.get("func") == "largest_files":
            example = f"fsort.py {command} <directorio> [top]"
        elif action.get("func") == "oldest_files":
            example = f"fsort.py {command} <directorio> [top]"
        elif action.get("func") == "aged_files":
            example = f"fsort.py {command} <directorio> [días]"
        elif action.get("func") == "find_duplicates":
            example = f"fsort.py {command} <directorio>"
        elif action.get("func") == "empty_trash":
            example = f"fsort.py {command} [papelera]"
        elif action.get("func") == "summarize_file":
            example = f"fsort.py {command} <archivo> [destino.txt]"
        elif action.get("func") == "sync_dirs":
            example = f"fsort.py {command} <origen> [destino]"
        elif action.get("func") == "extract_archive":
            example = f"fsort.py {command} <archivo> [destino]"
        elif action.get("func") == "undo_clean":
            example = f"fsort.py {command} [--dry-run | --yes]"
        elif action.get("func") == "dir_snapshot":
            example = f"fsort.py {command} <directorio> [nombre]"
        elif action.get("func") == "snapshot_diff":
            example = f"fsort.py {command} <directorio> [nombre] [--latest]"
        elif action.get("func") == "snapshot_list":
            example = f"fsort.py {command} [directorio]"
        else:
            example = f"fsort.py {command} <directorio>"
    elif action_type == "command":
        example = f"fsort.py {command} [arg...] (los argumentos sustituyen a {{1}}, {{2}}, ...)"
    else:
        example = ""

    try:
        run_action(command, action, action_args, dry_run)
    except (InvalidArgumentError, DirectoryNotFoundError, DestinationNotFoundError) as e:
        _print_error(e)
        if example:
            cprint(f"  Ejemplo: {example}")
        raise SystemExit(1)
    except FsortError as e:
        _print_error(e)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
