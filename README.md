# Ordenador de Archivos por Extensión

Una herramienta CLI simple para organizar automáticamente tus archivos en carpetas según su extensión.

## Características

- Organiza archivos por extensión en carpetas separadas (ej., `jpg/`, `pdf/`, `txt/`)
- Soporta modo simulación (`--dry-run`) para previsualizar cambios
- Puede copiar en lugar de mover (`--copy`)
- Soporta modo recursivo para procesar subdirectorios (`--recursive`)
- Maneja archivos sin extensión en una carpeta `sin_extension/`
- Evita colisiones de nombres añadiendo un contador

## Uso

```bash
# Ordenar archivos en el directorio actual
python3 sort_files_by_ext.py

# Ordenar archivos en un directorio específico
python3 sort_files_by_ext.py ~/Descargas

# Simular sin aplicar cambios
python3 sort_files_by_ext.py . --dry-run

# Copiar en lugar de mover
python3 sort_files_by_ext.py ~/Documentos --copy

# Procesar recursivamente
python3 sort_files_by_ext.py . --recursive
```

## Opciones

| Opción | Descripción |
| --- | --- |
| `directory` | Directorio a ordenar (opcional, por defecto: `.`) |
| `-d, --dry-run` | Simula la operación sin mover/copiar archivos |
| `-c, --copy` | Copia los archivos en lugar de moverlos |
| `-r, --recursive` | Procesa archivos recursivamente en subdirectorios |
| `-h, --help` | Muestra la ayuda |

## Instalación (opcional)

Para ejecutar como comando global:

```bash
chmod +x sort_files_by_ext.py
sudo ln -s $(pwd)/sort_files_by_ext.py /usr/local/bin/organizar
# Ahora puedes usar: organizar ~/Descargas
```
