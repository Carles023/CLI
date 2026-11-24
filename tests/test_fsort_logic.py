"""Tests de la logica de archivos de fsort (ordenar, vaciar, mover, duplicados, papelera)."""
from pathlib import Path

import pytest

from fsort import fsort
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
