"""Tests de catalogo.py — HU-3.1/3.2."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico import catalogo


@pytest.fixture()
def con():
    conexion = duckdb.connect()
    yield conexion
    conexion.close()


def _crear_particion_oc(con, data_dir: Path, filas: list[dict]) -> None:
    """filas: [{"codigo_producto_onu": ..., "nombreroducto_generico": ..., "rut_sucursal": ...}]"""
    destino = data_dir / "oc" / "anio=2026" / "mes=6"
    destino.mkdir(parents=True, exist_ok=True)
    valores = ", ".join(
        f"('{f['codigo_producto_onu']}', '{f['nombreroducto_generico']}', '{f['rut_sucursal']}')"
        for f in filas
    )
    con.sql(
        f"SELECT * FROM (VALUES {valores}) AS "
        f'v("codigo_producto_onu", "nombreroducto_generico", "rut_sucursal")'
    ).write_parquet(str(destino / "part.parquet"), compression="zstd")


def _crear_particion_cot(con, data_dir: Path, filas: list[dict]) -> None:
    destino = data_dir / "cot" / "anio=2026" / "mes=6"
    destino.mkdir(parents=True, exist_ok=True)
    valores = ", ".join(
        f"('{f['codigo_producto']}', '{f['nombre_producto_generico']}', '{f['rutproveedor']}')"
        for f in filas
    )
    con.sql(
        f"SELECT * FROM (VALUES {valores}) AS "
        f'v("codigo_producto", "nombre_producto_generico", "rutproveedor")'
    ).write_parquet(str(destino / "part.parquet"), compression="zstd")


RUT_BIOQUIMICA = "76563320-6"


# --- buscar_producto_en_historial ------------------------------------------


def test_lake_vacio_no_es_error(con, tmp_path: Path):
    assert catalogo.lake_tiene_datos(tmp_path / "data") is False
    resultados = catalogo.buscar_producto_en_historial(
        con, tmp_path / "data", texto="acido", solo_propio=False
    )
    assert resultados == []


def test_requiere_texto_o_codigo_onu(con, tmp_path: Path):
    with pytest.raises(ValueError, match="texto o codigo_onu"):
        catalogo.buscar_producto_en_historial(con, tmp_path / "data")


def test_solo_propio_requiere_rut(con, tmp_path: Path):
    with pytest.raises(ValueError, match="rut_propio"):
        catalogo.buscar_producto_en_historial(con, tmp_path / "data", texto="x", solo_propio=True)


def test_busca_por_texto_filtrando_por_rut_propio(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _crear_particion_oc(
        con, data_dir,
        [
            {"codigo_producto_onu": "41116007", "nombreroducto_generico": "Acido Citrico", "rut_sucursal": RUT_BIOQUIMICA},
            {"codigo_producto_onu": "41116007", "nombreroducto_generico": "Acido Citrico", "rut_sucursal": "99999999-9"},
            {"codigo_producto_onu": "99999999", "nombreroducto_generico": "Otro producto", "rut_sucursal": RUT_BIOQUIMICA},
        ],
    )

    resultados = catalogo.buscar_producto_en_historial(
        con, data_dir, texto="citrico", solo_propio=True, rut_propio="76.563.320-6"
    )

    assert len(resultados) == 1
    assert resultados[0].codigo_onu == "41116007"
    assert resultados[0].dataset == "oc"
    assert resultados[0].n_apariciones == 1  # sólo la fila de Bioquimica, no la del otro RUT


def test_solo_propio_false_incluye_todo_el_mercado(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _crear_particion_oc(
        con, data_dir,
        [
            {"codigo_producto_onu": "41116007", "nombreroducto_generico": "Acido Citrico", "rut_sucursal": RUT_BIOQUIMICA},
            {"codigo_producto_onu": "41116007", "nombreroducto_generico": "Acido Citrico", "rut_sucursal": "99999999-9"},
        ],
    )

    resultados = catalogo.buscar_producto_en_historial(
        con, data_dir, texto="citrico", solo_propio=False
    )

    assert resultados[0].n_apariciones == 2
    assert resultados[0].n_vendedores_distintos == 2


def test_busca_por_codigo_onu(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _crear_particion_oc(
        con, data_dir,
        [{"codigo_producto_onu": "41116007", "nombreroducto_generico": "Acido Citrico", "rut_sucursal": RUT_BIOQUIMICA}],
    )

    resultados = catalogo.buscar_producto_en_historial(
        con, data_dir, codigo_onu="41116007", solo_propio=False
    )

    assert len(resultados) == 1
    assert resultados[0].texto_producto == "Acido Citrico"


def test_busca_a_traves_de_multiples_datasets(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _crear_particion_oc(
        con, data_dir,
        [{"codigo_producto_onu": "41116007", "nombreroducto_generico": "Acido Citrico", "rut_sucursal": RUT_BIOQUIMICA}],
    )
    _crear_particion_cot(
        con, data_dir,
        [{"codigo_producto": "41116007", "nombre_producto_generico": "Acido Citrico Kg", "rutproveedor": RUT_BIOQUIMICA}],
    )

    resultados = catalogo.buscar_producto_en_historial(
        con, data_dir, codigo_onu="41116007", solo_propio=False
    )

    datasets = {r.dataset for r in resultados}
    assert datasets == {"oc", "cot"}


def test_lake_tiene_datos_true_si_hay_alguna_particion(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _crear_particion_oc(
        con, data_dir,
        [{"codigo_producto_onu": "1", "nombreroducto_generico": "x", "rut_sucursal": RUT_BIOQUIMICA}],
    )
    assert catalogo.lake_tiene_datos(data_dir) is True


# --- registrar/obtener/listar mapeos ----------------------------------------


def test_mapeo_inexistente_devuelve_none(tmp_path: Path):
    assert catalogo.obtener_mapeo_sku_onu(tmp_path / "mapeos.sqlite", "RP0032F1") is None


def test_registrar_y_obtener_mapeo(tmp_path: Path):
    ruta = tmp_path / "mapeos.sqlite"
    catalogo.registrar_mapeo_sku_onu(ruta, "RP0032F1", "41116007", "alta", "confirmado en conversacion")

    mapeo = catalogo.obtener_mapeo_sku_onu(ruta, "RP0032F1")
    assert mapeo.codigo_onu == "41116007"
    assert mapeo.confianza == "alta"


def test_registrar_mapeo_es_idempotente(tmp_path: Path):
    ruta = tmp_path / "mapeos.sqlite"
    catalogo.registrar_mapeo_sku_onu(ruta, "RP0032F1", "41116007", "media")
    catalogo.registrar_mapeo_sku_onu(ruta, "RP0032F1", "41116008", "alta")

    mapeo = catalogo.obtener_mapeo_sku_onu(ruta, "RP0032F1")
    assert mapeo.codigo_onu == "41116008"
    assert mapeo.confianza == "alta"
    assert len(catalogo.listar_mapeos_sku_onu(ruta)) == 1


def test_listar_mapeos(tmp_path: Path):
    ruta = tmp_path / "mapeos.sqlite"
    catalogo.registrar_mapeo_sku_onu(ruta, "RP0032F1", "41116007", "alta")
    catalogo.registrar_mapeo_sku_onu(ruta, "RP0145B1", "41103211", "media")

    assert len(catalogo.listar_mapeos_sku_onu(ruta)) == 2


# --- resolver_producto -------------------------------------------------------


def test_resolver_producto_via_mapeo_confirmado(tmp_path: Path):
    ruta = tmp_path / "mapeos.sqlite"
    catalogo.registrar_mapeo_sku_onu(ruta, "RP0032F1", "41116007", "alta")

    r = catalogo.resolver_producto("RP0032F1", ruta)

    assert r.codigo_onu == "41116007"
    assert r.metodo == "mapeo_confirmado"
    assert r.confianza == "alta"


def test_resolver_producto_codigo_literal(tmp_path: Path):
    r = catalogo.resolver_producto("41116007", tmp_path / "mapeos.sqlite")

    assert r.codigo_onu == "41116007"
    assert r.metodo == "codigo_literal"
    assert r.confianza == "alta"


def test_resolver_producto_sin_resolucion(tmp_path: Path):
    r = catalogo.resolver_producto("Acido Citrico 1 Kg", tmp_path / "mapeos.sqlite")

    assert r.codigo_onu is None
    assert r.metodo == "sin_resolucion"
    assert r.confianza == "ninguna"


def test_resolver_producto_prioriza_mapeo_sobre_lectura_literal(tmp_path: Path):
    """Si alguien registró un SKU que, por coincidencia, tiene forma de
    código ONU (8 dígitos), el mapeo confirmado gana — no lo literal."""
    ruta = tmp_path / "mapeos.sqlite"
    catalogo.registrar_mapeo_sku_onu(ruta, "12345678", "99999999", "alta")

    r = catalogo.resolver_producto("12345678", ruta)

    assert r.codigo_onu == "99999999"
    assert r.metodo == "mapeo_confirmado"
