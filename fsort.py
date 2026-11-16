#!/usr/bin/env python3
import argparse
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from config import ACTIONS_FILE, ActionsFileInvalidError, ActionsFileNotFoundError, ActionsValidationError, load_and_validate
from errores import (
    ActionCommandMissingError,
    ActionFuncMissingError,
    ActionFuncNotFoundError,
    ActionTypeError,
    DestinationNotFoundError,
    DirectoryNotFoundError,
    FsortError,
    NotADirectoryError_,
    OperationError,
)


def load_actions(path: Path = ACTIONS_FILE) -> dict:
    """Carga y valida (estructura y funciones) las acciones definidas en actions.json."""
    return load_and_validate(path)


def run_action(name: str, action: dict, args: list, dry_run: bool = False):
    """Ejecuta una acción definida en el JSON. Soporta tipos 'command' y 'python'."""
    action_type = action.get("type")

    if action_type == "python":
        run_python_action(name, action, args, dry_run)
        return

    if action_type != "command":
        raise ActionTypeError(str(action_type))

    command = action.get("command")
    if not command:
        raise ActionCommandMissingError(name)

    # Sustituir {1}, {2}, ... por los argumentos del usuario
    for i, arg in enumerate(args, 1):
        command = command.replace(f"{{{i}}}", arg)

    if dry_run:
        print(f"[DRY-RUN] Ejecutaría: {command}")
        return

    try:
        result = subprocess.run(shlex.split(command) if os.name != "nt" else command,
                                shell=os.name == "nt")
        sys.exit(result.returncode)
    except FileNotFoundError as e:
        raise OperationError(str(e))


def run_python_action(name: str, action: dict, args: list, dry_run: bool = False):
    """Ejecuta una acción de tipo 'python' llamando a la función indicada en 'func'."""
    func_name = action.get("func")
    if not func_name:
        raise ActionFuncMissingError(name)

    module = sys.modules[__name__]
    func = getattr(module, func_name, None)
    if not callable(func):
        raise ActionFuncNotFoundError(func_name)

    kwargs = dict(action.get("kwargs") or {})
    kwargs["dry_run"] = dry_run

    if func is move_items:
        if len(args) < 2:
            raise ActionCommandMissingError(f"{name} (requiere al menos un elemento y un destino)")
        items = args[:-1]
        dest = Path(args[-1]).expanduser().resolve()
        func(items, dest, **kwargs)
    elif func is empty_trash:
        directory = Path(args[0]).expanduser().resolve() if args else None
        func(directory, **kwargs)
    elif func is largest_files:
        if not args:
            raise DirectoryNotFoundError("(sin directorio: indica el directorio como argumento)")
        directory = Path(args[0]).expanduser().resolve()
        if len(args) > 1:
            kwargs["top"] = args[1]
        func(directory, **kwargs)
    else:
        if not args:
            raise DirectoryNotFoundError("(sin directorio: indica el directorio como argumento)")
        directory = Path(args[0]).expanduser().resolve()
        if func is flatten_dir:
            if len(args) < 2:
                raise DestinationNotFoundError("(sin destino: indica el destino como segundo argumento)")
            dest = Path(args[1]).expanduser().resolve()
            func(directory, dest, **kwargs)
        else:
            func(directory, **kwargs)


