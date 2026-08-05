"""Tests de columnas.py — HU-2.3.

Las listas COLUMNAS_NUMERICAS_* fueron derivadas corriendo una consulta
DuckDB sobre los CSV completos reales (no las fixtures truncadas de 40 KB) —
ver el registro de la sesión. Aquí sólo se verifica que a_snake_case() no
colisiona sobre los headers reales y que las columnas declaradas como
numéricas efectivamente existen en el header de su dataset.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from mcp_mercadopublico.lake.columnas import (
    COLUMNA_CODIGO_PRODUCTO_ONU,
    COLUMNA_CODIGO_PROCESO,
    COLUMNA_CRITERIO,
    COLUMNA_MONEDA,
    COLUMNA_MONTO_OFERTA,
    COLUMNA_NOMBRE_PROVEEDOR,
    COLUMNA_ORGANISMO,
    COLUMNA_PRODUCTO_GENERICO,
    COLUMNA_RUBRO_N1,
    COLUMNA_RUBRO_N2,
    COLUMNA_RUT_PROVEEDOR,
    COLUMNA_SELECCIONADO,
    COLUMNA_TAMANO,
    COLUMNAS_NUMERICAS_COT,
    COLUMNAS_NUMERICAS_LIC,
    COLUMNAS_NUMERICAS_OC,
    a_snake_case,
    renombrar_columnas,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _header(nombre: str) -> list[str]:
    datos = (FIXTURES / nombre).read_bytes().decode("latin-1")
    return next(csv.reader(io.StringIO(datos), delimiter=";", quotechar='"'))


@pytest.mark.parametrize(
    "original,esperado",
    [
        ("ID", "id"),
        ("FormaPago", "forma_pago"),
        ("Forma de Pago", "forma_de_pago"),
        ("MontoTotalDisponble", "monto_total_disponble"),
        ("Descripcion/Obervaciones", "descripcion_obervaciones"),
        ("codigoEstado", "codigo_estado"),
    ],
)
def test_a_snake_case_casos_conocidos(original: str, esperado: str):
    assert a_snake_case(original) == esperado


def test_forma_pago_y_forma_de_pago_no_colisionan():
    """P11: son columnas distintas en el origen — deben seguir siéndolo."""
    mapa = renombrar_columnas(["FormaPago", "Forma de Pago"])
    assert mapa["FormaPago"] != mapa["Forma de Pago"]


def test_sufijo_punto_uno_no_colisiona():
    """P10: DescripcionCriteriosRequisitosSociales.1 es una columna aparte."""
    mapa = renombrar_columnas(
        ["DescripcionCriteriosRequisitosSociales", "DescripcionCriteriosRequisitosSociales.1"]
    )
    valores = set(mapa.values())
    assert len(valores) == 2


def test_renombrar_columnas_detecta_colision_real():
    with pytest.raises(ValueError, match="Colisión"):
        renombrar_columnas(["Codigo", "codigo"])  # ambas -> 'codigo'


@pytest.mark.parametrize(
    "fixture,header_esperado_no_vacio",
    [("oc_head.bin", 78), ("lic_head.bin", 110), ("cot1_head.bin", 34)],
)
def test_headers_reales_sin_colision(fixture: str, header_esperado_no_vacio: int):
    header = _header(fixture)
    assert len(header) == header_esperado_no_vacio
    mapa = renombrar_columnas(header)  # no debe lanzar
    assert len(set(mapa.values())) == len(header)


def test_columnas_numericas_oc_existen_en_header_real():
    header = set(_header("oc_head.bin"))
    faltantes = COLUMNAS_NUMERICAS_OC - header
    assert not faltantes, f"columnas numéricas OC ausentes del header real: {faltantes}"


def test_columnas_numericas_lic_existen_en_header_real():
    header = set(_header("lic_head.bin"))
    faltantes = COLUMNAS_NUMERICAS_LIC - header
    assert not faltantes, f"columnas numéricas LIC ausentes del header real: {faltantes}"


def test_columnas_numericas_cot_existen_en_header_real():
    header = set(_header("cot1_head.bin"))
    faltantes = COLUMNAS_NUMERICAS_COT - header
    assert not faltantes, f"columnas numéricas COT ausentes del header real: {faltantes}"


def test_financiamiento_no_esta_en_columnas_numericas_oc():
    """Financiamiento es texto libre (ej. '22.08.999.019.002 (Ppto. Munic)');
    unos pocos valores matchean el patrón coma-decimal por coincidencia."""
    assert "Financiamiento" not in COLUMNAS_NUMERICAS_OC


def test_columna_moneda_existe_en_cada_header():
    assert COLUMNA_MONEDA["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_MONEDA["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_MONEDA["cot"] in set(_header("cot1_head.bin"))


def test_columna_rubro_n1_existe_donde_corresponde():
    assert COLUMNA_RUBRO_N1["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_RUBRO_N1["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_RUBRO_N1["cot"] is None  # COT no tiene columna de rubro


def test_columna_codigo_producto_onu_existe_en_cada_header():
    assert COLUMNA_CODIGO_PRODUCTO_ONU["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_CODIGO_PRODUCTO_ONU["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_CODIGO_PRODUCTO_ONU["cot"] in set(_header("cot1_head.bin"))


def test_columna_producto_generico_existe_en_cada_header():
    assert COLUMNA_PRODUCTO_GENERICO["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_PRODUCTO_GENERICO["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_PRODUCTO_GENERICO["cot"] in set(_header("cot1_head.bin"))


def test_columna_rut_proveedor_existe_en_cada_header():
    assert COLUMNA_RUT_PROVEEDOR["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_RUT_PROVEEDOR["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_RUT_PROVEEDOR["cot"] in set(_header("cot1_head.bin"))


# --- Metadatos de ÉP-04 -----------------------------------------------------


def test_columna_nombre_proveedor_existe_en_cada_header():
    assert COLUMNA_NOMBRE_PROVEEDOR["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_NOMBRE_PROVEEDOR["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_NOMBRE_PROVEEDOR["cot"] in set(_header("cot1_head.bin"))


def test_columna_organismo_existe_en_cada_header():
    assert COLUMNA_ORGANISMO["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_ORGANISMO["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_ORGANISMO["cot"] in set(_header("cot1_head.bin"))


def test_columna_rubro_n2_existe_donde_corresponde():
    assert COLUMNA_RUBRO_N2["oc"] in set(_header("oc_head.bin"))
    assert COLUMNA_RUBRO_N2["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_RUBRO_N2["cot"] is None


def test_columna_codigo_proceso_existe_solo_en_lic_y_cot():
    assert COLUMNA_CODIGO_PROCESO["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_CODIGO_PROCESO["cot"] in set(_header("cot1_head.bin"))
    assert "oc" not in COLUMNA_CODIGO_PROCESO  # OC no expone a los rivales


def test_columna_seleccionado_existe_en_lic_y_cot():
    assert COLUMNA_SELECCIONADO["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_SELECCIONADO["cot"] in set(_header("cot1_head.bin"))


def test_columna_monto_oferta_existe_en_lic_y_cot():
    assert COLUMNA_MONTO_OFERTA["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_MONTO_OFERTA["cot"] in set(_header("cot1_head.bin"))


def test_columna_criterio_existe_en_lic_y_cot():
    assert COLUMNA_CRITERIO["lic"] in set(_header("lic_head.bin"))
    assert COLUMNA_CRITERIO["cot"] in set(_header("cot1_head.bin"))


def test_columna_tamano_solo_existe_en_cot():
    assert COLUMNA_TAMANO["cot"] in set(_header("cot1_head.bin"))
    assert "oc" not in COLUMNA_TAMANO
    assert "lic" not in COLUMNA_TAMANO
    assert COLUMNA_TAMANO["cot"] not in set(_header("oc_head.bin"))
    assert COLUMNA_TAMANO["cot"] not in set(_header("lic_head.bin"))
