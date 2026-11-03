#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ACTIONS_FILE = Path(__file__).parent / "actions.json"


def load_actions(path: Path = ACTIONS_FILE) -> dict:
    """Carga las acciones definidas fuera del código en actions.json."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("actions", {})
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error al leer {path}: {e}")
        return {}


def run_action(name: str, action: dict, args: list, dry_run: bool = False):
    """Ejecuta una acción definida en el JSON. Soporta tipo 'command'."""
    if action.get("type", "command") != "command":
        print(f"Error: tipo de acción desconocido '{action.get('type')}'.")
        return

    command = action.get("command")
    if not command:
        print(f"Error: la acción '{name}' no tiene comando.")
        return

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
        print(f"Error: {e}")


def sort_files(directory: Path, dry_run: bool = False, copy: bool = False, recursive: bool = False):
    """
    Ordena archivos en un directorio por su extensión.
    Crea una carpeta por extensión y mueve/copia los archivos.
    """
    if not directory.exists():
        print(f"Error: El directorio {directory} no existe.")
        return
    
    if not directory.is_dir():
        print(f"Error: {directory} no es un directorio.")
        return
    
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
            print(f"Error al procesar {file_path.name}: {e}")
    
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
        print(f"Error: El directorio {directory} no existe.")
        return

    if not directory.is_dir():
        print(f"Error: {directory} no es un directorio.")
        return

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
                print(f"Error al procesar {file_path}: {e}")

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
                    print(f"Error al eliminar {subdir}: {e}")

    print(f"\nCompletado: {moved_count} archivo(s) {'copiados' if copy else 'movidos'}.")


def move_items(items: list, dest: Path, dry_run: bool = False, copy: bool = False):
    """
    Mueve (o copia) una lista de archivos o carpetas a un directorio destino.
    """
    if not dest.exists():
        print(f"Error: El destino {dest} no existe. Créalo primero.")
        return

    if not dest.is_dir():
        print(f"Error: {dest} no es un directorio.")
        return

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
            print(f"Error al procesar {path}: {e}")

    if dry_run:
        print("\n[DRY-RUN] Simulación completada. Usa sin --dry-run para aplicar los cambios.")
    else:
        print(f"\nCompletado: {moved_count} elemento(s) {'copiados' if copy else 'movidos'}.")


def main():
    actions = load_actions()
    unknown_args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if unknown_args and unknown_args[0] in actions:
        idx = sys.argv.index(unknown_args[0])
        action_args = [a for a in sys.argv[idx + 1:] if not a.startswith("-")]
        dry_run = "--dry-run" in sys.argv or "-d" in sys.argv
        run_action(unknown_args[0], actions[unknown_args[0]], action_args, dry_run)
        return

    parser = argparse.ArgumentParser(
        description="Ordena archivos por extensión en carpetas separadas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s                    # Ordena archivos en el directorio actual
  %(prog)s ~/Descargas        # Ordena archivos en Descargas
  %(prog)s . --dry-run        # Simula sin mover archivos
  %(prog)s . --copy           # Copia en lugar de mover
  %(prog)s . -r               # También ordena subdirectorios
  %(prog)s ~/Descargas --flatten ~/Todos   # Vacía subcarpetas hacia ~/Todos
  %(prog)s --move foto.jpg docs ~/Todos    # Mueve archivos/carpetas al destino
  %(prog)s --move --copy a.txt ~/Backup    # Copia en lugar de mover

Acciones personalizadas (definidas en actions.json):
  %(prog)s <accion> [args...] # Ej. fsort.py limpiar ~/Descargas
        """
    )
    parser.add_argument("directory", nargs="?", default=".", 
                        help="Directorio a ordenar (por defecto: directorio actual)")
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Simular la operación sin mover/copiar archivos")
    parser.add_argument("-c", "--copy", action="store_true",
                        help="Copiar archivos en lugar de moverlos")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Procesar archivos recursivamente en subdirectorios")
    parser.add_argument("-f", "--flatten", metavar="DESTINO",
                        help="Vaciar subcarpetas y mover/copiar sus archivos al directorio destino")
    parser.add_argument("--keep-empty", action="store_true",
                        help="No eliminar las subcarpetas vacías al usar --flatten")
    parser.add_argument("-m", "--move", nargs="+", metavar="ITEM",
                        help="Mover/copiar archivos o carpetas al directorio destino (último argumento)")
    parser.add_argument("--actions", action="store_true",
                        help="Listar las acciones personalizadas de actions.json")
    
    args = parser.parse_args()

    if args.actions:
        if not actions:
            print("No hay acciones definidas en actions.json.")
        else:
            print("Acciones disponibles (actions.json):")
            for name, action in actions.items():
                desc = action.get("description", "")
                print(f"  {name}: {desc}")
        return

    directory = Path(args.directory).expanduser().resolve()

    if args.move:
        items = args.move[:-1]
        dest = Path(args.move[-1]).expanduser().resolve()
        move_items(items, dest, dry_run=args.dry_run, copy=args.copy)
    elif args.flatten:
        dest = Path(args.flatten).expanduser().resolve()
        flatten_dir(directory, dest, dry_run=args.dry_run, copy=args.copy,
                    remove_empty=not args.keep_empty)
    else:
        sort_files(directory, dry_run=args.dry_run, copy=args.copy, recursive=args.recursive)


if __name__ == "__main__":
    main()
