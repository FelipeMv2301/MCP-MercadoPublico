"""Tests de manifest.py — HU-2.5."""

from __future__ import annotations

from pathlib import Path

from mcp_mercadopublico.lake.manifest import (
    listar_periodos,
    obtener_periodo,
    registrar_periodo,
)


def test_periodo_inexistente_devuelve_none(tmp_path: Path):
    ruta = tmp_path / "manifest.sqlite"
    assert obtener_periodo(ruta, "oc", "2026-6") is None


def test_registrar_y_obtener_periodo(tmp_path: Path):
    ruta = tmp_path / "manifest.sqlite"
    registrar_periodo(
        ruta,
        dataset="oc",
        periodo="2026-6",
        etag='"abc123"',
        last_modified="Wed, 05 Aug 2026 10:05:32 GMT",
        filas_leidas=437538,
        filas_escritas=39421,
        filas_descartadas=398117,
        estado="ingerido",
    )
    registro = obtener_periodo(ruta, "oc", "2026-6")
    assert registro is not None
    assert registro.etag == '"abc123"'
    assert registro.filas_leidas == 437538
    assert registro.filas_escritas == 39421
    assert registro.estado == "ingerido"


def test_reingesta_es_idempotente_reemplaza_no_duplica(tmp_path: Path):
    ruta = tmp_path / "manifest.sqlite"
    registrar_periodo(
        ruta, dataset="oc", periodo="2026-6", etag='"v1"', last_modified=None,
        filas_leidas=100, filas_escritas=50, filas_descartadas=50, estado="ingerido",
    )
    registrar_periodo(
        ruta, dataset="oc", periodo="2026-6", etag='"v2"', last_modified=None,
        filas_leidas=200, filas_escritas=90, filas_descartadas=110, estado="ingerido",
    )

    registro = obtener_periodo(ruta, "oc", "2026-6")
    assert registro.etag == '"v2"'
    assert registro.filas_leidas == 200

    todos = listar_periodos(ruta, "oc")
    assert len(todos) == 1  # no duplicó la fila


def test_listar_periodos_filtra_por_dataset(tmp_path: Path):
    ruta = tmp_path / "manifest.sqlite"
    registrar_periodo(
        ruta, dataset="oc", periodo="2026-6", etag=None, last_modified=None,
        filas_leidas=1, filas_escritas=1, filas_descartadas=0, estado="ingerido",
    )
    registrar_periodo(
        ruta, dataset="lic", periodo="2026-6", etag=None, last_modified=None,
        filas_leidas=1, filas_escritas=1, filas_descartadas=0, estado="ingerido",
    )

    assert len(listar_periodos(ruta, "oc")) == 1
    assert len(listar_periodos(ruta, "lic")) == 1
    assert len(listar_periodos(ruta)) == 2


def test_wal_mode_activado(tmp_path: Path):
    """El archivo -wal se borra al cerrar la conexión (checkpoint automático
    de SQLite) — hay que preguntar el modo mientras la conexión está viva,
    no inferirlo de archivos que sólo existen de forma transitoria."""
    import sqlite3

    ruta = tmp_path / "manifest.sqlite"
    registrar_periodo(
        ruta, dataset="oc", periodo="2026-6", etag=None, last_modified=None,
        filas_leidas=0, filas_escritas=0, filas_descartadas=0, estado="ingerido",
    )
    con = sqlite3.connect(ruta)
    try:
        modo = con.execute("PRAGMA journal_mode").fetchone()[0]
        assert modo.lower() == "wal"
    finally:
        con.close()
