"""Tests de la logica de archivos de fsort (ordenar, vaciar, mover, duplicados, papelera)."""
import sys
from pathlib import Path

import pytest

from fsort import config, fsort
from fsort.errores import (
    DestinationNotFoundError,
    DirectoryNotFoundError,
    InvalidArgumentError,
    NotADirectoryError_,
)


def touch(path: Path, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- sort_files ---------------------------------------------------------------

def test_sort_files_crea_carpetas_por_extension(tmp_path):
    touch(tmp_path / "a.txt")
    touch(tmp_path / "b.jpg")
    touch(tmp_path / "c")
    fsort.sort_files(tmp_path)
    assert (tmp_path / "txt" / "a.txt").exists()
    assert (tmp_path / "jpg" / "b.jpg").exists()
    assert (tmp_path / "sin_extension" / "c").exists()
    assert not (tmp_path / "a.txt").exists()


def test_sort_files_dry_run_no_mueve(tmp_path):
    f = touch(tmp_path / "a.txt")
    fsort.sort_files(tmp_path, dry_run=True)
    assert f.exists()


def test_sort_files_colisiones_no_sobrescriben(tmp_path):
    touch(tmp_path / "txt" / "a.txt", "viejo")
    touch(tmp_path / "a.txt", "nuevo")
    fsort.sort_files(tmp_path)
    assert (tmp_path / "txt" / "a.txt").read_text(encoding="utf-8") == "viejo"
    assert (tmp_path / "txt" / "a_1.txt").read_text(encoding="utf-8") == "nuevo"


def test_sort_files_directorio_no_existe(tmp_path):
    with pytest.raises(DirectoryNotFoundError):
        fsort.sort_files(tmp_path / "nada")


def test_sort_files_no_es_directorio(tmp_path):
    f = touch(tmp_path / "a.txt")
    with pytest.raises(NotADirectoryError_):
        fsort.sort_files(f)


def test_sort_files_recursivo_consolida(tmp_path):
    touch(tmp_path / "sub" / "a.txt")
    fsort.sort_files(tmp_path, recursive=True)
    assert (tmp_path / "txt" / "a.txt").exists()


def test_sort_files_excluye_script(tmp_path):
    touch(tmp_path / "fsort.py")
    touch(tmp_path / "a.txt")
    fsort.sort_files(tmp_path)
    assert (tmp_path / "fsort.py").exists()
    assert (tmp_path / "txt" / "a.txt").exists()


def test_sort_files_copia_deja_original(tmp_path):
    f = touch(tmp_path / "a.txt")
    fsort.sort_files(tmp_path, copy=True)
    assert f.exists()
    assert (tmp_path / "txt" / "a.txt").exists()


# --- flatten_dir --------------------------------------------------------------

def test_flatten_dir_mueve_y_elimina_vacias(tmp_path):
    d = tmp_path / "base"
    touch(d / "sub1" / "a.txt")
    touch(d / "sub2" / "deep" / "b.txt")
    dest = tmp_path / "dest"
    fsort.flatten_dir(d, dest)
    assert (dest / "a.txt").exists()
    assert (dest / "b.txt").exists()
    assert not (d / "sub1").exists()
    assert not (d / "sub2").exists()


def test_flatten_dir_copy_conserva(tmp_path):
    d = tmp_path / "base"
    touch(d / "sub" / "a.txt")
    dest = tmp_path / "dest"
    fsort.flatten_dir(d, dest, copy=True)
    assert (dest / "a.txt").exists()
    assert (d / "sub" / "a.txt").exists()


# --- move_items ---------------------------------------------------------------

def test_move_items_mueve_y_copia(tmp_path):
    f = touch(tmp_path / "a.txt")
    d = tmp_path / "dest"
    d.mkdir()
    fsort.move_items([str(f)], d)
    assert (d / "a.txt").exists()
    assert not f.exists()

    f2 = touch(tmp_path / "b.txt")
    fsort.move_items([str(f2)], d, copy=True)
    assert f2.exists()
    assert (d / "b.txt").exists()


def test_move_items_destino_no_existe(tmp_path):
    f = touch(tmp_path / "a.txt")
    with pytest.raises(DestinationNotFoundError):
        fsort.move_items([str(f)], tmp_path / "nodest")


def test_move_items_omite_ya_en_destino(tmp_path, capsys):
    d = tmp_path / "dest"
    d.mkdir()
    f = touch(tmp_path / "a.txt")
    dentro = d / "a.txt"
    f.write_text("x")
    import shutil
    shutil.move(str(f), str(dentro))
    fsort.move_items([str(dentro)], d)
    assert "Omitido" in capsys.readouterr().out
    assert dentro.exists()


def test_move_items_colisiones(tmp_path):
    touch(tmp_path / "a.txt", "uno")
    d = tmp_path / "dest"
    d.mkdir()
    touch(d / "a.txt", "dos")
    fsort.move_items([str(tmp_path / "a.txt")], d)
    assert (d / "a.txt").read_text(encoding="utf-8") == "dos"
    assert (d / "a_1.txt").read_text(encoding="utf-8") == "uno"


# --- find_duplicates ----------------------------------------------------------

def test_find_duplicates_informa(tmp_path, capsys):
    touch(tmp_path / "a.txt", "contenido")
    touch(tmp_path / "b.txt", "contenido")
    touch(tmp_path / "c.txt", "otro")
    fsort.find_duplicates(tmp_path)
    out = capsys.readouterr().out
    assert "grupo" in out
    assert (tmp_path / "a.txt").exists()  # no borra sin delete


def test_find_duplicates_delete_conserva_mas_antiguo(tmp_path):
    a = touch(tmp_path / "a.txt", "contenido")
    b = touch(tmp_path / "b.txt", "contenido")
    import os
    os.utime(a, (0, 0))
    os.utime(b, (100, 100))
    fsort.find_duplicates(tmp_path, delete=True)
    assert a.exists()
    assert not b.exists()


def test_find_duplicates_dry_run(tmp_path):
    touch(tmp_path / "a.txt", "contenido")
    touch(tmp_path / "b.txt", "contenido")
    fsort.find_duplicates(tmp_path, delete=True, dry_run=True)
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()


# --- largest_files ------------------------------------------------------------

def test_largest_files_top(tmp_path, capsys):
    touch(tmp_path / "peq.txt", "a")
    touch(tmp_path / "big.txt", "b" * 100)
    fsort.largest_files(tmp_path, top=1)
    out = capsys.readouterr().out
    assert "big.txt" in out
    assert "peq.txt" not in out


def test_largest_files_top_invalido(tmp_path):
    touch(tmp_path / "a.txt")
    with pytest.raises(InvalidArgumentError):
        fsort.largest_files(tmp_path, top="cero")
    with pytest.raises(InvalidArgumentError):
        fsort.largest_files(tmp_path, top=0)


def test_largest_files_delete_dry_run(tmp_path):
    f = touch(tmp_path / "big.txt", "b" * 100)
    fsort.largest_files(tmp_path, top=1, delete=True, dry_run=True)
    assert f.exists()


# --- clean_temp / empty_trash -------------------------------------------------

def test_clean_temp_sin_tty_no_mueve(tmp_path, no_tty):
    f = touch(tmp_path / "a.tmp")
    fsort.clean_temp(tmp_path)
    assert f.exists()


def test_clean_temp_yes_mueve_a_papelera(tmp_path, monkeypatch):
    trash = tmp_path / "trash"
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    monkeypatch.setenv("FSORT_YES", "1")
    f = touch(tmp_path / "a.tmp")
    fsort.clean_temp(tmp_path)
    assert not f.exists()
    assert (trash / "a.tmp").exists()


def test_clean_temp_no_toca_papelera(tmp_path, monkeypatch):
    trash = tmp_path / "trash"
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    monkeypatch.setenv("FSORT_YES", "1")
    guardado = touch(trash / "b.tmp")
    fsort.clean_temp(tmp_path)
    assert guardado.exists()


def test_empty_trash_lista_sin_borrar(tmp_path, monkeypatch, capsys):
    trash = tmp_path / "trash"
    trash.mkdir()
    touch(trash / "a.txt")
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    fsort.empty_trash()
    assert "a.txt" in capsys.readouterr().out
    assert (trash / "a.txt").exists()


def test_empty_trash_delete(tmp_path, monkeypatch):
    trash = tmp_path / "trash"
    trash.mkdir()
    f = touch(trash / "a.txt")
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    fsort.empty_trash(delete=True)
    assert not f.exists()


# --- dir_report ---------------------------------------------------------------

def _poblado(tmp_path):
    (tmp_path / "a.txt").write_text("contenido duplicado")
    (tmp_path / "b.txt").write_text("contenido duplicado")
    (tmp_path / "c.tmp").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.pdf").write_text("y")


def test_reporte_summary(tmp_path, capsys):
    _poblado(tmp_path)
    fsort.dir_report(tmp_path)
    out = capsys.readouterr().out
    assert "Archivos:" in out and "4" in out
    assert "Top" in out and ".txt" in out
    assert "Temporales" in out
    assert "Duplicados: 1" in out


def test_reporte_sense_temporals(tmp_path, capsys):
    (tmp_path / "a.txt").write_text("z")
    fsort.dir_report(tmp_path)
    out = capsys.readouterr().out
    assert "Temporales" not in out
    assert "Duplicados" not in out


def test_reporte_top_invalido(tmp_path):
    _poblado(tmp_path)
    with pytest.raises(InvalidArgumentError):
        fsort.dir_report(tmp_path, top="cero")


def test_reporte_directorio_no_existe(tmp_path):
    with pytest.raises(DirectoryNotFoundError):
        fsort.dir_report(tmp_path / "nada")


def test_find_duplicates_quiet(tmp_path, capsys):
    _poblado(tmp_path)
    res = fsort.find_duplicates(tmp_path, quiet=True)
    out = capsys.readouterr().out
    assert res["groups"] == 1
    assert res["wasted"] > 0
    assert out == ""


def test_find_duplicates_retorna_groups(tmp_path):
    (tmp_path / "u.txt").write_text("unico")
    res = fsort.find_duplicates(tmp_path, quiet=True)
    assert res == {"groups": 0, "wasted": 0}


def test_reporte_comando_real(tmp_path):
    """'reporte' existeix en actions.json i apunta a dir_report."""
    from fsort import config
    actions = config.load_and_validate()
    assert actions["reporte"]["func"] == "dir_report"


# --- deshacer-limpieza --------------------------------------------------------

def _limpiar(tmp_path, monkeypatch, trash=None):
    trash = trash or tmp_path / "trash"
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    monkeypatch.setenv("FSORT_LOG_FILE", str(log))
    monkeypatch.setenv("FSORT_YES", "1")
    fsort.clean_temp(tmp_path)
    return trash, log


def test_undo_deshace_ultima_limpiar(tmp_path, monkeypatch):
    _poblado(tmp_path)
    trash, log = _limpiar(tmp_path, monkeypatch)
    assert not (tmp_path / "c.tmp").exists()
    fsort.undo_clean(assume_yes=True)
    assert (tmp_path / "c.tmp").exists()
    assert not (trash / "c.tmp").exists()
    assert log.read_text(encoding="utf-8") == ""


def test_undo_dry_run_no_restaura(tmp_path, monkeypatch, capsys):
    _poblado(tmp_path)
    _limpiar(tmp_path, monkeypatch)
    fsort.undo_clean(dry_run=True)
    assert "[DRY-RUN]" in capsys.readouterr().out
    assert not (tmp_path / "c.tmp").exists()


def test_undo_sin_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FSORT_LOG_FILE", str(tmp_path / "nodir" / "l.jsonl"))
    fsort.undo_clean()
    assert "No hay registros" in capsys.readouterr().out


def test_undo_papelera_vaciada_no_rompe(tmp_path, monkeypatch, capsys):
    _poblado(tmp_path)
    trash, log = _limpiar(tmp_path, monkeypatch)
    fsort.empty_trash(directory=trash, delete=True)
    fsort.undo_clean(assume_yes=True)
    out = capsys.readouterr().out
    assert "no se puede recuperar" in out
    assert log.read_text(encoding="utf-8").strip()  # entrada conservada


def test_undo_colision_no_sobrescribe(tmp_path, monkeypatch):
    _poblado(tmp_path)
    _limpiar(tmp_path, monkeypatch)
    (tmp_path / "c.tmp").write_text("nuevo")
    fsort.undo_clean(assume_yes=True)
    assert (tmp_path / "c.tmp").read_text(encoding="utf-8") == "nuevo"
    assert (tmp_path / "c_1.tmp").exists()


def test_undo_sin_tty_no_restaura(tmp_path, monkeypatch, no_tty):
    _poblado(tmp_path)
    _limpiar(tmp_path, monkeypatch)
    monkeypatch.delenv("FSORT_YES")
    fsort.undo_clean()
    assert not (tmp_path / "c.tmp").exists()


def test_undo_dos_limpiezas(tmp_path, monkeypatch):
    _poblado(tmp_path)
    trash, log = _limpiar(tmp_path, monkeypatch)
    d2 = tmp_path / "d2"
    d2.mkdir()
    (d2 / "d.tmp").write_text("d")
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    fsort.clean_temp(d2)
    fsort.undo_clean(assume_yes=True)
    assert (d2 / "d.tmp").exists()          # solo la última
    assert not (tmp_path / "c.tmp").exists()
    assert log.read_text(encoding="utf-8").strip()  # queda la primera limpieza


def test_clean_temp_si_registra_log(tmp_path, monkeypatch):
    _poblado(tmp_path)
    trash, log = _limpiar(tmp_path, monkeypatch)
    assert "c.tmp" in log.read_text(encoding="utf-8")


def test_accio_deshacer_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["deshacer-limpieza"]["func"] == "undo_clean"


# --- limpiar-auto (kwargs assume_yes) ----------------------------------------

def test_limpiar_auto_sin_tty_no_mueve(tmp_path, monkeypatch, capsys):
    """assume_yes via kwargs NO debe saltarse la proteccion de sin-TTY."""
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.setenv("FSORT_LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.delenv("FSORT_YES", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    f = touch(tmp_path / "a.tmp")
    acc = config.load_and_validate()["limpiar-auto"]
    fsort.run_python_action("limpiar-auto", acc, [str(tmp_path)])
    assert f.exists()
    assert "sin TTY" in capsys.readouterr().out


def test_limpiar_auto_con_yes_si_mueve(tmp_path, monkeypatch):
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.setenv("FSORT_LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("FSORT_YES", "1")
    f = touch(tmp_path / "a.tmp")
    acc = config.load_and_validate()["limpiar-auto"]
    fsort.run_python_action("limpiar-auto", acc, [str(tmp_path)])
    assert not f.exists()
    assert (tmp_path / "trash" / "a.tmp").exists()


def test_limpiar_auto_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["limpiar-auto"]["func"] == "clean_temp"
    assert actions["limpiar-auto"]["kwargs"]["assume_yes"] is True


def test_clean_temp_assume_yes_sin_tty_cancela(tmp_path, monkeypatch, capsys):
    """clean_temp(assume_yes=True) sin TTY y sin FSORT_YES: no mueve nada."""
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.delenv("FSORT_YES", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    f = touch(tmp_path / "a.tmp")
    fsort.clean_temp(tmp_path, assume_yes=True)
    assert f.exists()
    assert "cancelado" in capsys.readouterr().out.lower()
