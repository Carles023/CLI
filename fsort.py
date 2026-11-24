#!/usr/bin/env python3
"""Envoltorio: permite ejecutar 'python3 fsort.py' o un symlink sin instalar el paquete.

Delegate en fsort/__main__.py (el paquete real). Si el paquete no esta accesible
(p. ej. no se puede importar), reintenta anadiendo el directorio del script al sys.path.
"""
import runpy
import sys
from pathlib import Path

_here = str(Path(__file__).resolve().parent)
if _here not in sys.path:
    sys.path.insert(0, _here)

try:
    from fsort.fsort import main as _main
except ImportError:
    _main = None

if __name__ == "__main__":
    if _main is None:
        sys.exit("error: no se encontro el paquete fsort (esperado en ./fsort/)")
    _main()
