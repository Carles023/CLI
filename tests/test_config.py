"""Tests de la validacion de actions.json (config.py)."""
import pytest

from fsort import config
from fsort.errores import ActionsValidationError


def _data(actions):
    return {"actions": actions}


def test_validar_accion_command_correcta():
    errs = config.validate(_data({"info": {
        "description": "info", "type": "command", "command": "ls {1}"}}))
    assert errs == []


def test_validar_falta_description():
    errs = config.validate(_data({"x": {"type": "command", "command": "ls"}}))
    assert any("description" in e for e in errs)


def test_validar_type_invalido():
    errs = config.validate(_data({"x": {"description": "d", "type": "magia",
                                        "command": "ls"}}))
    assert any("type" in e and "valor inv" in e for e in errs)


def test_validar_python_sin_func():
    errs = config.validate(_data({"x": {"description": "d", "type": "python"}}))
    assert any("func" in e for e in errs)


def test_validar_python_func_inexistente():
    errs = config.validate(_data({"x": {"description": "d", "type": "python",
                                        "func": "funcion_que_no_existe"}}))
    assert any("funcion_que_no_existe" in e for e in errs)


def test_validar_python_func_existente():
    errs = config.validate(_data({"x": {"description": "d", "type": "python",
                                        "func": "sort_files"}}))
    assert errs == []


def test_validar_command_sin_command():
    errs = config.validate(_data({"x": {"description": "d", "type": "command"}}))
    assert any("command" in e for e in errs)


def test_validar_marcadores_no_consecutivos():
    errs = config.validate(_data({"x": {"description": "d", "type": "command",
                                        "command": "mv {1} {3}"}}))
    assert any("consecutivos" in e for e in errs)


def test_validar_campos_desconocidos():
    errs = config.validate(_data({"x": {"description": "d", "type": "command",
                                        "command": "ls", "extra": 1}}))
    assert any("extra" in e and "no reconocido" in e for e in errs)


def test_validar_arrel_no_dict():
    errs = config.validate([1, 2])
    assert errs and "objeto JSON" in errs[0]


def test_validar_sin_actions():
    errs = config.validate({})
    assert errs and "actions" in errs[0]


def test_validar_actions_buit():
    errs = config.validate(_data({}))
    assert any("no puede estar vac" in e for e in errs)


def test_check_actions_revalida_mapa():
    errs = config.check_actions({"x": {"description": "d", "type": "python"}})
    assert any("func" in e for e in errs)


def test_load_and_validate_archivo_invalido(tmp_path):
    p = tmp_path / "acc.json"
    p.write_text('{"actions": {"x": {"type": "python"}}}', encoding="utf-8")
    with pytest.raises(ActionsValidationError):
        config.load_and_validate(p)


def test_load_and_validate_archivo_inexistente(tmp_path):
    from fsort.errores import ActionsFileNotFoundError
    with pytest.raises(ActionsFileNotFoundError):
        config.load_and_validate(tmp_path / "no_existe.json")


def test_load_and_validate_actions_json_real():
    """El actions.json del repo debe pasar la validacion completa."""
    actions = config.load_and_validate()
    assert "ordenar" in actions
    assert "mover" in actions
