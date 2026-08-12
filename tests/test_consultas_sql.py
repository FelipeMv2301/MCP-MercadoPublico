"""Tests de lake/consultas_sql.py — validación de sólo-lectura + paginación."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico.lake import consultas_sql


@pytest.fixture()
def con():
    conexion = duckdb.connect()
    yield conexion
    conexion.close()


def _particion_oc(data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    destino = data_dir / "oc" / f"anio={anio}" / f"mes={mes}"
    destino.mkdir(parents=True, exist_ok=True)
    conexion = duckdb.connect()
    try:
        valores = ", ".join(
            "({codigo}, {proveedor}, {monto})".format(**f) for f in filas
        )
        conexion.sql(
            f"SELECT * FROM (VALUES {valores}) AS v(codigo, proveedor, monto)"
        ).write_parquet(str(destino / "part.parquet"), compression="zstd")
    finally:
        conexion.close()


def _lake_oc_con_n_filas(data_dir: Path, n: int) -> None:
    filas = [{"codigo": i, "proveedor": f"'P{i}'", "monto": i * 100} for i in range(n)]
    _particion_oc(data_dir, 2026, 6, filas)


# --- _validar_solo_lectura -------------------------------------------------


@pytest.mark.parametrize("sql", ["SELECT * FROM oc", "select * from oc", "  select 1", "WITH x AS (SELECT 1) SELECT * FROM x"])
def test_validar_acepta_select_y_with(sql):
    consultas_sql._validar_solo_lectura(sql)  # no debe lanzar


def test_validar_acepta_select_con_punto_y_coma_final():
    consultas_sql._validar_solo_lectura("SELECT 1;")


@pytest.mark.parametrize("sql", [
    "DROP TABLE oc",
    "DELETE FROM oc",
    "INSERT INTO oc VALUES (1)",
    "UPDATE oc SET monto=0",
    "ATTACH 'otro.db' AS otro",
    "COPY oc TO 'salida.csv'",
    "INSTALL httpfs",
    "LOAD httpfs",
    "PRAGMA database_list",
    "SET memory_limit='1GB'",
    "CREATE VIEW x AS SELECT 1",
    "CALL algo()",
])
def test_validar_rechaza_comandos_no_lectura(sql):
    with pytest.raises(consultas_sql.ConsultaSqlInvalida):
        consultas_sql._validar_solo_lectura(sql)


def test_validar_rechaza_multiples_statements():
    with pytest.raises(consultas_sql.ConsultaSqlInvalida, match="único statement"):
        consultas_sql._validar_solo_lectura("SELECT 1; DROP TABLE oc;")


def test_validar_rechaza_vacio():
    with pytest.raises(consultas_sql.ConsultaSqlInvalida):
        consultas_sql._validar_solo_lectura("   ")


def test_validar_rechaza_que_no_empiece_con_select_o_with():
    with pytest.raises(consultas_sql.ConsultaSqlInvalida, match="SELECT o WITH"):
        consultas_sql._validar_solo_lectura("EXPLAIN SELECT 1")


def test_validar_no_se_engana_por_palabra_prohibida_dentro_de_un_string():
    """'DROPBOX' no debe gatillar el blocklist de 'DROP' por \\b — el
    regex usa límites de palabra, no substring."""
    consultas_sql._validar_solo_lectura("SELECT * FROM oc WHERE proveedor = 'DROPBOX SA'")


# --- _registrar_vistas -----------------------------------------------------


def test_registrar_vistas_solo_incluye_datasets_con_datos(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _lake_oc_con_n_filas(data_dir, 3)

    disponibles = consultas_sql._registrar_vistas(con, data_dir)

    assert disponibles == ["oc"]
    assert con.execute("SELECT COUNT(*) FROM oc").fetchone()[0] == 3


def test_registrar_vistas_lake_vacio_no_registra_nada(con, tmp_path: Path):
    disponibles = consultas_sql._registrar_vistas(con, tmp_path / "data")
    assert disponibles == []


# --- ejecutar_consulta (validación + vistas + paginación integradas) ------


def test_ejecutar_consulta_lee_la_vista_del_dataset(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _lake_oc_con_n_filas(data_dir, 5)

    filas, hay_mas, disponibles = consultas_sql.ejecutar_consulta(
        con, data_dir, "SELECT * FROM oc ORDER BY codigo", offset=0, limite=100
    )

    assert disponibles == ["oc"]
    assert hay_mas is False
    assert [f["codigo"] for f in filas] == [0, 1, 2, 3, 4]


def test_ejecutar_consulta_pagina_sin_solapar_ni_saltar(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _lake_oc_con_n_filas(data_dir, 25)

    vistos = []
    offset, limite = 0, 10
    for _ in range(5):
        filas, hay_mas, _ = consultas_sql.ejecutar_consulta(
            con, data_dir, "SELECT * FROM oc ORDER BY codigo", offset=offset, limite=limite
        )
        vistos.extend(f["codigo"] for f in filas)
        if not hay_mas:
            break
        offset += limite

    assert vistos == list(range(25))


def test_ejecutar_consulta_rechaza_comando_no_lectura_antes_de_tocar_el_lake(con, tmp_path: Path):
    with pytest.raises(consultas_sql.ConsultaSqlInvalida):
        consultas_sql.ejecutar_consulta(
            con, tmp_path / "data", "DROP TABLE oc", offset=0, limite=10
        )


def test_ejecutar_consulta_sobre_dataset_sin_datos_lanza_error_duckdb(con, tmp_path: Path):
    """'lic' no tiene vista registrada si no hay parquet — DuckDB debe
    fallar con tabla no encontrada, no devolver vacío en silencio."""
    with pytest.raises(duckdb.Error):
        consultas_sql.ejecutar_consulta(
            con, tmp_path / "data", "SELECT * FROM lic", offset=0, limite=10
        )


def test_ejecutar_consulta_serializa_decimal_a_float(con, tmp_path: Path):
    filas, _, _ = consultas_sql.ejecutar_consulta(
        con, tmp_path / "data", "SELECT CAST(1.5 AS DECIMAL(10,2)) AS monto", offset=0, limite=10
    )
    assert filas == [{"monto": 1.5}]
    assert isinstance(filas[0]["monto"], float)


def test_ejecutar_consulta_serializa_fecha_a_isoformat(con, tmp_path: Path):
    filas, _, _ = consultas_sql.ejecutar_consulta(
        con, tmp_path / "data", "SELECT DATE '2026-06-15' AS f", offset=0, limite=10
    )
    assert filas == [{"f": "2026-06-15"}]
