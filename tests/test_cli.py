"""Tests del CLI (main/run_action) y de utilidades de red/confirmacion."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fsort import fsort
from fsort.errores import AIError, InvalidArgumentError

ROOT = Path(__file__).resolve().parent.parent


def _run(argv, env=None):
    return subprocess.run([sys.executable, str(ROOT / "fsort.py"), *argv],
                          capture_output=True, text=True, env=env, cwd=str(ROOT))


def test_script_acciones():
    r = _run(["--actions"])
    assert r.returncode == 0
    assert "ordenar" in r.stdout


def test_script_comando_inexistente():
    r = _run(["comando-que-no-existe"])
    assert r.returncode == 1
    assert "no existe" in r.stdout


def test_script_ordenar_dry_run(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    r = _run(["ordenar", str(tmp_path), "--dry-run"])
    assert r.returncode == 0
    assert "DRY-RUN" in r.stdout
    assert (tmp_path / "a.txt").exists()


def test_script_actions_file_alternativo(tmp_path):
    acciones = tmp_path / "acciones.json"
    acciones.write_text(json.dumps({"actions": {
        "hola": {"description": "d", "type": "command", "command": "echo hola"}}}),
        encoding="utf-8")
    r = _run(["--actions-file", str(acciones), "--actions"])
    assert r.returncode == 0
    assert "hola" in r.stdout


def test_script_actions_file_invalido_sal_1(tmp_path):
    acciones = tmp_path / "malo.json"
    acciones.write_text('{"actions": {"x": {"type": "python"}}}', encoding="utf-8")
    r = _run(["--actions-file", str(acciones), "x"])
    assert r.returncode == 1


# --- run_action ---------------------------------------------------------------

def test_run_action_faltan_args(tmp_path):
    acc = {"description": "d", "type": "command", "command": "echo {1} {2}"}
    with pytest.raises(InvalidArgumentError):
        fsort.run_action("x", acc, ["solo1"])


def test_run_action_dry_run_no_ejecuta(tmp_path, capsys):
    f = tmp_path / "a.txt"
    f.write_text("x")
    acc = {"description": "d", "type": "command",
           "command": f"mv {f} {tmp_path}/b.txt"}
    fsort.run_action("x", acc, [], dry_run=True)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert f.exists()


def test_run_action_tipo_invalido():
    with pytest.raises(Exception):
        fsort.run_action("x", {"description": "d", "type": "inventado"}, [])


# --- _ai_config / ask_ai ------------------------------------------------------

def test_ai_config_defaults(monkeypatch):
    for var in ("FSORT_AI_URL", "FSORT_AI_MODEL", "FSORT_AI_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = fsort._ai_config()
    assert cfg["base_url"] == "https://ia.simarro/llmapi/v1"
    assert cfg["model"] == "Qwen38-DualSpark-medium"
    assert cfg["api_key"] == ""


def test_ai_config_env(monkeypatch):
    monkeypatch.setenv("FSORT_AI_URL", "https://example.test/v1")
    monkeypatch.setenv("FSORT_AI_MODEL", "otro")
    monkeypatch.setenv("FSORT_AI_KEY", "sk-x")
    cfg = fsort._ai_config()
    assert cfg == {"base_url": "https://example.test/v1", "model": "otro",
                   "api_key": "sk-x"}


def test_ask_ai_sin_key(monkeypatch):
    monkeypatch.delenv("FSORT_AI_KEY", raising=False)
    with pytest.raises(AIError):
        fsort.ask_ai("hola")


def test_ask_ai_json_malformado(monkeypatch):
    monkeypatch.setenv("FSORT_AI_KEY", "sk-x")

    class Resp:
        def read(self):
            return b"no es json"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fsort.urllib.request, "urlopen", lambda *a, **k: Resp())
    with pytest.raises(AIError):
        fsort.ask_ai("hola")


def test_ask_ai_respuesta_ok(monkeypatch):
    monkeypatch.setenv("FSORT_AI_KEY", "sk-x")
    body = json.dumps(
        {"choices": [{"message": {"content": "  respuesta  "}}]}).encode()

    class Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fsort.urllib.request, "urlopen", lambda *a, **k: Resp())
    assert fsort.ask_ai("hola") == "respuesta"


# --- _confirm -----------------------------------------------------------------

def test_confirm_yes_env(monkeypatch):
    monkeypatch.setenv("FSORT_YES", "1")
    assert fsort._confirm() is True


def test_confirm_sin_tty(monkeypatch):
    monkeypatch.delenv("FSORT_YES", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert fsort._confirm() is False


def test_confirm_respuestas(monkeypatch):
    monkeypatch.delenv("FSORT_YES", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    respuestas = iter(["s\n", "si\n", "yes\n", "n\n", "\n", "hola\n"])
    esperadas = [True, True, True, False, False, False]
    monkeypatch.setattr(fsort.sys.stdin, "readline", lambda: next(respuestas))
    for esperado in esperadas:
        assert fsort._confirm() is esperado


# --- helpers ------------------------------------------------------------------

def test_human_size():
    assert fsort._human_size(0) == "0 B"
    assert fsort._human_size(1023) == "1023 B"
    assert fsort._human_size(1024) == "1.0 KB"
    assert fsort._human_size(1024 ** 2) == "1.0 MB"


def test_match_name():
    assert fsort._match_name("foto.JPG", "*.jpg")
    assert fsort._match_name("a.pdf", "pdf")
    assert fsort._match_name("cualquiera", "*")
    assert not fsort._match_name("a.png", "pdf")


def test_sha256_ok(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"contenido")
    import hashlib
    assert fsort._sha256(f) == hashlib.sha256(b"contenido").hexdigest()


def test_sha256_inexistente(tmp_path):
    assert fsort._sha256(tmp_path / "no.bin") is None


def test_ai_defaults_coinciden_con_config():
    """Evita desincronia entre los defaults documentados y los del codigo."""
    from fsort import config
    defaults = dict((v, d) for v, _desc, d in config.AI_ENV_VARS)
    cfg = fsort._ai_config()
    assert defaults["FSORT_AI_URL"] == f"`{cfg['base_url']}`"
    assert defaults["FSORT_AI_MODEL"] == f"`{cfg['model']}`"


# --- sustitucion segura de marcadores (injeccion de shell) --------------------

def _capture_run(monkeypatch):
    vistos = {}

    def fake_run(argv, **kw):
        vistos["argv"] = argv

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(fsort.subprocess, "run", fake_run)
    return vistos


def test_injeccion_argumento_neutro(tmp_path, monkeypatch):
    """Un argumento con ; rm -rf viaja como UN token: no se ejecuta como orden."""
    vistos = _capture_run(monkeypatch)
    monkeypatch.setattr(fsort.sys, "exit", lambda code=0: None)
    acc = {"description": "d", "type": "command", "command": "echo {1}"}
    veneno = "hola; rm -rf /"
    fsort.run_action("x", acc, [veneno])
    assert vistos["argv"] == ["echo", veneno]


def test_comando_se_ejecuta_como_argv_no_shell(tmp_path, monkeypatch):
    vistos = _capture_run(monkeypatch)
    acc = {"description": "d", "type": "command", "command": "ls -lh {1}"}
    monkeypatch.setattr(fsort.sys, "exit", lambda code=0: None)
    fsort.run_action("info", acc, [str(tmp_path)])
    assert vistos["argv"] == ["ls", "-lh", str(tmp_path)]


def test_espacios_en_argumento_un_solo_token(tmp_path, monkeypatch):
    vistos = _capture_run(monkeypatch)
    d = tmp_path / "mi carpeta"
    d.mkdir()
    acc = {"description": "d", "type": "command", "command": "ls -lh {1}"}
    monkeypatch.setattr(fsort.sys, "exit", lambda code=0: None)
    fsort.run_action("info", acc, [str(d)])
    assert vistos["argv"] == ["ls", "-lh", str(d)]


def test_dry_run_muestra_shlex_quote(tmp_path, capsys):
    acc = {"description": "d", "type": "command", "command": "ls {1}"}
    fsort.run_action("info", acc, ["/ruta con espacios"], dry_run=True)
    out = capsys.readouterr().out
    assert "'/ruta con espacios'" in out
    assert "rm" not in out


def test_prefijo_adjunto_se_mantiene_un_token(tmp_path, monkeypatch):
    vistos = _capture_run(monkeypatch)
    acc = {"description": "d", "type": "command", "command": "du -sh {1}"}
    monkeypatch.setattr(fsort.sys, "exit", lambda code=0: None)
    fsort.run_action("tamano", acc, ["dir;evil"])
    assert vistos["argv"] == ["du", "-sh", "dir;evil"]