def sort_files(directory: Path, dry_run: bool = False, copy: bool = False, recursive: bool = False):
    """
    Ordena archivos en un directorio por su extensión.
    Crea una carpeta por extensión y mueve/copia los archivos.
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
        print("No hay archivos para ordenar.")
        return
    
    moved_count = 0
    for file_path in files:
        # Obtener extensión
        extension = file_path.suffix.lower()
        if not extension:
            ext_folder = "sin_extension"
        else:
            # Quitar el punto y usarlo como nombre de carpeta
            ext_folder = extension[1:]  # ej: .txt -> txt
        
        # Crear carpeta destino
        dest_folder = directory / ext_folder if not recursive else file_path.parent / ext_folder
        dest_file = dest_folder / file_path.name
        
        # Evitar mover archivos que ya están en la carpeta correcta
        if file_path.parent == dest_folder:
            continue
        
        if dry_run:
            action = "Copiaría" if copy else "Movería"
            print(f"[DRY-RUN] {action}: {file_path} -> {dest_file}")
            continue
        
        # Crear directorio si no existe
        dest_folder.mkdir(parents=True, exist_ok=True)
        
        # Manejar colisiones de nombre
        counter = 1
        original_dest = dest_file
        while dest_file.exists():
            stem = original_dest.stem
            suffix = original_dest.suffix
            dest_file = dest_folder / f"{stem}_{counter}{suffix}"
            counter += 1
        
        try:
            if copy:
                shutil.copy2(file_path, dest_file)
                print(f"Copiado: {file_path.name} -> {ext_folder}/")
            else:
                shutil.move(str(file_path), str(dest_file))
                print(f"Movido: {file_path.name} -> {ext_folder}/")
            moved_count += 1
        except Exception as e:
            raise OperationError(f"{file_path}: {e}")
    
    if not dry_run:
        action = "copiados" if copy else "movidos"
        print(f"\nCompletado: {moved_count} archivo(s) {action}.")
    else:
        print("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")


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
        print("No hay subcarpetas que vaciar.")
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
                print(f"[DRY-RUN] {action}: {file_path} -> {dest_file}")
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
                    print(f"Copiado: {file_path.relative_to(directory)} -> {dest_file.name}")
                else:
                    shutil.move(str(file_path), str(dest_file))
                    print(f"Movido: {file_path.relative_to(directory)} -> {dest_file.name}")
                moved_count += 1
            except Exception as e:
                raise OperationError(f"{file_path}: {e}")

    if dry_run:
        print("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")
        return

    if remove_empty and not copy:
        for subdir in sorted(subdirs, key=lambda d: len(d.parts), reverse=True):
            leftovers = [f for f in subdir.rglob("*") if f.is_file()]
            if not leftovers:
                try:
                    shutil.rmtree(subdir)
                    print(f"Eliminada carpeta vacía: {subdir.relative_to(directory)}/")
                except Exception as e:
                    raise OperationError(f"no se pudo eliminar {subdir}: {e}")

    print(f"\nCompletado: {moved_count} archivo(s) {'copiados' if copy else 'movidos'}.")


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
            print(f"Error: {path} no existe.")
            continue

        if path.resolve() == dest:
            print(f"Omitido: {path.name} ya está en el destino.")
            continue

        dest_file = dest / path.name

        if dry_run:
            action = "Copiaría" if copy else "Movería"
            print(f"[DRY-RUN] {action}: {path} -> {dest_file}")
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
                print(f"Copiado: {path.name} -> {dest}/")
            else:
                shutil.move(str(path), str(dest_file))
                print(f"Movido: {path.name} -> {dest}/")
            moved_count += 1
        except Exception as e:
            raise OperationError(f"{path}: {e}")

    if dry_run:
        print("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")
    else:
        print(f"\nCompletado: {moved_count} elemento(s) {'copiados' if copy else 'movidos'}.")


def _human_size(num: float) -> str:
    """Formatea un número de bytes a una unidad legible."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} PB"


