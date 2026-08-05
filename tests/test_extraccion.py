"""Tests de extraccion.py — HU-2.2."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mcp_mercadopublico.lake.extraccion import extraer_csv_utf8


def _crear_zip(ruta_zip: Path, archivos: dict[str, bytes]) -> None:
    with zipfile.ZipFile(ruta_zip, "w") as zf:
        for nombre, contenido in archivos.items():
            zf.writestr(nombre, contenido)


def test_extrae_un_solo_csv(tmp_path: Path):
    zip_path = tmp_path / "oc-da_2026-6.zip"
    contenido_latin1 = 'ID;Region\n1;"Regi\xf3n de Tarapac\xe1"\n'.encode("latin-1")
    _crear_zip(zip_path, {"2026-6.csv": contenido_latin1})

    rutas = extraer_csv_utf8(zip_path, tmp_path / "extraido")

    assert len(rutas) == 1
    assert rutas[0].name == "2026-6.utf8.csv"
    texto = rutas[0].read_text(encoding="utf-8")
    assert "Región de Tarapacá" in texto


def test_nombre_interno_no_coincide_con_nombre_del_zip(tmp_path: Path):
    """No debe asumirse que el CSV interno se llama como el ZIP externo."""
    zip_path = tmp_path / "COT_2026-06.zip"
    _crear_zip(zip_path, {"COT1_2026-06.csv": b"a;b\n1;2\n"})

    rutas = extraer_csv_utf8(zip_path, tmp_path / "extraido")

    assert rutas[0].name == "COT1_2026-06.utf8.csv"


def test_multiples_archivos_preserva_orden_del_zip(tmp_path: Path):
    """COT puede traer COT1_/COT2_/COT3_ — deben salir en el orden del ZIP,
    la concatenación la decide el ETL, no este módulo."""
    zip_path = tmp_path / "COT_2026-06.zip"
    _crear_zip(
        zip_path,
        {
            "COT1_2026-06.csv": b"a;b\n1;2\n",
            "COT2_2026-06.csv": b"a;b\n3;4\n",
            "COT3_2026-06.csv": b"a;b\n5;6\n",
        },
    )

    rutas = extraer_csv_utf8(zip_path, tmp_path / "extraido")

    assert [r.name for r in rutas] == [
        "COT1_2026-06.utf8.csv",
        "COT2_2026-06.utf8.csv",
        "COT3_2026-06.utf8.csv",
    ]


def test_ignora_archivos_no_csv_dentro_del_zip(tmp_path: Path):
    zip_path = tmp_path / "mixto.zip"
    _crear_zip(
        zip_path,
        {
            "2026-6.csv": b"a;b\n1;2\n",
            "leeme.txt": b"esto no es un csv",
        },
    )

    rutas = extraer_csv_utf8(zip_path, tmp_path / "extraido")

    assert len(rutas) == 1
    assert rutas[0].name == "2026-6.utf8.csv"


def test_zip_sin_csv_falla_explicito(tmp_path: Path):
    zip_path = tmp_path / "vacio.zip"
    _crear_zip(zip_path, {"nada.txt": b"sin csv aqui"})

    with pytest.raises(ValueError, match="ningún archivo .csv"):
        extraer_csv_utf8(zip_path, tmp_path / "extraido")


def test_descarta_el_csv_crudo_tras_transcodificar(tmp_path: Path):
    """No debe quedar el intermedio latin-1 ocupando scratch además del
    UTF-8 — se descarta apenas se transcodifica."""
    zip_path = tmp_path / "2026-6.zip"
    _crear_zip(zip_path, {"2026-6.csv": b"a;b\n1;2\n"})
    destino = tmp_path / "extraido"

    extraer_csv_utf8(zip_path, destino)

    archivos = list(destino.iterdir())
    assert len(archivos) == 1  # sólo el .utf8.csv, no el crudo


def test_newline_embebido_sobrevive_la_transcodificacion(tmp_path: Path):
    """P3: el newline dentro de un campo entrecomillado no debe perderse ni
    partir la fila durante la transcodificación byte-a-byte."""
    zip_path = tmp_path / "COT_2026-06.zip"
    contenido = 'a;b\n1;"linea uno\r\nlinea dos"\n'.encode("latin-1")
    _crear_zip(zip_path, {"COT1_2026-06.csv": contenido})

    rutas = extraer_csv_utf8(zip_path, tmp_path / "extraido")

    # newline="" evita que Python normalice \r\n -> \n al leer de vuelta,
    # que es exactamente lo que este test necesita verificar que NO pasó.
    with rutas[0].open(encoding="utf-8", newline="") as f:
        texto = f.read()
    assert "linea uno\r\nlinea dos" in texto
