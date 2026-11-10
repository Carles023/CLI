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
- Mueve o copia archivos y carpetas concretos a otro directorio (`--move`)
- Acciones personalizadas definidas fuera del código en `actions.json`

## Acciones personalizadas (actions.json)

Puedes añadir comandos nuevos sin tocar el código editando `actions.json`:

```json
{
  "actions": {
    "info": {
      "description": "Muestra información del directorio",
      "type": "command",
      "command": "ls -lh {1}"
    }
  }
}
```

- `{1}`, `{2}`, ... se sustituyen por los argumentos que pases tras el nombre de la acción.
- Ejecutar: `python3 fsort.py info ~/Descargas`
- Listar las acciones disponibles: `python3 fsort.py --actions`
- Simular: `python3 fsort.py info ~/Descargas --dry-run`
- Validar `actions.json` y ver qué campo falla: `python3 config.py`

### pdf-a-odt

Convierte un PDF a ODT (formato editable de LibreOffice Writer) conservando el PDF original:

```bash
python3 fsort.py pdf-a-odt ~/Documentos/informe.pdf ~/Documentos/odts
```

- `{1}`: ruta del PDF a convertir.
- `{2}`: directorio destino donde se genera el `.odt` (se crea si no existe).
- Requiere LibreOffice (`soffice`) instalado en el sistema.

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

# Mover archivos o carpetas a otro directorio (el último argumento es el destino)
python3 fsort.py --move foto.jpg ~/Documentos pdfs ~/Todos

# Copiar en lugar de mover
python3 fsort.py --move --copy a.txt ~/Backup

# Convertir un PDF a ODT conservando el original
python3 fsort.py pdf-a-odt ~/Documentos/informe.pdf ~/Documentos/odts
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
| `-m, --move ITEM... DESTINO` | Mueve/copía archivos o carpetas al destino (último argumento) |
| `--actions` | Lista las acciones personalizadas de `actions.json` |
| `-h, --help` | Muestra la ayuda |

## Instalación (opcional)

Para ejecutar como comando global:

```bash
chmod +x fsort.py
sudo ln -s $(pwd)/fsort.py /usr/local/bin/fsort
# Ahora puedes usar: fsort ~/Descargas
```
