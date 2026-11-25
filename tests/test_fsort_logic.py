"""Tests de la logica de archivos de fsort (ordenar, vaciar, mover, duplicados, papelera)."""
import shutil
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


# --- ordenar-auto (folder_mode='human') ---------------------------------------

def _human_dirs(d: Path):
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def test_sort_files_human_categorias(tmp_path):
    for n in ("foto.jpg", "otra.PNG", "nota.docx", "cancion.mp3", "peli.mkv",
              "paquete.zip", "app.exe", "script.py", "font.ttf", "cosa.xyz"):
        touch(tmp_path / n)
    touch(tmp_path / "sinext")
    fsort.sort_files(tmp_path, folder_mode="human")
    dirs = _human_dirs(tmp_path)
    assert dirs == ["archives", "codigo", "documentos", "fuentes", "imagenes",
                    "musica", "otros", "programas", "sin_extension", "video"]
    assert (tmp_path / "imagenes" / "otra.PNG").exists()
    assert (tmp_path / "otros" / "cosa.xyz").exists()


def test_sort_files_human_pdfs_separados_de_documentos(tmp_path):
    """En modo humano los .pdf van a pdfs/ y el resto de docs a documentos/."""
    touch(tmp_path / "informe.pdf")
    touch(tmp_path / "notas.txt")
    fsort.sort_files(tmp_path, folder_mode="human")
    assert (tmp_path / "pdfs" / "informe.pdf").exists()
    assert (tmp_path / "documentos" / "notas.txt").exists()
    assert not (tmp_path / "documentos" / "informe.pdf").exists()


def test_sort_files_human_colisiones(tmp_path):
    d = tmp_path / "imagenes"
    d.mkdir()
    viejo = d / "foto.png"
    viejo.write_text("viejo")
    touch(tmp_path / "foto.png", "nuevo")
    fsort.sort_files(tmp_path, folder_mode="human")
    assert viejo.read_text(encoding="utf-8") == "viejo"
    assert (d / "foto_1.png").read_text(encoding="utf-8") == "nuevo"


def test_sort_files_human_dry_run(tmp_path):
    f = touch(tmp_path / "foto.jpg")
    fsort.sort_files(tmp_path, folder_mode="human", dry_run=True)
    assert f.exists()


def test_sort_files_human_recursivo(tmp_path):
    touch(tmp_path / "sub" / "foto.jpg")
    fsort.sort_files(tmp_path, folder_mode="human", recursive=True)
    assert (tmp_path / "imagenes" / "foto.jpg").exists()


def test_sort_files_ext_conserva_comportament(tmp_path):
    """El modo clasico sigue moviendo a carpetas por extension."""
    touch(tmp_path / "a.png")
    fsort.sort_files(tmp_path)
    assert (tmp_path / "png" / "a.png").exists()


def test_folder_for_helpers():
    assert fsort._folder_for(".jpg") == "jpg"
    assert fsort._folder_for(".jpg", "human") == "imagenes"
    assert fsort._folder_for(".docx", "human") == "documentos"
    assert fsort._folder_for(".pdf", "human") == "pdfs"
    assert fsort._folder_for(".xyz", "human") == "otros"
    assert fsort._folder_for("", "human") == "sin_extension"


def test_dest_for_sense_mode_human_no_renombra(tmp_path):
    d = tmp_path / "png"
    d.mkdir()
    (d / "a.png").write_text("v")
    f = tmp_path / "a.png"
    f.write_text("n")
    assert fsort._dest_for(f, d, "ext") == d / "a.png"


def test_ordenar_auto_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["ordenar-auto"]["func"] == "sort_files"
    assert actions["ordenar-auto"]["kwargs"]["folder_mode"] == "human"


def test_move_no_overwrite_no_pisa(tmp_path):
    """_move_no_overwrite: si el destino existe, reubica en _1 sin pisar."""
    dst = tmp_path / "txt"
    dst.mkdir()
    viejo = dst / "a.txt"
    viejo.write_text("viejo")
    orig = tmp_path / "a.txt"
    orig.write_text("nuevo")
    final = fsort._move_no_overwrite(orig, viejo)
    assert viejo.read_text(encoding="utf-8") == "viejo"
    assert final.name == "a_1.txt"
    assert final.read_text(encoding="utf-8") == "nuevo"
    assert not orig.exists()


# --- mas-antiguos / por-edad --------------------------------------------------

