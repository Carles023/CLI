# fsort

Una herramienta CLI simple para organizar automáticamente tus archivos en carpetas según su extensión.

## Características

- Organiza archivos por extensión en carpetas separadas (ej., `jpg/`, `pdf/`, `txt/`)
- Soporta modo simulación (`--dry-run`) para previsualizar cambios
- Puede copiar en lugar de mover (`--copy`)
- Soporta modo recursivo para procesar subdirectorios (`--recursive`)
- Maneja archivos sin extensión en una carpeta `sin_extension/`
- Evita colisiones de nombres añadiendo un contador
- Vacía subcarpetas y mueve sus archivos a otro directorio (`--flatten`)

## Uso

```bash
# Ordenar archivos en el directorio actual
python3 fsort.py

# Ordenar archivos en un directorio específico
python3 fsort.py ~/Descargas

# Simular sin aplicar cambios
python3 fsort.py . --dry-run

# Copiar en lugar de mover
python3 fsort.py ~/Documentos --copy

# Procesar recursivamente
python3 fsort.py . --recursive

# Vaciar subcarpetas y juntar sus archivos en otro directorio
python3 fsort.py ~/Descargas --flatten ~/Todos
```

## Opciones

| Opción | Descripción |
| --- | --- |
| `directory` | Directorio a ordenar (opcional, por defecto: `.`) |
| `-d, --dry-run` | Simula la operación sin mover/copiar archivos |
| `-c, --copy` | Copia los archivos en lugar de moverlos |
| `-r, --recursive` | Procesa archivos recursivamente en subdirectorios |
| `-f, --flatten DESTINO` | Vacía las subcarpetas y mueve/copias sus archivos al destino |
| `--keep-empty` | Conserva las subcarpetas vacías al usar `--flatten` |
| `-h, --help` | Muestra la ayuda |

## Instalación (opcional)

Para ejecutar como comando global:

```bash
chmod +x fsort.py
sudo ln -s $(pwd)/fsort.py /usr/local/bin/fsort
# Ahora puedes usar: fsort ~/Descargas
```
