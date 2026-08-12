"""Tests de server.consultar_lake — wiring de la tool (validación, límites,
paginación, y que un error de la consulta no rompa el proceso)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico import limites, server
from mcp_mercadopublico.config import Settings, cargar_identidad

TOML_MINIMO = """
[nosotros]
rut = "76.563.320-6"

[ingesta]
periodo_desde = "2025-1"
periodo_hasta = "2026-8"
datasets = ["oc"]
filtro = "rubro_n1"
rubros_n1 = []
"""


def _particion_oc(data_dir: Path, n: int) -> None:
    destino = data_dir / "oc" / "anio=2026" / "mes=6"
    destino.mkdir(parents=True, exist_ok=True)
    valores = ", ".join(f"({i}, {i * 100})" for i in range(n))
    con = duckdb.connect()
    try:
        con.sql(f"SELECT * FROM (VALUES {valores}) AS v(codigo, monto)").write_parquet(
            str(destino / "part.parquet"), compression="zstd"
        )
    finally:
        con.close()


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    identidad_toml = tmp_path / "identidad.toml"
    identidad_toml.write_text(TOML_MINIMO, encoding="utf-8")
    identidad = cargar_identidad(identidad_toml)
    s = Settings(identidad=identidad, data_dir=tmp_path / "data")
    monkeypatch.setattr(server, "get_settings", lambda: s)
    return s


def test_consultar_lake_devuelve_filas_de_la_vista(settings: Settings):
    _particion_oc(settings.data_dir, 5)

    resultado = server.consultar_lake("SELECT * FROM oc ORDER BY codigo")

    assert resultado["n_filas"] == 5
    assert resultado["hay_mas"] is False
    assert resultado["datasets_disponibles"] == ["oc"]
    assert [f["codigo"] for f in resultado["filas"]] == [0, 1, 2, 3, 4]


def test_consultar_lake_pagina_con_offset_y_limite(settings: Settings):
    _particion_oc(settings.data_dir, 10)

    resultado = server.consultar_lake("SELECT * FROM oc ORDER BY codigo", offset=3, limite=4)

    assert [f["codigo"] for f in resultado["filas"]] == [3, 4, 5, 6]
    assert resultado["hay_mas"] is True


def test_consultar_lake_rechaza_comando_no_select(settings: Settings):
    resultado = server.consultar_lake("DROP TABLE oc")
    assert "error" in resultado


def test_consultar_lake_offset_negativo_rechazado(settings: Settings):
    assert "error" in server.consultar_lake("SELECT 1", offset=-1)


def test_consultar_lake_limite_invalido_rechazado(settings: Settings):
    assert "error" in server.consultar_lake("SELECT 1", limite=0)


def test_consultar_lake_limite_se_clampa_al_maximo_duro(settings: Settings):
    n = limites.LIMITE_MAXIMO_CONSULTA_SQL + 20
    _particion_oc(settings.data_dir, n)

    resultado = server.consultar_lake("SELECT * FROM oc", limite=100_000)

    assert resultado["n_filas"] == limites.LIMITE_MAXIMO_CONSULTA_SQL
    assert resultado["hay_mas"] is True


def test_consultar_lake_error_de_sql_no_rompe_devuelve_error(settings: Settings):
    _particion_oc(settings.data_dir, 3)

    resultado = server.consultar_lake("SELECT columna_que_no_existe FROM oc")

    assert "error" in resultado


def test_consultar_lake_dataset_sin_datos_no_aparece_disponible(settings: Settings):
    """Sin ninguna partición ingerida, ninguna vista existe — consultar
    'oc' debe fallar con error claro, no devolver vacío en silencio."""
    resultado = server.consultar_lake("SELECT * FROM oc")

    assert "error" in resultado
