"""fsort — CLI para organizar archivos según su extensión."""
try:
    from importlib.metadata import version as _version
    __version__ = _version("fsort")
except Exception:
    # Paquete no instalado (ej. ejecución desde el repo): version de desarrollo.
    __version__ = "1.0.0"