def _fechas(tmp_path):
    import os, time
    for nombre, dias in (("viejo1.txt", 400), ("viejo2.log", 500),
                         ("medio.pdf", 100), ("nuevo.jpg", 1)):
        f = tmp_path / nombre
        f.write_bytes(b"x" * 10)
        t = time.time() - dias * 86400
        os.utime(f, (t, t))


def test_oldest_files_top(tmp_path, capsys):
    _fechas(tmp_path)
    fsort.oldest_files(tmp_path, top=2)
    out = capsys.readouterr().out
    assert "viejo2.log" in out and "viejo1.txt" in out
    assert "nuevo.jpg" not in out


def test_oldest_files_top_invalido(tmp_path):
    _fechas(tmp_path)
    with pytest.raises(InvalidArgumentError):
        fsort.oldest_files(tmp_path, top="cero")
    with pytest.raises(InvalidArgumentError):
        fsort.oldest_files(tmp_path, top=0)


def test_oldest_files_ext(tmp_path, capsys):
    _fechas(tmp_path)
    fsort.oldest_files(tmp_path, ext="log")
    out = capsys.readouterr().out
    assert "viejo2.log" in out and "viejo1.txt" not in out


def test_aged_files_filtra_dias(tmp_path, capsys):
    _fechas(tmp_path)
    fsort.aged_files(tmp_path, days=365, dry_run=True)
    out = capsys.readouterr().out
    assert "viejo1.txt" in out and "viejo2.log" in out
    assert "medio.pdf" not in out and "nuevo.jpg" not in out
    assert (tmp_path / "viejo1.txt").exists()


