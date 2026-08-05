"""Tests de precios.py — HU-5.1/5.2/5.3/5.4."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico import precios

ONU = "41116007"
BIOQUIMICA = "76.563.320-6"
RIVAL = "76.502.658-K"


@pytest.fixture()
def con():
    conexion = duckdb.connect()
    yield conexion
    conexion.close()


def _particion_oc(con, data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    destino = data_dir / "oc" / f"anio={anio}" / f"mes={mes}"
    destino.mkdir(parents=True, exist_ok=True)
    valores = ", ".join(
        "('{codigo_producto_onu}', '{rut_sucursal}', '{nombre_proveedor}', "
        "'{organismo_publico}', '{rubro_n2}', '{nombreroducto_generico}', "
        "{precio_neto}, {total_linea_neto}, {es_clp}, '{procedencia_oc}')".format(**f)
        for f in filas
    )
    con.sql(
        f"SELECT * FROM (VALUES {valores}) AS v("
        '"codigo_producto_onu", "rut_sucursal", "nombre_proveedor", '
        '"organismo_publico", "rubro_n2", "nombreroducto_generico", '
        '"precio_neto", "total_linea_neto", "es_clp", "procedencia_oc")'
    ).write_parquet(str(destino / "part.parquet"), compression="zstd")


_DEFAULTS_LIC = {"razon_social_proveedor": "?", "nombre_producto_genrico": "?", "rubro1": "?"}


def _particion_lic(con, data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    destino = data_dir / "lic" / f"anio={anio}" / f"mes={mes}"
    destino.mkdir(parents=True, exist_ok=True)
    filas = [{**_DEFAULTS_LIC, **f} for f in filas]
    for f in filas:
        # postmortem usa "Valor Total Ofertado" (el monto de la oferta), NO
        # "MontoUnitarioOferta" (usado por benchmark/precio_para_ganar) —
        # son columnas distintas del mismo dataset. Default: igualarlas
        # cuando el test no distingue entre ambas explícitamente.
        f.setdefault("valor_total_ofertado", f["monto_unitario_oferta"])
    valores = ", ".join(
        "('{codigo_externo}', '{codigo_producto_onu}', '{rut_proveedor}', "
        "'{razon_social_proveedor}', '{nombre_producto_genrico}', '{nombre_organismo}', "
        "{monto_unitario_oferta}, {valor_total_ofertado}, '{oferta_seleccionada}', "
        "'{criterios_evaluacion}', '{rubro1}', {es_clp})".format(**f)
        for f in filas
    )
    con.sql(
        f"SELECT * FROM (VALUES {valores}) AS v("
        '"codigo_externo", "codigo_producto_onu", "rut_proveedor", '
        '"razon_social_proveedor", "nombre_producto_genrico", "nombre_organismo", '
        '"monto_unitario_oferta", "valor_total_ofertado", "oferta_seleccionada", '
        '"criterios_evaluacion", "rubro1", "es_clp")'
    ).write_parquet(str(destino / "part.parquet"), compression="zstd")


_DEFAULTS_COT = {"razon_social_proveedor": "?", "nombre_producto_generico": "?"}


def _particion_cot(con, data_dir: Path, anio: int, mes: int, filas: list[dict]) -> None:
    destino = data_dir / "cot" / f"anio={anio}" / f"mes={mes}"
    destino.mkdir(parents=True, exist_ok=True)
    filas = [{**_DEFAULTS_COT, **f} for f in filas]
    valores = ", ".join(
        "('{codigo_cotizacion}', '{codigo_producto}', '{rutproveedor}', "
        "'{razon_social_proveedor}', '{nombre_producto_generico}', "
        "{monto_total}, {cantidad_solicitada}, '{proveedor_seleccionado}', "
        "'{nombre_criterio}', {es_clp})".format(**f)
        for f in filas
    )
    con.sql(
        f"SELECT * FROM (VALUES {valores}) AS v("
        '"codigo_cotizacion", "codigo_producto", "rutproveedor", '
        '"razon_social_proveedor", "nombre_producto_generico", '
        '"monto_total", "cantidad_solicitada", "proveedor_seleccionado", '
        '"nombre_criterio", "es_clp")'
    ).write_parquet(str(destino / "part.parquet"), compression="zstd")


# --- benchmark_precio --------------------------------------------------------


def test_benchmark_lake_vacio_muestra_insuficiente(con, tmp_path: Path):
    r = precios.benchmark_precio(con, tmp_path / "data", ONU)
    assert r.n == 0
    assert r.muestra_insuficiente is True
    assert r.minimo is None


def test_benchmark_calcula_percentiles_y_separa_ganadores(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": BIOQUIMICA,
             "nombre_organismo": "X", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "precio", "es_clp": "true"},
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": RIVAL,
             "nombre_organismo": "X", "monto_unitario_oferta": 120.0,
             "oferta_seleccionada": "No Seleccionada", "criterios_evaluacion": "precio", "es_clp": "true"},
        ],
    )

    r = precios.benchmark_precio(con, data_dir, ONU, canal="lic")

    assert r.n == 2
    assert r.n_proveedores_distintos == 2
    assert r.minimo == 100.0
    assert r.maximo == 120.0
    assert r.ganadores == {"n": 1, "minimo": 100.0, "mediana": 100.0, "maximo": 100.0}
    assert r.perdedores == {"n": 1, "minimo": 120.0, "mediana": 120.0, "maximo": 120.0}
    assert r.muestra_insuficiente is True  # n=2 < 10


def test_benchmark_cot_normaliza_a_precio_unitario(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_cot(
        con, data_dir, 2026, 6,
        [{"codigo_cotizacion": "C1", "codigo_producto": ONU, "rutproveedor": BIOQUIMICA,
          "monto_total": 500.0, "cantidad_solicitada": 5, "proveedor_seleccionado": "si",
          "nombre_criterio": "precio", "es_clp": "true"}],
    )

    r = precios.benchmark_precio(con, data_dir, ONU, canal="cot")

    assert r.minimo == 100.0  # 500/5, no 500


def test_benchmark_excluye_moneda_no_clp(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 6,
        [
            {"codigo_producto_onu": ONU, "rut_sucursal": RIVAL, "nombre_proveedor": "x",
             "organismo_publico": "x", "rubro_n2": "x", "nombreroducto_generico": "x",
             "precio_neto": 100.0, "total_linea_neto": 100.0, "es_clp": "true", "procedencia_oc": "NA"},
            {"codigo_producto_onu": ONU, "rut_sucursal": RIVAL, "nombre_proveedor": "x",
             "organismo_publico": "x", "rubro_n2": "x", "nombreroducto_generico": "x",
             "precio_neto": 999999.0, "total_linea_neto": 999999.0, "es_clp": "false", "procedencia_oc": "NA"},
        ],
    )

    r = precios.benchmark_precio(con, data_dir, ONU, canal="oc")

    assert r.n == 1
    assert r.maximo == 100.0


def test_benchmark_canal_invalido(con, tmp_path: Path):
    with pytest.raises(ValueError, match="canal"):
        precios.benchmark_precio(con, tmp_path / "data", ONU, canal="zgen")


def test_benchmark_n_alto_no_es_insuficiente(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    filas = [
        {"codigo_producto_onu": ONU, "rut_sucursal": f"RUT{i}", "nombre_proveedor": "x",
         "organismo_publico": "x", "rubro_n2": "x", "nombreroducto_generico": "x",
         "precio_neto": float(100 + i), "total_linea_neto": float(100 + i), "es_clp": "true",
         "procedencia_oc": "NA"}
        for i in range(12)
    ]
    _particion_oc(con, data_dir, 2026, 6, filas)

    r = precios.benchmark_precio(con, data_dir, ONU, canal="oc")

    assert r.n == 12
    assert r.muestra_insuficiente is False


# --- precio_para_ganar --------------------------------------------------------


def test_precio_para_ganar_rechaza_canal_oc(con, tmp_path: Path):
    with pytest.raises(ValueError, match="oc"):
        precios.precio_para_ganar(con, tmp_path / "data", ONU, canal="oc")


def test_precio_para_ganar_umbral_y_deteccion_no_mas_barato(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": BIOQUIMICA,
             "nombre_organismo": "HOSPITAL X", "monto_unitario_oferta": 110.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "plazo de entrega",
             "es_clp": "true"},
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": RIVAL,
             "nombre_organismo": "HOSPITAL X", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "No Seleccionada", "criterios_evaluacion": "plazo de entrega",
             "es_clp": "true"},
        ],
    )

    r = precios.precio_para_ganar(con, data_dir, ONU, canal="lic")

    assert r.umbral_observado == 110.0
    assert r.precio_perdedor_mas_barato == 100.0
    assert r.procesos_con_ganador == 1
    assert r.veces_gano_sin_ser_el_mas_barato == 1  # 110 > 100, ganó sin ser el más barato


def test_precio_para_ganar_filtra_por_organismo(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": BIOQUIMICA,
             "nombre_organismo": "HOSPITAL X", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "precio", "es_clp": "true"},
            {"codigo_externo": "P2", "codigo_producto_onu": ONU, "rut_proveedor": RIVAL,
             "nombre_organismo": "UNIVERSIDAD Y", "monto_unitario_oferta": 200.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "precio", "es_clp": "true"},
        ],
    )

    r = precios.precio_para_ganar(con, data_dir, ONU, canal="lic", organismo="HOSPITAL X")

    assert r.n == 1
    assert r.umbral_observado == 100.0


def test_precio_para_ganar_sin_datos(con, tmp_path: Path):
    r = precios.precio_para_ganar(con, tmp_path / "data", ONU, canal="lic")
    assert r.n == 0
    assert r.umbral_observado is None


# --- criterios_que_deciden ----------------------------------------------------


def test_criterios_clasifica_y_cuenta(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_cot(
        con, data_dir, 2026, 6,
        [
            {"codigo_cotizacion": "C1", "codigo_producto": ONU, "rutproveedor": RIVAL,
             "monto_total": 110.0, "cantidad_solicitada": 1, "proveedor_seleccionado": "si",
             "nombre_criterio": "Plazos de entrega, el proveedor ofrecio el plazo mas conveniente",
             "es_clp": "true"},
            {"codigo_cotizacion": "C1", "codigo_producto": ONU, "rutproveedor": BIOQUIMICA,
             "monto_total": 100.0, "cantidad_solicitada": 1, "proveedor_seleccionado": "no",
             "nombre_criterio": "precio", "es_clp": "true"},
        ],
    )

    r = precios.criterios_que_deciden(con, data_dir, canal="cot")

    assert r.n_procesos_ganadores == 1
    categorias = {f["categoria"] for f in r.frecuencias}
    assert "plazo_entrega" in categorias
    fila_plazo = next(f for f in r.frecuencias if f["categoria"] == "plazo_entrega")
    assert fila_plazo["n"] == 1
    # gano a 110 siendo que el minimo del proceso (BIOQUIMICA=100) era mas barato
    assert fila_plazo["prima_precio_mediana_pct"] == pytest.approx(0.1, abs=1e-6)


def test_criterios_lic_separa_por_punto_y_coma(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": BIOQUIMICA,
             "nombre_organismo": "x", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "Seleccionada",
             "criterios_evaluacion": "Plazo de Entrega ; Experiencia ; Oferta Economica",
             "es_clp": "true"},
        ],
    )

    r = precios.criterios_que_deciden(con, data_dir, canal="lic")

    categorias = {f["categoria"] for f in r.frecuencias}
    assert {"plazo_entrega", "experiencia", "precio"}.issubset(categorias)


def test_criterios_filtra_por_rubro_n1_en_lic(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": BIOQUIMICA,
             "nombre_organismo": "x", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "precio",
             "es_clp": "true", "rubro1": "EQUIPAMIENTO PARA LABORATORIOS"},
            {"codigo_externo": "P2", "codigo_producto_onu": ONU, "rut_proveedor": RIVAL,
             "nombre_organismo": "x", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "experiencia",
             "es_clp": "true", "rubro1": "VEHICULOS"},
        ],
    )

    r = precios.criterios_que_deciden(
        con, data_dir, canal="lic", rubro_n1="Equipamiento para laboratorios"
    )

    assert r.n_procesos_ganadores == 1
    assert {f["categoria"] for f in r.frecuencias} == {"precio"}


def test_criterios_canal_invalido(con, tmp_path: Path):
    with pytest.raises(ValueError, match="canal"):
        precios.criterios_que_deciden(con, tmp_path / "data", canal="oc")


def test_criterios_lake_vacio(con, tmp_path: Path):
    r = precios.criterios_que_deciden(con, tmp_path / "data")
    assert r.n_procesos_ganadores == 0
    assert r.frecuencias == []


# --- postmortem ----------------------------------------------------------


def test_postmortem_reconstruye_proceso(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": BIOQUIMICA,
             "nombre_organismo": "x", "monto_unitario_oferta": 110.0,
             "oferta_seleccionada": "No Seleccionada", "criterios_evaluacion": "plazo", "es_clp": "true"},
            {"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": RIVAL,
             "nombre_organismo": "x", "monto_unitario_oferta": 100.0,
             "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "plazo", "es_clp": "true"},
        ],
    )

    pm = precios.postmortem(con, data_dir, "P1", rut_propio=BIOQUIMICA)

    assert pm.canal == "lic"
    assert len(pm.ofertas) == 2
    assert pm.ganador_rut == RIVAL
    assert pm.nuestra_posicion["participamos"] is True
    assert pm.nuestra_posicion["seleccionado"] is False
    assert pm.nuestra_posicion["diferencia_vs_ganador_pct"] == pytest.approx(0.1, abs=1e-6)


def test_postmortem_no_participamos(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_lic(
        con, data_dir, 2026, 6,
        [{"codigo_externo": "P1", "codigo_producto_onu": ONU, "rut_proveedor": RIVAL,
          "nombre_organismo": "x", "monto_unitario_oferta": 100.0,
          "oferta_seleccionada": "Seleccionada", "criterios_evaluacion": "precio", "es_clp": "true"}],
    )

    pm = precios.postmortem(con, data_dir, "P1", rut_propio=BIOQUIMICA)

    assert pm.nuestra_posicion == {"participamos": False}


def test_postmortem_proceso_inexistente(con, tmp_path: Path):
    pm = precios.postmortem(con, tmp_path / "data", "NO-EXISTE")
    assert pm.canal is None
    assert pm.ofertas == []


# --- perfil_comprador ----------------------------------------------------


def test_perfil_comprador_mix_canal_y_estacionalidad(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    _particion_oc(
        con, data_dir, 2026, 5,
        [{"codigo_producto_onu": ONU, "rut_sucursal": BIOQUIMICA, "nombre_proveedor": "Bioquimica",
          "organismo_publico": "HOSPITAL X", "rubro_n2": "lab", "nombreroducto_generico": "reactivo",
          "precio_neto": 100.0, "total_linea_neto": 100.0, "es_clp": "true", "procedencia_oc": "NA"}],
    )
    _particion_oc(
        con, data_dir, 2026, 6,
        [{"codigo_producto_onu": ONU, "rut_sucursal": RIVAL, "nombre_proveedor": "Rival",
          "organismo_publico": "HOSPITAL X", "rubro_n2": "lab", "nombreroducto_generico": "reactivo",
          "precio_neto": 200.0, "total_linea_neto": 200.0, "es_clp": "true",
          "procedencia_oc": "Proveniente de licitación pública"}],
    )

    perfil = precios.perfil_comprador(con, data_dir, "HOSPITAL X")

    assert perfil.n_lineas == 2
    canales = {c["canal"] for c in perfil.mix_canal}
    assert "Compra ágil / trato directo" in canales
    assert "Proveniente de licitación pública" in canales
    assert len(perfil.estacionalidad) == 2
    assert perfil.top_proveedores[0]["proveedor"] in {"Bioquimica", "Rival"}


def test_perfil_comprador_sin_datos(con, tmp_path: Path):
    perfil = precios.perfil_comprador(con, tmp_path / "data", "ORGANISMO INEXISTENTE")
    assert perfil.n_lineas == 0
    assert perfil.mix_canal == []
