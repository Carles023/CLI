"""Tests de las excepciones personalizadas."""
from fsort import errores


def test_clases_distintas_y_message():
    assert issubclass(errores.FsortError, Exception)
    assert errores.DirectoryNotFoundError("x").message == "El directorio no existe"


def test_str_con_detalle():
    e = errores.OperationError("sin permisos")
    assert str(e) == "Error al procesar el archivo: sin permisos"


def test_str_sin_detalle():
    assert str(errores.FsortError()) == "Error no especificado"


def test_actions_validation_error_lista():
    e = errores.ActionsValidationError(["a", "b", "c"])
    assert len(e.errors) == 3
    assert "3 error" in e.detail


def test_sin_duplicados_en_modulo():
    """FileReadError no debe estar duplicada en el modulo (bug historico)."""
    import inspect
    src = inspect.getsource(errores)
    assert src.count("class FileReadError") == 1
