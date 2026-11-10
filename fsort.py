#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from config import ACTIONS_FILE, ActionsFileInvalidError, ActionsFileNotFoundError, ActionsValidationError, validate
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
    """Carga y valida (solo estructura) las acciones definidas en actions.json."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ActionsFileNotFoundError(str(path))
    except json.JSONDecodeError as e:
        raise ActionsFileInvalidError(f"{path} (línea {e.lineno}, columna {e.colno}): {e.msg}")

    validate._skip_funcs = True
    try:
        errors = validate(data)
    finally:
        del validate._skip_funcs
    if errors:
        raise ActionsValidationError([f"{path}: {err}" for err in errors])

    return data.get("actions", {})


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


def main():
    try:
        actions = load_actions()
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
