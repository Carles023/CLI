"""Punto de entrada: `python -m fsort` y el script consola `fsort`.

Si el paquete no esta en sys.path (p. ej. un symlink directo al launcher),
anade el directorio raiz del proyecto para poder importar `fsort`.
"""
import sys
from pathlib import Path

try:
    from .fsort import main
except ImportError:
    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from fsort.fsort import main

if __name__ == "__main__":
    # `python -m fsort` mostraria '__main__.py' en --version/-h: fuerza el
    # nombre de programa correcto (el consola 'fsort' ya lo trae del PATH).
    if Path(sys.argv[0]).name == "__main__.py":
        sys.argv[0] = "fsort"
    main()
