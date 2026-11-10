#!/usr/bin/env python3
"""Excepciones personalizadas de fsort."""


class FsortError(Exception):
    """Error base de fsort."""

    message = "Error no especificado"

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.message}: {self.detail}" if self.detail else self.message


class ActionsFileNotFoundError(FsortError):
    """El archivo actions.json no existe."""

    message = "No se encuentra el archivo de acciones"


class ActionsFileInvalidError(FsortError):
    """El archivo actions.json no es un JSON válido."""

    message = "JSON inválido en el archivo de acciones"


class ActionsValidationError(FsortError):
    """La estructura de actions.json no pasa la validación."""

    message = "Validación de acciones fallida"

    def __init__(self, errors: list):
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} error(es)")


class ActionTypeError(FsortError):
    """El tipo de acción no es compatible."""

    message = "Tipo de acción desconocido"


class ActionCommandMissingError(FsortError):
    """La acción no define un comando."""

    message = "La acción no tiene comando"


class ActionFuncMissingError(FsortError):
    """La acción de tipo 'python' no define la función a ejecutar."""

    message = "La acción no define la función a ejecutar"


class ActionFuncNotFoundError(FsortError):
    """La función indicada en la acción no existe en fsort.py."""

    message = "La función de la acción no existe"


class DirectoryNotFoundError(FsortError):
    """El directorio indicado no existe."""

    message = "El directorio no existe"


class NotADirectoryError_(FsortError):
    """La ruta indicada no es un directorio."""

    message = "La ruta no es un directorio"


class DestinationNotFoundError(FsortError):
    """El destino de un movimiento no existe."""

    message = "El destino no existe"


class OperationError(FsortError):
    """Error al mover, copiar o eliminar un archivo."""

    message = "Error al procesar el archivo"