def test_aged_files_mueve_papelera_y_undo(tmp_path, monkeypatch):
    _fechas(tmp_path)
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.setenv("FSORT_LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("FSORT_YES", "1")
    fsort.aged_files(tmp_path, days=365)
    assert not (tmp_path / "viejo1.txt").exists()
    assert (tmp_path / "trash" / "viejo1.txt").exists()
    fsort.undo_clean(assume_yes=True)
    assert (tmp_path / "viejo1.txt").exists()


def test_aged_files_delete(tmp_path, monkeypatch):
    _fechas(tmp_path)
    monkeypatch.setenv("FSORT_YES", "1")
    fsort.aged_files(tmp_path, days=365, delete=True)
    assert not (tmp_path / "viejo1.txt").exists()
    assert (tmp_path / "medio.pdf").exists()


def test_aged_files_dias_invalidos(tmp_path):
    _fechas(tmp_path)
    with pytest.raises(InvalidArgumentError):
        fsort.aged_files(tmp_path, days="muchos")
    with pytest.raises(InvalidArgumentError):
        fsort.aged_files(tmp_path, days=-1)


def test_aged_files_sin_candidatos(tmp_path, capsys):
    _fechas(tmp_path)
    fsort.aged_files(tmp_path, days=10000, dry_run=True)
    assert "Ningun archivo" in capsys.readouterr().out


def test_aged_files_sin_tty_no_mueve(tmp_path, monkeypatch, no_tty):
    _fechas(tmp_path)
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.delenv("FSORT_YES", raising=False)
    fsort.aged_files(tmp_path, days=365)
    assert (tmp_path / "viejo1.txt").exists()


def test_accions_edad_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["mas-antiguos"]["func"] == "oldest_files"
    assert actions["por-edad"]["func"] == "aged_files"
    assert actions["por-edad-eliminar"]["kwargs"]["delete"] is True
    assert actions["por-edad-txt"]["kwargs"]["ext"] == "txt"


def test_cli_mas_antiguos_args(tmp_path):
    """El 2n argument (top) arriba correctament a la funcio."""
    _fechas(tmp_path)
    acc = config.load_and_validate()["mas-antiguos"]
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fsort.run_python_action("mas-antiguos", acc, [str(tmp_path), "1"])
    out = buf.getvalue()
    assert "viejo2.log" in out
    assert "viejo1.txt" not in out


def test_cli_por_edad_args(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.setenv("FSORT_LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("FSORT_YES", "1")
    _fechas(tmp_path)
    acc = config.load_and_validate()["por-edad"]
    fsort.run_python_action("por-edad", acc, [str(tmp_path), "365"])
    assert not (tmp_path / "viejo1.txt").exists()
    assert (tmp_path / "medio.pdf").exists()


# --- descomprimir-a -----------------------------------------------------------

import zipfile as _zip
import tarfile as _tar
import gzip as _gzip


def _mk_archivos(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    with _zip.ZipFile(d / "foto.zip", "w") as z:
        z.writestr("a.txt", "hola")
        z.writestr("sub/b.md", "mundo")
    with _tar.open(d / "pandas.tar.gz", "w:gz") as t:
        (d / "x.txt").write_text("uno")
        (d / "y.log").write_text("dos")
        t.add(d / "x.txt", arcname="x.txt")
        t.add(d / "y.log", arcname="y.log")
        (d / "x.txt").unlink()
        (d / "y.log").unlink()
    with _gzip.open(d / "solo.txt.gz", "wb") as g:
        g.write(b"contenido gz")
    with _zip.ZipFile(d / "malvado.zip", "w") as z:
        z.writestr("../ESCAPADO.txt", "mal")
    with _zip.ZipFile(d / "absoluto.zip", "w") as z:
        z.writestr("/etc/ESCAPADO.txt", "mal")
    (d / "fake.zip").write_text("no soy un zip")
    shutil.copy2(d / "foto.zip", d / "x.rar")


def test_extract_zip(tmp_path):
    _mk_archivos(tmp_path)
    fsort.extract_archive(tmp_path / "foto.zip", tmp_path / "z1")
    assert (tmp_path / "z1" / "a.txt").read_text() == "hola"
    assert (tmp_path / "z1" / "sub" / "b.md").read_text() == "mundo"


def test_extract_tar_gz(tmp_path):
    _mk_archivos(tmp_path)
    fsort.extract_archive(tmp_path / "pandas.tar.gz")
    assert (tmp_path / "pandas" / "x.txt").exists()
    assert (tmp_path / "pandas" / "y.log").exists()


def test_extract_gz_sueltos(tmp_path):
    _mk_archivos(tmp_path)
    fsort.extract_archive(tmp_path / "solo.txt.gz")
    assert (tmp_path / "solo.txt" / "solo.txt.gz").read_text() == "contenido gz"


def test_extract_no_sobrescribe(tmp_path):
    _mk_archivos(tmp_path)
    fsort.extract_archive(tmp_path / "foto.zip", tmp_path / "z1")
    fsort.extract_archive(tmp_path / "foto.zip", tmp_path / "z1")
    assert (tmp_path / "z1_1" / "a.txt").exists()


def test_extract_dry_run(tmp_path, capsys):
    _mk_archivos(tmp_path)
    fsort.extract_archive(tmp_path / "foto.zip", tmp_path / "z1", dry_run=True)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert not (tmp_path / "z1").exists()


def test_extract_zip_slip_rechazado(tmp_path):
    from fsort.errores import OperationError
    _mk_archivos(tmp_path)
    with pytest.raises(OperationError):
        fsort.extract_archive(tmp_path / "malvado.zip", tmp_path / "z1")
    assert not (tmp_path.parent / "ESCAPADO.txt").exists()
    assert not (tmp_path / "z1" / "ESCAPADO.txt").exists()


def test_extract_ruta_absoluta_rechazada(tmp_path):
    from fsort.errores import OperationError
    _mk_archivos(tmp_path)
    with pytest.raises(OperationError):
        fsort.extract_archive(tmp_path / "absoluto.zip", tmp_path / "z1")
    assert not (tmp_path / "z1" / "etc").exists()


def test_extract_zip_invalido(tmp_path):
    from fsort.errores import FileReadError
    _mk_archivos(tmp_path)
    with pytest.raises(FileReadError):
        fsort.extract_archive(tmp_path / "fake.zip", tmp_path / "z1")


def test_extract_rar_no_soportado(tmp_path):
    from fsort.errores import UnsupportedFileFormatError
    _mk_archivos(tmp_path)
    with pytest.raises(UnsupportedFileFormatError):
        fsort.extract_archive(tmp_path / "x.rar", tmp_path / "z1")


def test_extract_inexistente(tmp_path):
    from fsort.errores import FileReadError
    with pytest.raises(FileReadError):
        fsort.extract_archive(tmp_path / "nada.zip")


def test_accion_descomprimir_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["descomprimir-a"]["func"] == "extract_archive"


# --- sincronizar --------------------------------------------------------------

def _arbol_sync(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("nuevo")
    (src / "sub" / "b.md").write_text("eme")
    dst.mkdir()
    (dst / "a.txt").write_text("viejo")
    (dst / "sobrante.log").write_text("x")
    import os, time
    t_viejo = time.time() - 400 * 86400
    os.utime(dst / "a.txt", (t_viejo, t_viejo))
    return src, dst


def _env_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.setenv("FSORT_LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.setenv("FSORT_YES", "1")


def test_sync_crea_y_actualiza(tmp_path, monkeypatch):
    src, dst = _arbol_sync(tmp_path)
    _env_sync(tmp_path, monkeypatch)
    fsort.sync_dirs(src, dst)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "nuevo"
    assert (dst / "sub" / "b.md").exists()
    assert (dst / "sobrante.log").exists()  # sin delete no se toca


def test_sync_dry_run_no_toca(tmp_path, monkeypatch, capsys):
    src, dst = _arbol_sync(tmp_path)
    _env_sync(tmp_path, monkeypatch)
    fsort.sync_dirs(src, dst, dry_run=True)
    assert "DRY-RUN" in capsys.readouterr().out
    assert (dst / "a.txt").read_text(encoding="utf-8") == "viejo"


def test_sync_espejo_papelera_y_undo(tmp_path, monkeypatch):
    src, dst = _arbol_sync(tmp_path)
    _env_sync(tmp_path, monkeypatch)
    fsort.sync_dirs(src, dst, delete=True)
    assert not (dst / "sobrante.log").exists()
    assert (tmp_path / "trash" / "sobrante.log").exists()
    fsort.undo_clean(assume_yes=True)
    assert (dst / "sobrante.log").exists()


def test_sync_colision_va_a_papelera(tmp_path, monkeypatch):
    # archivo preexistente MAS NUEVO en destino: no debe copiarse encima
    src, dst = _arbol_sync(tmp_path)
    _env_sync(tmp_path, monkeypatch)
    import os, time
    t = time.time() + 100
    os.utime(dst / "a.txt", (t, t))
    fsort.sync_dirs(src, dst)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "viejo"  # no se toca


def test_sync_ya_sincronizado(tmp_path, monkeypatch, capsys):
    src, dst = _arbol_sync(tmp_path)
    _env_sync(tmp_path, monkeypatch)
    fsort.sync_dirs(src, dst)
    capsys.readouterr()
    fsort.sync_dirs(src, dst)
    assert "Ya sincronizado" in capsys.readouterr().out


def test_sync_origen_destino_iguales(tmp_path, monkeypatch):
    _env_sync(tmp_path, monkeypatch)
    with pytest.raises(InvalidArgumentError):
        fsort.sync_dirs(tmp_path, tmp_path)


def test_sync_destino_dentro_origen(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _env_sync(tmp_path, monkeypatch)
    (src / "dentro").mkdir()
    with pytest.raises(InvalidArgumentError):
        fsort.sync_dirs(src, src / "dentro")


def test_sync_sin_tty_no_copia(tmp_path, monkeypatch, no_tty):
    src, dst = _arbol_sync(tmp_path)
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path / "trash"))
    monkeypatch.delenv("FSORT_YES", raising=False)
    fsort.sync_dirs(src, dst)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "viejo"


def test_sync_destino_no_existe(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _env_sync(tmp_path, monkeypatch)
    from fsort.errores import DestinationNotFoundError
    with pytest.raises(DestinationNotFoundError):
        fsort.sync_dirs(src, tmp_path / "nodst")


def test_sync_omite_mismo_mtime(tmp_path, monkeypatch, capsys):
    src, dst = _arbol_sync(tmp_path)
    _env_sync(tmp_path, monkeypatch)
    fsort.sync_dirs(src, dst)          # primera pasada
    import os
    st = os.stat(dst / "a.txt")
    os.utime(src / "a.txt", (st.st_atime, st.st_mtime))  # misma marca
    capsys.readouterr()
    fsort.sync_dirs(src, dst)
    assert "Ya sincronizado" in capsys.readouterr().out


def test_accions_sync_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["sincronizar"]["func"] == "sync_dirs"
    assert actions["sincronizar-espejo"]["kwargs"]["delete"] is True


# --- duplicados-hardlink ------------------------------------------------------

def _dup_dir(tmp_path):
    a = tmp_path / "a" / "x.bin"
    b = tmp_path / "b" / "y.bin"
    c = tmp_path / "z.bin"
    for p in (a, b, c):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"duplicado" * 100)
    import os, time
    t = time.time()
    os.utime(a, (t - 300, t - 300))
    a_único = tmp_path / "otro.bin"
    a_único.write_bytes(b"distinto")
    return a, b, c


def _env_dup(tmp_path, monkeypatch):
    # papelera dentro del arbol: la salvaguarda de dedup_hardlink debe excluir los .bak
    trash = tmp_path / "trash"
    monkeypatch.setenv("FSORT_TRASH_DIR", str(trash))
    monkeypatch.setenv("FSORT_YES", "1")
    return trash


def test_hardlink_dedup(tmp_path, monkeypatch):
    a, b, c = _dup_dir(tmp_path)
    trash = _env_dup(tmp_path, monkeypatch)
    fsort.dedup_hardlink(tmp_path)
    import os
    ia, ib, ic = (os.stat(p).st_ino for p in (a, b, c))
    assert ia == ib == ic                     # los tres, mismo inodo
    assert os.stat(a).st_nlink == 3
    assert b.read_bytes() == a.read_bytes()   # rutas intactas
    assert (tmp_path / "otro.bin").exists()   # no duplicado intacto
    assert (trash / "y.bin.bak").exists()  # backup del reemplazado


def test_hardlink_dry_run_no_toca(tmp_path, monkeypatch):
    a, b, c = _dup_dir(tmp_path)
    _env_dup(tmp_path, monkeypatch)
    fsort.dedup_hardlink(tmp_path, dry_run=True)
    import os
    assert os.stat(a).st_ino != os.stat(b).st_ino


def test_hardlink_idempotente(tmp_path, monkeypatch, capsys):
    _dup_dir(tmp_path)
    _env_dup(tmp_path, monkeypatch)
    fsort.dedup_hardlink(tmp_path)
    capsys.readouterr()
    fsort.dedup_hardlink(tmp_path)
    assert "Sin cambios" in capsys.readouterr().out


def test_hardlink_sin_tty_no_toca(tmp_path, monkeypatch):
    a, b, c = _dup_dir(tmp_path)
    monkeypatch.setenv("FSORT_TRASH_DIR", str(tmp_path.parent / (tmp_path.name + "_t")))
    monkeypatch.delenv("FSORT_YES", raising=False)
    fsort.dedup_hardlink(tmp_path)
    import os
    assert os.stat(a).st_ino != os.stat(b).st_ino


def test_hardlink_delete(tmp_path, monkeypatch):
    a, b, c = _dup_dir(tmp_path)
    monkeypatch.setenv("FSORT_YES", "1")
    fsort.dedup_hardlink(tmp_path, delete=True)
    assert a.exists()
    assert not b.exists() and not c.exists()


def test_accion_hardlink_registered():
    from fsort import config
    actions = config.load_and_validate()
    assert actions["duplicados-hardlink"]["func"] == "dedup_hardlink"


# --- instantaneas (snapshot / diff / snapshot-list) -----------------------------

@pytest.fixture
def snap_root(tmp_path, monkeypatch):
    root = tmp_path / "_snapshots"
    monkeypatch.setenv("FSORT_SNAPSHOT_DIR", str(root))
    return root


def _snap(d: Path, name: str = None):
    """Crea una instantanea y devuelve la ruta del json generado."""
    root = fsort._snapshot_root()
    before = {p.name for p in (root / fsort._snapshot_slug(d)).glob("*.json")} \
        if (root / fsort._snapshot_slug(d)).exists() else set()
    fsort.dir_snapshot(d, name=name)
    nuevos = {p for p in (root / fsort._snapshot_slug(d)).glob("*.json")
              if p.name not in before}
    assert len(nuevos) == 1
    return nuevos.pop()


def test_snapshot_guarda_inventario(tmp_path, snap_root):
    touch(tmp_path / "a.txt", "uno")
    touch(tmp_path / "sub" / "b.md", "dos")
    path = _snap(tmp_path)
    assert path.exists()
    assert snap_root / fsort._snapshot_slug(tmp_path) in path.parents
    snap = fsort._load_snapshot(path)
    assert set(snap["files"]) == {"a.txt", "sub/b.md"}
    assert snap["files"]["a.txt"]["size"] == len("uno")
    assert len(snap["files"]["a.txt"]["sha256"]) == 64


def test_snapshot_dry_run_no_guarda(tmp_path, snap_root, capsys):
    touch(tmp_path / "a.txt")
    fsort.dir_snapshot(tmp_path, dry_run=True)
    assert "[DRY-RUN]" in capsys.readouterr().out
    assert not snap_root.exists()


def test_snapshot_directorio_inexistente(tmp_path, snap_root):
    with pytest.raises(DirectoryNotFoundError):
        fsort.dir_snapshot(tmp_path / "no-existe")


def test_diff_detecta_creados_modificados_borrados(tmp_path, snap_root, capsys):
    touch(tmp_path / "a.txt", "uno")
    touch(tmp_path / "b.log", "dos")
    _snap(tmp_path)
    touch(tmp_path / "c.txt", "tres")
    (tmp_path / "a.txt").write_text("cambiado", encoding="utf-8")
    (tmp_path / "b.log").unlink()
    fsort.snapshot_diff(tmp_path)
    out = capsys.readouterr().out
    assert "+ Añadido: c.txt" in out
    assert "~ Modificado: a.txt" in out
    assert "- Eliminado: b.log" in out
    assert "Resumen:" in out


def test_diff_sin_cambios(tmp_path, snap_root, capsys):
    touch(tmp_path / "a.txt")
    _snap(tmp_path)
    fsort.snapshot_diff(tmp_path)
    assert "Sin cambios" in capsys.readouterr().out


def test_diff_detecta_renombrado_por_hash(tmp_path, snap_root, capsys):
    touch(tmp_path / "viejo.txt", "contenido")
    _snap(tmp_path)
    (tmp_path / "viejo.txt").rename(tmp_path / "nuevo.txt")
    fsort.snapshot_diff(tmp_path)
    out = capsys.readouterr().out
    assert "Movido/renombrado: viejo.txt -> nuevo.txt" in out
    assert "- Eliminado" not in out
    assert "+ Añadido" not in out


def test_diff_latest_compara_dos_instantaneas(tmp_path, snap_root, capsys):
    import time
    touch(tmp_path / "a.txt", "uno")
    _snap(tmp_path)
    time.sleep(1.1)
    touch(tmp_path / "b.txt", "dos")
    _snap(tmp_path)
    fsort.snapshot_diff(tmp_path, latest=True)
    out = capsys.readouterr().out
    assert "+ Añadido: b.txt" in out
    assert "~ Modificado" not in out


def test_diff_sin_instantanea_falla(tmp_path, snap_root):
    with pytest.raises(InvalidArgumentError):
        fsort.snapshot_diff(tmp_path)


def test_diff_ext_filtra(tmp_path, snap_root, capsys):
    touch(tmp_path / "a.txt", "uno")
    _snap(tmp_path)
    touch(tmp_path / "b.log", "dos")
    fsort.snapshot_diff(tmp_path, ext="*.txt")
    out = capsys.readouterr().out
    assert "+ Añadido" not in out
    assert "Sin cambios" in out


def test_diff_no_compta_instantaneas_como_creados(tmp_path, monkeypatch, capsys):
    """El arbol de instantaneas dentro del directorio no contamina el diff."""
    root = tmp_path / "root"
    root.mkdir()
    touch(root / "a.txt")
    monkeypatch.setenv("FSORT_SNAPSHOT_DIR", str(root / ".fsort-snap"))
    fsort.dir_snapshot(root)
    assert (root / ".fsort-snap").exists()
    fsort.snapshot_diff(root)
    out = capsys.readouterr().out
    assert "Sin cambios" in out


def test_snapshot_list_muestra_fecha_y_archivos(tmp_path, snap_root, capsys):
    touch(tmp_path / "a.txt")
    _snap(tmp_path)
    fsort.snapshot_list(tmp_path)
    out = capsys.readouterr().out
    assert str(tmp_path) in out
    assert "instantanea(s)" in out


def test_snapshot_list_sin_instantaneas(tmp_path, snap_root, capsys):
    fsort.snapshot_list(tmp_path)
    assert "No hay instantaneas" in capsys.readouterr().out


def test_snapshot_keep_purga_las_antiguas(tmp_path, snap_root, monkeypatch, capsys):
    monkeypatch.setenv("SNAPSHOT_KEEP", "1")
    touch(tmp_path / "a.txt")
    _snap(tmp_path)
    import time
    time.sleep(1.1)
    _snap(tmp_path)
    files = fsort._snapshot_files_of(snap_root / fsort._snapshot_slug(tmp_path))
    assert len(files) == 1
    assert "Antigua purgada" in capsys.readouterr().out


def test_snapshot_colision_sobrescribe_con_sufijo(tmp_path, snap_root):
    touch(tmp_path / "a.txt")
    p1 = _snap(tmp_path)
    p2 = _snap(tmp_path)
    assert p1 != p2
    assert p2.name.endswith("_1.json")


def test_acciones_snapshot_registered():
    actions = config.load_and_validate()
    assert actions["snapshot"]["func"] == "dir_snapshot"
    assert actions["diff"]["func"] == "snapshot_diff"
    assert actions["snapshot-list"]["func"] == "snapshot_list"
