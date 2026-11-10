# fsort

Una herramienta CLI simple para organizar automáticamente tus archivos en carpetas según su extensión.

## Características

- Organiza archivos por extensión en carpetas separadas (ej., `jpg/`, `pdf/`, `txt/`)
- Soporta modo simulación (`--dry-run`) para previsualizar cambios
- Vacía subcarpetas y mueve sus archivos a otro directorio
- Mueve o copia archivos y carpetas concretos a otro directorio
- Convierte PDF a ODT
- Todos los comandos se definen fuera del código en `actions.json`

## Comandos disponibles (actions.json)

| Comando | Descripción | Uso |
| --- | --- | --- |
| `limpiar` | Mueve archivos temporales y backups a la papelera (ejemplo) | `fsort.py limpiar <arg1>` |
| `info` | Muestra información del directorio | `fsort.py info <arg1>` |
| `tamano` | Muestra el tamaño total de un directorio | `fsort.py tamano <arg1>` |
| `ordenar` | Ordena archivos de un directorio en subcarpetas por extensión | `fsort.py ordenar <directorio>` |
| `ordenar-copiar` | Igual que 'ordenar' pero copia los archivos en lugar de moverlos | `fsort.py ordenar-copiar <directorio>` |
| `ordenar-recursivo` | Ordena archivos por extensión incluyendo subdirectorios | `fsort.py ordenar-recursivo <directorio>` |
| `vaciar` | Vacía las subcarpetas de un directorio moviendo sus archivos al destino indicado ({2}) y elimina las carpetas vacías | `fsort.py vaciar <directorio> <destino>` |
| `vaciar-copiar` | Igual que 'vaciar' pero copia los archivos y conserva las subcarpetas | `fsort.py vaciar-copiar <directorio> <destino>` |
| `mover` | Mueve archivos o carpetas ({1}...{n-1}) al directorio destino (último argumento) | `fsort.py mover <elemento>... <destino>` |
| `mover-copiar` | Copia archivos o carpetas al directorio destino en lugar de moverlos | `fsort.py mover-copiar <elemento>... <destino>` |

## Uso

```bash
# Ejecutar un comando
python3 fsort.py <comando> [argumentos...]

# Ejemplos
python3 fsort.py ordenar ~/Descargas
python3 fsort.py info ~/Documentos
python3 fsort.py mover foto.jpg docs ~/Todos

# Listar los comandos disponibles
python3 fsort.py --actions

# Simular sin aplicar cambios
python3 fsort.py ordenar . --dry-run
```

## Opciones globales

| Opción | Descripción |
| --- | --- |
| `-d, --dry-run` | Simula la operación sin mover/copiar archivos |
| `--actions` | Lista los comandos personalizados de `actions.json` |
| `-h, --help` | Muestra la ayuda |

## Añadir o editar comandos

Todos los comandos viven en `actions.json`, sin lógica en el código:

```json
{
  "info": {
    "description": "Muestra información del directorio",
    "type": "command",
    "command": "ls -lh {1}"
  }
}
```

- `{1}`, `{2}`, ... se sustituyen por los argumentos que pases tras el nombre del comando.
- `type: "command"` ejecuta un comando de shell; `type: "python"` llama a una función de `fsort.py` (indicada en `func`, con flags opcionales en `kwargs`).
- Validar el archivo: `python3 config.py`

## Actualizar este README

```bash
python3 gen_readme.py
```

## Instalación (opcional)

Para ejecutar como comando global:

```bash
chmod +x fsort.py
sudo ln -s $(pwd)/fsort.py /usr/local/bin/fsort
# Ahora puedes usar: fsort ordenar ~/Descargas
```
