#!/usr/bin/env python3
import argparse
import os
import shutil
from pathlib import Path


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
    files = [f for f in files if f.name != script_name and f.name != "sort_files_by_ext.py"]
    
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


def main():
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
    
    args = parser.parse_args()
    directory = Path(args.directory).expanduser().resolve()
    
    sort_files(directory, dry_run=args.dry_run, copy=args.copy, recursive=args.recursive)


if __name__ == "__main__":
    main()
