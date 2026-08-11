"""Tests de server.head_to_head — paginación por offset/limite.

No usan get_settings() (singleton con lru_cache, ver config.py) — se
monkeypatchea server.get_settings con una Settings construida a mano sobre
tmp_path, siguiendo el mismo patrón que test_config.py usa para Identidad.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico import limites, server
from mcp_mercadopublico.config import Settings, cargar_identidad

BIOQUIMICA = "76.563.320-6"
RIVAL = "76.502.658-K"

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


def _settings(tmp_path: Path) -> Settings:
    identidad_toml = tmp_path / "identidad.toml"
    identidad_toml.write_text(TOML_MINIMO, encoding="utf-8")
    identidad = cargar_identidad(identidad_toml)
    return Settings(identidad=identidad, data_dir=tmp_path / "data")


def _particion_lic(data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    con = duckdb.connect()
    try:
        destino = data_dir / "lic" / f"anio={anio}" / f"mes={mes}"
        destino.mkdir(parents=True, exist_ok=True)
        valores = ", ".join(
            "('{codigo_externo}', '{rut_proveedor}', '{razon_social_proveedor}', "
            "'{nombre_producto_genrico}', {valor_total_ofertado}, '{oferta_seleccionada}', "
            "'{criterios_evaluacion}')".format(**f)
            for f in filas
        )
        con.sql(
            f"SELECT * FROM (VALUES {valores}) AS v("
            '"codigo_externo", "rut_proveedor", "razon_social_proveedor", '
            '"nombre_producto_genrico", "valor_total_ofertado", "oferta_seleccionada", '
            '"criterios_evaluacion")'
        ).write_parquet(str(destino / "part.parquet"), compression="zstd")
    finally:
        con.close()


def _particion_cot(data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    con = duckdb.connect()
    try:
        destino = data_dir / "cot" / f"anio={anio}" / f"mes={mes}"
        destino.mkdir(parents=True, exist_ok=True)
        valores = ", ".join(
            "('{codigo_cotizacion}', '{rutproveedor}', '{razon_social_proveedor}', "
            "'{nombre_producto_generico}', {monto_total}, '{proveedor_seleccionado}', "
            "'{nombre_criterio}', '{tamano}')".format(**f)
            for f in filas
        )
        con.sql(
            f"SELECT * FROM (VALUES {valores}) AS v("
            '"codigo_cotizacion", "rutproveedor", "razon_social_proveedor", '
            '"nombre_producto_generico", "monto_total", "proveedor_seleccionado", '
            '"nombre_criterio", "tamano")'
        ).write_parquet(str(destino / "part.parquet"), compression="zstd")
    finally:
        con.close()


def _fila_lic(codigo: str, *, ganamos: bool = True) -> list[dict]:
    sel_nosotros = "Seleccionada" if ganamos else "No Seleccionada"
    sel_rival = "No Seleccionada" if ganamos else "Seleccionada"
    return [
        {"codigo_externo": codigo, "rut_proveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
         "nombre_producto_genrico": "x", "valor_total_ofertado": 100, "oferta_seleccionada": sel_nosotros,
         "criterios_evaluacion": "precio"},
        {"codigo_externo": codigo, "rut_proveedor": RIVAL, "razon_social_proveedor": "Rival",
         "nombre_producto_genrico": "x", "valor_total_ofertado": 110, "oferta_seleccionada": sel_rival,
         "criterios_evaluacion": "precio"},
    ]


def _lake_con_n_cruces_lic(data_dir: Path, n: int) -> None:
    filas = [fila for i in range(n) for fila in _fila_lic(f"P{i:04d}")]
    _particion_lic(data_dir, 2026, 6, filas)


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "get_settings", lambda: s)
    return s


def test_pagina_completa_cuando_no_hay_mas_cruces_que_el_limite(settings: Settings):
    _lake_con_n_cruces_lic(settings.data_dir, 3)

    resultado = server.head_to_head(RIVAL)

    assert resultado["total_cruces"] == 3
    assert resultado["hay_mas"] is False
    assert len(resultado["cruces"]) == 3
    assert resultado["resumen"]["n_cruces"] == 3


def test_offset_y_limite_devuelven_el_slice_esperado(settings: Settings):
    _lake_con_n_cruces_lic(settings.data_dir, 10)

    resultado = server.head_to_head(RIVAL, offset=3, limite=4)

    codigos = [c["codigo_proceso"] for c in resultado["cruces"]]
    assert codigos == ["P0003", "P0004", "P0005", "P0006"]
    assert resultado["total_cruces"] == 10
    assert resultado["hay_mas"] is True  # offset(3) + limite(4) = 7 < 10


def test_ultima_pagina_marca_hay_mas_false(settings: Settings):
    _lake_con_n_cruces_lic(settings.data_dir, 10)

    resultado = server.head_to_head(RIVAL, offset=8, limite=4)

    codigos = [c["codigo_proceso"] for c in resultado["cruces"]]
    assert codigos == ["P0008", "P0009"]
    assert resultado["hay_mas"] is False


def test_offset_mas_alla_del_total_devuelve_pagina_vacia(settings: Settings):
    _lake_con_n_cruces_lic(settings.data_dir, 5)

    resultado = server.head_to_head(RIVAL, offset=5, limite=50)

    assert resultado["cruces"] == []
    assert resultado["hay_mas"] is False
    assert resultado["total_cruces"] == 5


def test_paginas_sucesivas_reconstruyen_el_100pct_sin_solapar_ni_saltar(settings: Settings):
    """El caso de uso central del pedido: offset=0,50,100... hasta hay_mas=false
    debe devolver exactamente el universo completo, sin duplicados ni huecos."""
    _lake_con_n_cruces_lic(settings.data_dir, 137)

    vistos: list[str] = []
    offset = 0
    limite = 50
    paginas = 0
    while True:
        resultado = server.head_to_head(RIVAL, offset=offset, limite=limite)
        vistos.extend(c["codigo_proceso"] for c in resultado["cruces"])
        paginas += 1
        assert paginas < 10  # guarda contra loop infinito si hay_mas nunca baja
        if not resultado["hay_mas"]:
            break
        offset += limite

    esperados = [f"P{i:04d}" for i in range(137)]
    assert vistos == esperados  # orden + cobertura exacta, sin duplicados


def test_resumen_no_cambia_segun_la_pagina_pedida(settings: Settings):
    """El resumen (n_cruces, ganados_por_nosotros, mediana) corre sobre el
    universo completo — no debe variar según offset/limite (punto 2 del
    pedido de paginación)."""
    filas = []
    for i in range(8):
        filas.extend(_fila_lic(f"P{i:04d}", ganamos=(i % 2 == 0)))
    _particion_lic(settings.data_dir, 2026, 6, filas)

    pagina_1 = server.head_to_head(RIVAL, offset=0, limite=3)
    pagina_2 = server.head_to_head(RIVAL, offset=3, limite=3)

    assert pagina_1["resumen"] == pagina_2["resumen"]
    assert pagina_1["resumen"]["n_cruces"] == 8
    assert pagina_1["resumen"]["ganados_por_nosotros"] == 4
    assert pagina_1["total_cruces"] == pagina_2["total_cruces"] == 8


def test_limite_se_clampa_al_maximo_duro(settings: Settings):
    n = limites.LIMITE_MAXIMO_HEAD_TO_HEAD + 20
    _lake_con_n_cruces_lic(settings.data_dir, n)

    resultado = server.head_to_head(RIVAL, offset=0, limite=100_000)

    assert len(resultado["cruces"]) == limites.LIMITE_MAXIMO_HEAD_TO_HEAD
    assert resultado["total_cruces"] == n
    assert resultado["hay_mas"] is True


def test_offset_negativo_es_rechazado(settings: Settings):
    _lake_con_n_cruces_lic(settings.data_dir, 3)

    resultado = server.head_to_head(RIVAL, offset=-1)

    assert "error" in resultado


def test_limite_cero_o_negativo_es_rechazado(settings: Settings):
    _lake_con_n_cruces_lic(settings.data_dir, 3)

    assert "error" in server.head_to_head(RIVAL, limite=0)
    assert "error" in server.head_to_head(RIVAL, limite=-5)


def test_canal_combinado_con_paginacion_filtra_antes_de_paginar(settings: Settings):
    """canal='lic' + offset/limite: la paginación debe operar sólo sobre los
    cruces de ese canal, no sobre lic+cot combinados (punto 5 del pedido)."""
    _lake_con_n_cruces_lic(settings.data_dir, 6)
    filas_cot = [fila for i in range(6, 9) for fila in [
        {"codigo_cotizacion": f"P{i:04d}", "rutproveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
         "nombre_producto_generico": "x", "monto_total": 100, "proveedor_seleccionado": "si",
         "nombre_criterio": "precio", "tamano": "MiPyme"},
        {"codigo_cotizacion": f"P{i:04d}", "rutproveedor": RIVAL, "razon_social_proveedor": "Rival",
         "nombre_producto_generico": "x", "monto_total": 90, "proveedor_seleccionado": "no",
         "nombre_criterio": "precio", "tamano": "MiPyme"},
    ]]
    _particion_cot(settings.data_dir, 2026, 6, filas_cot)

    resultado = server.head_to_head(RIVAL, canal="lic", offset=0, limite=50)

    assert resultado["total_cruces"] == 6  # sólo los 6 de 'lic', no los 3 de 'cot'
    assert all(c["canal"] == "lic" for c in resultado["cruces"])
