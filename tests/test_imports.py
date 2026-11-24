"""No-regresion: el paquete debe importar e instalarse sin depender del cwd.

Bug historico: 'from config import ...' solo funcionaba ejecutando fsort.py
desde el directorio del repo; con un symlink global o 'python -m fsort'
desde otra ruta fallaba con ModuleNotFoundError.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_extra(**kw):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(kw)
    return env


def test_import_paquete_desde_otro_cwd(tmp_path):
    r = subprocess.run([sys.executable, "-c", "import fsort.fsort, fsort.config, fsort.errores"],
                       cwd=str(tmp_path), env=_env_extra(), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_run_module_desde_otro_cwd(tmp_path):
    r = subprocess.run([sys.executable, "-m", "fsort", "--actions"],
                       cwd=str(tmp_path), env=_env_extra(), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ordenar" in r.stdout


def test_script_shim_fuera_del_repo(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "fsort.py"), "--actions"],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ordenar" in r.stdout


def test_config_usa_actions_json_del_repo():
    from fsort import config
    assert config.ACTIONS_FILE.name == "actions.json"
    assert config.ACTIONS_FILE.exists()


def test___main___expone_main():
    from fsort.__main__ import main  # noqa: F401  (entry point del script consola)