def find_duplicates(directory: Path, dry_run: bool = False, delete: bool = False,
                    recursive: bool = True, min_size: int = 1):
    """
    Detecta archivos duplicados (mismo contenido) comparando primero el tamaño y
    luego el hash SHA-256. Agrupa los duplicados y muestra cuáles conservar.
    Con 'delete=True' elimina los redundantes (conserva el más antiguo).
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
        print("No se encontraron archivos duplicados.")
        return

    groups.sort(key=lambda paths: paths[0].stat().st_size * (len(paths) - 1), reverse=True)

    total_groups = len(groups)
    wasted = 0
    deleted_count = 0

    for idx, paths in enumerate(groups, 1):
        size = paths[0].stat().st_size
        # Conservar el más antiguo (menor mtime) como "original"
        paths_sorted = sorted(paths, key=lambda p: p.stat().st_mtime)
        keep, *redundant = paths_sorted
        wasted += size * len(redundant)

        print(f"[{idx}/{total_groups}] {_human_size(size)} c/u — {len(paths)} copias:")
        print(f"  Conservar: {keep}")
        for dup in redundant:
            if delete:
                if dry_run:
                    print(f"  [DRY-RUN] Eliminaría: {dup}")
                    continue
                try:
                    dup.unlink()
                    print(f"  Eliminado: {dup}")
                    deleted_count += 1
                except Exception as e:
                    raise OperationError(f"{dup}: {e}")
            else:
                print(f"  Duplicado: {dup}")

    print()
    if delete:
        if dry_run:
            print(f"[DRY-RUN] {total_groups} grupo(s) de duplicados. "
                  f"Se liberarían {_human_size(wasted)}. "
                  "Usa sin --dry-run para eliminar los duplicados.")
        else:
            print(f"Completado: {deleted_count} archivo(s) duplicado(s) eliminados. "
                  f"Liberado: {_human_size(wasted)}.")
    else:
        print(f"Encontrados {total_groups} grupo(s) de duplicados. "
              f"Espacio recuperable: {_human_size(wasted)}.")
        print("Usa 'duplicados-eliminar' para eliminar los redundantes.")


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
    """Indica si un nombre coincide con un patrón glob que puede ser nombre o *.ext."""
    import fnmatch
    lowered = name.lower()
    p = pattern.lower()
    if p.startswith("*"):
        return lowered.endswith(p[1:])
    return fnmatch.fnmatch(lowered, p)


def largest_files(directory: Path, top: int = 10, dry_run: bool = False,
                  delete: bool = False, ext: str = "*"):
    """
    Lista los archivos más grandes de un directorio (ordenados por tamaño).
    'ext' permite filtrar por extensión (ej: 'pdf'). Con 'delete=True' elimina los N.
    """
    if not directory.exists():
        raise DirectoryNotFoundError(str(directory))

    if not directory.is_dir():
        raise NotADirectoryError_(str(directory))

    try:
        top = int(top)
    except (TypeError, ValueError):
        raise OperationError(f"el número de archivos debe ser un entero, no '{top}'")

    if top <= 0:
        raise OperationError(f"el número de archivos debe ser mayor que 0, no '{top}'")

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
        print("No hay archivos que analizar.")
        return

    entries.sort(key=lambda item: item[0], reverse=True)
    selected = entries[:top]
    total = sum(size for size, _ in selected)

    print(f"Top {len(selected)} archivo(s) más grandes en {directory}"
          + (f" (extensión: {ext})" if ext != "*" else "") + ":")
    for rank, (size, file_path) in enumerate(selected, 1):
        print(f"  {rank:>2}. {_human_size(size):>9}  {file_path}")

    print()
    if delete:
        for size, file_path in selected:
            if dry_run:
                print(f"[DRY-RUN] Eliminaría: {file_path}")
                continue
            try:
                file_path.unlink()
                print(f"Eliminado: {file_path}")
            except Exception as e:
                raise OperationError(f"{file_path}: {e}")

    if delete:
        if dry_run:
            print(f"[DRY-RUN] Se liberarían {_human_size(total)}. "
                  "Usa sin --dry-run para eliminar.")
        else:
            print(f"Completado: liberado {_human_size(total)}.")
    else:
        print(f"Tamaño total de los seleccionados: {_human_size(total)}.")


def empty_trash(directory: Path = None, dry_run: bool = False,
                top: int = 0, delete: bool = False, ext: str = "*"):
    """
    Vacía la papelera eliminando de forma permanente su contenido.
    Por defecto usa FSORT_TRASH_DIR o './trash'. Con 'top=N' solo los N más grandes.
    Con 'delete=False' (vista por defecto) solo lista el contenido sin borrar.
    """
    trash = directory or Path(os.environ.get("FSORT_TRASH_DIR", "trash")).expanduser().resolve()

    if not trash.exists():
        print(f"La papelera ({trash}) no existe. Nada que vaciar.")
        return

    if not trash.is_dir():
        raise NotADirectoryError_(str(trash))

    # Contenido de primer nivel (no la carpeta raíz de la papelera)
    entries = [p for p in trash.iterdir() if _match_name(p.name, ext)]

    if not entries:
        print(f"La papelera ({trash}) ya está vacía.")
        return

    sized = [(_dir_size(p), p) for p in entries]
    sized.sort(key=lambda item: item[0], reverse=True)

    try:
        top = int(top)
    except (TypeError, ValueError):
        raise OperationError(f"el número de archivos debe ser un entero, no '{top}'")

    if top > 0:
        sized = sized[:top]

    do_delete = delete

    if do_delete:
        print(f"Vaciando la papelera ({trash}):")
    else:
        print(f"Contenido de la papelera ({trash}):")

    freed = 0
    count = 0
    for size, entry in sized:
        label = f"{entry.name}/" if entry.is_dir() else entry.name
        if do_delete:
            if dry_run:
                print(f"  [DRY-RUN] Eliminaría: {label} ({_human_size(size)})")
                freed += size
                count += 1
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                print(f"  Eliminado: {label} ({_human_size(size)})")
                freed += size
                count += 1
            except Exception as e:
                raise OperationError(f"{entry}: {e}")
        else:
            print(f"  {label} ({_human_size(size)})")
            freed += size
            count += 1

    print()
    if not do_delete:
        print(f"{count} elemento(s). Total: {_human_size(freed)}. "
              "Usa 'vaciar-papelera-ya' para eliminar el contenido.")
    elif dry_run:
        print(f"[DRY-RUN] {count} elemento(s). Se liberarían {_human_size(freed)}. "
              "Usa sin --dry-run para vaciar la papelera.")
    else:
        print(f"Papelera vaciada: {count} elemento(s) eliminados. Liberado: {_human_size(freed)}.")


def main():
    try:
        actions = load_actions()
    except ActionsValidationError as e:
        print(f"Error: {e.message}: {e.detail}:")
        for err in e.errors:
            print(f"  - {err}")
        raise SystemExit(1)
    except FsortError as e:
        print(f"Error: {e}")
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="Ejecuta comandos definidos en actions.json (ordenar, vaciar, mover, info, ...).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s <comando> [args...]   # Ejecuta un comando de actions.json
  %(prog)s ordenar ~/Descargas   # Ordena archivos por extensión
  %(prog)s info ~/Descargas      # Lista el directorio
  %(prog)s pdf-a-odt a.pdf ./out # Convierte PDF a ODT
  %(prog)s --actions             # Lista los comandos disponibles
  %(prog)s ordenar . --dry-run   # Simula sin aplicar cambios
        """
    )
    parser.add_argument("command", nargs="*", metavar="COMANDO",
                        help="Comando de actions.json seguido de sus argumentos")
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Simular la operación sin mover/copiar archivos")
    parser.add_argument("--actions", action="store_true",
                        help="Listar los comandos personalizados de actions.json")

    args, extra = parser.parse_known_args()

    if not args.actions and not args.command:
        parser.error("falta el comando (usa --actions para ver los disponibles)")

    try:
        dispatch(args, extra, actions)
    except FsortError as e:
        print(f"Error: {e}")
        raise SystemExit(1)


def dispatch(args, extra: list, actions: dict):
    if args.actions:
        if not actions:
            print("No hay acciones definidas en actions.json.")
        else:
            print("Acciones disponibles (actions.json):")
            for name, action in actions.items():
                desc = action.get("description", "")
                print(f"  {name}: {desc}")
        return

    command, *action_args = args.command
    action_args.extend(extra)

    if command not in actions:
        print(f"Error: comando desconocido '{command}'. Usa --actions para ver los disponibles.")
        raise SystemExit(1)

    dry_run = args.dry_run or "-d" in extra
    if dry_run and "-d" in extra:
        action_args.remove("-d")

    run_action(command, actions[command], action_args, dry_run)


if __name__ == "__main__":
    main()
