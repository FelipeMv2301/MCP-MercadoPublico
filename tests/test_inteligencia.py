"""Tests de inteligencia.py — HU-4.1/4.2/4.3/4.4.

Los nombres de columna snake_case usados en los builders fueron verificados
con a_snake_case() antes de escribir estos tests (no transcritos de memoria):
'Oferta seleccionada' -> oferta_seleccionada, 'RUTProveedor' -> rutproveedor
(sin guion — mayúsculas consecutivas), etc.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico import inteligencia as intel

BIOQUIMICA = "76.563.320-6"
RIVAL_1 = "76.502.658-K"
RIVAL_2 = "78.116.970-6"


@pytest.fixture()
def con():
    conexion = duckdb.connect()
    yield conexion
    conexion.close()


def _particion_oc(con, data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    destino = data_dir / "oc" / f"anio={anio}" / f"mes={mes}"
    destino.mkdir(parents=True, exist_ok=True)
    valores = ", ".join(
        "('{rut_sucursal}', '{nombre_proveedor}', '{organismo_publico}', '{rubro_n2}', "
        "'{nombreroducto_generico}', {total_linea_neto}, {es_clp})".format(**f)
        for f in filas
    )
    con.sql(
        f"SELECT * FROM (VALUES {valores}) AS v("
        '"rut_sucursal", "nombre_proveedor", "organismo_publico", "rubro_n2", '
        '"nombreroducto_generico", "total_linea_neto", "es_clp")'
    ).write_parquet(str(destino / "part.parquet"), compression="zstd")


def _particion_lic(con, data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
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


def _particion_cot(con, data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
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


# --- descubrir_rivales -------------------------------------------------------


def test_descubrir_rivales_por_lic(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "rut_proveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_genrico": "kit", "valor_total_ofertado": 100, "oferta_seleccionada": "Seleccionada",
             "criterios_evaluacion": "precio"},
            {"codigo_externo": "P1", "rut_proveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_genrico": "kit", "valor_total_ofertado": 120, "oferta_seleccionada": "No Seleccionada",
             "criterios_evaluacion": "precio"},
            {"codigo_externo": "P2", "rut_proveedor": RIVAL_2, "razon_social_proveedor": "Rival Dos",
             "nombre_producto_genrico": "otro", "valor_total_ofertado": 50, "oferta_seleccionada": "Seleccionada",
             "criterios_evaluacion": "precio"},
        ],
    )

    rivales = intel.descubrir_rivales(con, data_dir, BIOQUIMICA)

    assert len(rivales) == 1  # sólo RIVAL_1 comparte proceso (P1) con Bioquimica
    assert rivales[0].rut == RIVAL_1
    assert rivales[0].canal == "lic"
    assert rivales[0].n_cruces == 1


def test_descubrir_rivales_marca_watchlist(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_cot(
        con, data_dir, 2026, 6,
        [
            {"codigo_cotizacion": "C1", "rutproveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_generico": "x", "monto_total": 100, "proveedor_seleccionado": "si",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
            {"codigo_cotizacion": "C1", "rutproveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_generico": "x", "monto_total": 90, "proveedor_seleccionado": "no",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
        ],
    )

    rivales = intel.descubrir_rivales(
        con, data_dir, BIOQUIMICA, ruts_watchlist={RIVAL_1}
    )

    assert rivales[0].en_watchlist is True


def test_descubrir_rivales_filtra_por_canal(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "rut_proveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_genrico": "kit", "valor_total_ofertado": 100, "oferta_seleccionada": "Seleccionada",
             "criterios_evaluacion": "precio"},
            {"codigo_externo": "P1", "rut_proveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_genrico": "kit", "valor_total_ofertado": 120, "oferta_seleccionada": "No Seleccionada",
             "criterios_evaluacion": "precio"},
        ],
    )
    _particion_cot(
        con, data_dir, 2026, 6,
        [
            {"codigo_cotizacion": "C1", "rutproveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_generico": "x", "monto_total": 100, "proveedor_seleccionado": "si",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
            {"codigo_cotizacion": "C1", "rutproveedor": RIVAL_2, "razon_social_proveedor": "Rival Dos",
             "nombre_producto_generico": "x", "monto_total": 90, "proveedor_seleccionado": "no",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
        ],
    )

    solo_lic = intel.descubrir_rivales(con, data_dir, BIOQUIMICA, canal="lic")
    assert {r.rut for r in solo_lic} == {RIVAL_1}

    solo_cot = intel.descubrir_rivales(con, data_dir, BIOQUIMICA, canal="cot")
    assert {r.rut for r in solo_cot} == {RIVAL_2}


def test_descubrir_rivales_canal_invalido(con, tmp_path: Path):
    with pytest.raises(ValueError, match="canal"):
        intel.descubrir_rivales(con, tmp_path / "data", BIOQUIMICA, canal="oc")


def test_descubrir_rivales_lake_vacio(con, tmp_path: Path):
    assert intel.descubrir_rivales(con, tmp_path / "data", BIOQUIMICA) == []


# --- perfil_competidor -------------------------------------------------------


def test_perfil_competidor_monto_y_evolucion(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 5,
        [{"rut_sucursal": RIVAL_1, "nombre_proveedor": "Rival Uno", "organismo_publico": "HOSPITAL X",
          "rubro_n2": "Equipos e insumos para laboratorio", "nombreroducto_generico": "reactivo",
          "total_linea_neto": 1000, "es_clp": "true"}],
    )
    _particion_oc(
        con, data_dir, 2026, 6,
        [{"rut_sucursal": RIVAL_1, "nombre_proveedor": "Rival Uno", "organismo_publico": "HOSPITAL X",
          "rubro_n2": "Equipos e insumos para laboratorio", "nombreroducto_generico": "reactivo",
          "total_linea_neto": 2000, "es_clp": "true"}],
    )

    perfil = intel.perfil_competidor(con, data_dir, RIVAL_1)

    assert perfil.nombre == "Rival Uno"
    assert perfil.monto_total_clp == 3000
    assert perfil.n_lineas == 2
    assert perfil.ticket_promedio == 1500
    assert perfil.evolucion_mensual == [
        {"periodo": "2026-5", "monto": 1000.0, "n": 1},
        {"periodo": "2026-6", "monto": 2000.0, "n": 1},
    ]
    assert perfil.top_organismos[0]["organismo"] == "HOSPITAL X"


def test_perfil_competidor_excluye_moneda_no_clp(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 6,
        [
            {"rut_sucursal": RIVAL_1, "nombre_proveedor": "Rival Uno", "organismo_publico": "X",
             "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 1000, "es_clp": "true"},
            {"rut_sucursal": RIVAL_1, "nombre_proveedor": "Rival Uno", "organismo_publico": "X",
             "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 999999, "es_clp": "false"},
        ],
    )

    perfil = intel.perfil_competidor(con, data_dir, RIVAL_1)

    assert perfil.monto_total_clp == 1000  # la fila no-CLP no contamina el total
    assert perfil.n_lineas == 1


def test_perfil_competidor_liga(con, tmp_path: Path):
    perfil_a = intel.perfil_competidor(
        con, tmp_path / "data", RIVAL_1, liga_a={RIVAL_1}, liga_b={RIVAL_2}
    )
    assert perfil_a.liga == "A"

    perfil_b = intel.perfil_competidor(
        con, tmp_path / "data", RIVAL_2, liga_a={RIVAL_1}, liga_b={RIVAL_2}
    )
    assert perfil_b.liga == "B"

    perfil_sin_liga = intel.perfil_competidor(
        con, tmp_path / "data", "11.111.111-1", liga_a={RIVAL_1}, liga_b={RIVAL_2}
    )
    assert perfil_sin_liga.liga is None


def test_perfil_competidor_win_rate_y_tamano_desde_cot(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_cot(
        con, data_dir, 2026, 6,
        [
            {"codigo_cotizacion": "C1", "rutproveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_generico": "x", "monto_total": 100, "proveedor_seleccionado": "si",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
            {"codigo_cotizacion": "C2", "rutproveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_generico": "x", "monto_total": 100, "proveedor_seleccionado": "no",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
        ],
    )

    perfil = intel.perfil_competidor(con, data_dir, RIVAL_1)

    assert perfil.win_rate == {"ganadas": 1, "ofertadas": 2, "tasa": 0.5}
    assert perfil.tamano_empresa == "MiPyme"


def test_perfil_competidor_sin_datos_no_falla(con, tmp_path: Path):
    perfil = intel.perfil_competidor(con, tmp_path / "data", RIVAL_1)
    assert perfil.monto_total_clp == 0.0
    assert perfil.n_lineas == 0
    assert perfil.ticket_promedio is None
    assert perfil.win_rate is None


# --- radar_competencia -------------------------------------------------------


def test_radar_detecta_entrante(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 6,
        [{"rut_sucursal": RIVAL_1, "nombre_proveedor": "Rival Uno", "organismo_publico": "x",
          "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 5000, "es_clp": "true"}],
    )
    # sin datos en 2026-5 -> entrante

    movimientos = intel.radar_competencia(
        con, data_dir, anio=2026, mes=6, anio_comparar=2026, mes_comparar=5
    )

    assert len(movimientos) == 1
    assert movimientos[0].es_entrante is True
    assert movimientos[0].monto_periodo_actual == 5000
    assert movimientos[0].monto_periodo_anterior == 0


def test_radar_detecta_saliente_y_delta(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 5,
        [{"rut_sucursal": RIVAL_1, "nombre_proveedor": "Rival Uno", "organismo_publico": "x",
          "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 1000, "es_clp": "true"}],
    )
    _particion_oc(
        con, data_dir, 2026, 6,
        [{"rut_sucursal": RIVAL_2, "nombre_proveedor": "Rival Dos", "organismo_publico": "x",
          "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 3000, "es_clp": "true"}],
    )

    movimientos = intel.radar_competencia(
        con, data_dir, anio=2026, mes=6, anio_comparar=2026, mes_comparar=5
    )

    por_rut = {m.rut: m for m in movimientos}
    assert por_rut[RIVAL_1].es_saliente is True
    assert por_rut[RIVAL_2].es_entrante is True
    assert por_rut[RIVAL_2].delta_monto == 3000


def test_radar_ordena_por_magnitud_absoluta_no_por_tamano(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 5,
        [
            {"rut_sucursal": RIVAL_1, "nombre_proveedor": "Grande", "organismo_publico": "x",
             "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 1000000, "es_clp": "true"},
            {"rut_sucursal": RIVAL_2, "nombre_proveedor": "Chico", "organismo_publico": "x",
             "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 1000, "es_clp": "true"},
        ],
    )
    _particion_oc(
        con, data_dir, 2026, 6,
        [
            {"rut_sucursal": RIVAL_1, "nombre_proveedor": "Grande", "organismo_publico": "x",
             "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 1010000, "es_clp": "true"},
            {"rut_sucursal": RIVAL_2, "nombre_proveedor": "Chico", "organismo_publico": "x",
             "rubro_n2": "y", "nombreroducto_generico": "z", "total_linea_neto": 4000, "es_clp": "true"},
        ],
    )

    movimientos = intel.radar_competencia(
        con, data_dir, anio=2026, mes=6, anio_comparar=2026, mes_comparar=5
    )

    # RIVAL_1 cambia +10.000 (absoluto mayor); RIVAL_2 cambia +3.000 pero
    # relativamente triplica — el orden es por magnitud absoluta, no % ni tamaño
    assert movimientos[0].rut == RIVAL_1


def test_radar_lake_vacio(con, tmp_path: Path):
    assert intel.radar_competencia(
        con, tmp_path / "data", anio=2026, mes=6, anio_comparar=2026, mes_comparar=5
    ) == []


# --- head_to_head -------------------------------------------------------


def test_head_to_head_cruce_simple(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "rut_proveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_genrico": "kit didactico", "valor_total_ofertado": 100000,
             "oferta_seleccionada": "No Seleccionada", "criterios_evaluacion": "plazo de entrega"},
            {"codigo_externo": "P1", "rut_proveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_genrico": "kit didactico", "valor_total_ofertado": 90000,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "plazo de entrega"},
        ],
    )

    cruces = intel.head_to_head(con, data_dir, BIOQUIMICA, RIVAL_1)

    assert len(cruces) == 1
    c = cruces[0]
    assert c.canal == "lic"
    assert c.codigo_proceso == "P1"
    assert c.nuestro_monto == 100000
    assert c.su_monto == 90000
    assert c.ganador == "rival"
    assert c.diferencia_pct == round((100000 - 90000) / 90000, 4)
    assert c.criterio == "plazo de entrega"


def test_head_to_head_solo_incluye_procesos_con_ambos(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "rut_proveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_genrico": "x", "valor_total_ofertado": 100, "oferta_seleccionada": "Seleccionada",
             "criterios_evaluacion": "precio"},
            {"codigo_externo": "P2", "rut_proveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_genrico": "y", "valor_total_ofertado": 200, "oferta_seleccionada": "Seleccionada",
             "criterios_evaluacion": "precio"},
        ],
    )

    cruces = intel.head_to_head(con, data_dir, BIOQUIMICA, RIVAL_1)

    assert cruces == []  # P1 y P2 son procesos distintos, nunca coincidieron


def test_head_to_head_ganamos_nosotros(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_cot(
        con, data_dir, 2026, 6,
        [
            {"codigo_cotizacion": "C1", "rutproveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
             "nombre_producto_generico": "x", "monto_total": 5000, "proveedor_seleccionado": "si",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
            {"codigo_cotizacion": "C1", "rutproveedor": RIVAL_1, "razon_social_proveedor": "Rival Uno",
             "nombre_producto_generico": "x", "monto_total": 5500, "proveedor_seleccionado": "no",
             "nombre_criterio": "precio", "tamano": "MiPyme"},
        ],
    )

    cruces = intel.head_to_head(con, data_dir, BIOQUIMICA, RIVAL_1, canal="cot")

    assert cruces[0].ganador == "nosotros"


def test_head_to_head_lake_vacio(con, tmp_path: Path):
    assert intel.head_to_head(con, tmp_path / "data", BIOQUIMICA, RIVAL_1) == []
