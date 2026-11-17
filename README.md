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
| `duplicados` | Detecta archivos duplicados (mismo contenido) en un directorio mostrando los grupos y el espacio recuperable | `fsort.py duplicados <directorio>` |
| `duplicados-eliminar` | Detecta archivos duplicados y, en interactivos, deja elegir qué copia conservar de cada grupo (por defecto conserva el más antiguo y elimina el resto) | `fsort.py duplicados-eliminar <directorio>` |
| `mas-grandes` | Lista los archivos más grandes de un directorio (top N, por defecto 10). Acepta 'top' como segundo argumento | `fsort.py mas-grandes <directorio> [top]` |
| `mas-grandes-eliminar` | Igual que 'mas-grandes' pero elimina los N archivos más grandes. Usa --dry-run para simular | `fsort.py mas-grandes-eliminar <directorio> [top]` |
| `vaciar-papelera` | Muestra el contenido de la papelera (por defecto ./trash o FSORT_TRASH_DIR) sin borrar | `fsort.py vaciar-papelera [papelera]` |
| `vaciar-papelera-ya` | Vacía la papelera eliminando permanentemente su contenido. Acepta la papelera como argumento opcional. Usa --dry-run para simular | `fsort.py vaciar-papelera-ya [papelera]` |
| `resumir` | Resume con la IA de Simarro el contenido de un archivo de texto (txt, md, pdf, docx, odt, csv, html...) y lo guarda en <archivo>_resumen.txt o en el destino indicado | `fsort.py resumir <archivo> [destino.txt]` |
| `ai` | Consulta la IA de Simarro. Pasa la pregunta como argumento (o usa --ai). Requiere FSORT_AI_KEY | `fsort.py ai "tu pregunta"` |

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
| `--actions-file RUTA` | Usa un `actions.json` alternativo (por defecto, el del script) |
| `-h, --help` | Muestra la ayuda |

## IA de Simarro

Configuración por variables de entorno:

| Variable | Descripción | Por defecto |
| --- | --- | --- |
| `FSORT_AI_KEY` | Clave de API (obligatoria) | — |
| `FSORT_AI_URL` | URL base de la API compatible con OpenAI | `https://ia.simarro/llmapi/v1` |
| `FSORT_AI_MODEL` | Modelo a usar | `Qwen38-DualSpark-medium` |
| `FSORT_AI_CA` | Ruta al certificado CA de Simarro | `~/.config/opencode/ca-simarro.crt` |
| `FSORT_AI_INSECURE` | `1` para desactivar la verificación TLS | desactivado |

```bash
export FSORT_AI_KEY='sk-...'
python3 fsort.py --ai "¿Cómo busco duplicados en ~/Descargas?"
python3 fsort.py ai "¿Qué comando uso para vaciar subcarpetas?"
python3 fsort.py resumir informe.pdf            # -> informe_resumen.txt
python3 fsort.py resumir paper.docx resumen.txt # destino a medida
```

### `resumir`

Extrae el texto del archivo, envía-lo a la IA de Simarro y guarda el resultado en un `.txt`
con cabecera (nombre, fecha, modelo, aviso de truncado si aplica).

- **Formatos**: texto (`.txt .md .rst .log .csv .tsv .json .xml .html .tex .py .sh .yml`...),
  `.pdf` (usa `pdftotext`), `.docx .odt .rtf .org` (usa `pandoc`).
- **Límite de entrada**: 12.000 caracteres por defecto (configurable amb
  `FSORT_SUMMARY_MAX_CHARS`). Si el archivo es más largo, se trunca y se avisa al resumen.
- **Salida**: junto al original (`<stem>_resumen.txt`) o en la ruta indicada
  (siempre `.txt`). Si ya existe, se crea `<stem>_resumen_1.txt`, etc. — nunca sobrescribe.
- **Estructura**: `RESUMEN EJECUTIVO` / `PUNTOS CLAVE` / `CONCLUSIONES`, en el idioma del documento.
- `--dry-run` no consume tokens: solo dice qué haría.

La IA responde en el idioma de la pregunta y propone comandos `fsort.py` reales.

## Errores

`actions.json` se valida **antes** de ejecutar cualquier comando (estructura, campos, marcadores `{n}` y existencia de las funciones `func`). Si algo falla, la terminal muestra el porqué con una sugerencia de solución:

```
✗ Error: El directorio no existe: descargss
  Sugerencia: Comprueba la ruta; si el directorio aún no existe, créalo antes.
  Ejemplo: fsort.py ordenar <directorio>
```

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
