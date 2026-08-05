"""Tests de caracterización de las 15 trampas de parsing (HU-1.4).

Estos tests NO ejercitan código de ETL — ese se construye en ÉP-02
(mcp_mercadopublico.lake.etl, aún no escrito). Fijan, contra los bytes reales
descargados el 2026-08-05 (ver tests/fixtures/README.md), el comportamiento
documentado en docs/esquema-datos-abiertos.md §3.

Sirven de especificación ejecutable para HU-2.3: si uno de estos tests
empieza a fallar, es porque ChileCompra cambió el formato del archivo — no
porque haya un bug en un parser propio, que todavía no existe.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _filas(nombre: str, encoding: str = "latin-1") -> list[list[str]]:
    """Decodifica un fixture con el parser real y devuelve sus filas.

    Las fixtures están truncadas a media fila a propósito (README de
    fixtures) — se descarta la última, que casi siempre queda incompleta.
    """
    datos = (FIXTURES / nombre).read_bytes().decode(encoding)
    filas = list(csv.reader(io.StringIO(datos), delimiter=";", quotechar='"'))
    return filas[:-1] if filas else filas


def _primera_fila(nombre: str) -> dict[str, str]:
    filas = _filas(nombre)
    return dict(zip(filas[0], filas[1]))


# --- P1: encoding latin-1/cp1252, sin BOM ----------------------------------


def test_p1_oc_no_es_utf8():
    crudo = (FIXTURES / "oc_head.bin").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        crudo.decode("utf-8")


def test_p1_cot_no_es_utf8():
    crudo = (FIXTURES / "cot1_head.bin").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        crudo.decode("utf-8")


def test_p1_latin1_decodifica_sin_error():
    for nombre in ("oc_head.bin", "lic_head.bin", "cot1_head.bin"):
        (FIXTURES / nombre).read_bytes().decode("latin-1")  # no debe lanzar


def test_p1_sin_bom():
    for nombre in ("oc_head.bin", "lic_head.bin", "cot1_head.bin"):
        crudo = (FIXTURES / nombre).read_bytes()
        assert not crudo.startswith(b"\xef\xbb\xbf")


# --- P2: decimal con coma ----------------------------------------------------


def test_p2_monto_oc_decimal_coma():
    fila = _primera_fila("oc_head.bin")
    assert fila["MontoTotalOC"] == "19977,72"
    assert float(fila["MontoTotalOC"].replace(",", ".")) == pytest.approx(19977.72)


def test_p2_precio_neto_decimal_coma():
    fila = _primera_fila("oc_head.bin")
    assert fila["precioNeto"] == "279,8"


# --- P3: newlines embebidos en campo entrecomillado -------------------------


def test_p3_detalle_cotizacion_trae_newline_embebido():
    fila = _primera_fila("cot1_head.bin")
    assert "\n" in fila["DetalleCotizacion"]
    assert "Garantía 12 meses" in fila["DetalleCotizacion"]


def test_p3_contar_lineas_fisicas_subestima_filas():
    """Prohibido estimar el número de filas contando '\\n' — hay más saltos
    de línea físicos que filas lógicas por los campos multilínea."""
    crudo = (FIXTURES / "cot1_head.bin").read_bytes().decode("latin-1")
    lineas_fisicas = crudo.count("\n")
    filas_logicas = len(_filas("cot1_head.bin"))
    assert lineas_fisicas != filas_logicas


# --- P4: "NA" como nulo literal ----------------------------------------------


def test_p4_na_literal_en_campos_de_oc():
    fila = _primera_fila("oc_head.bin")
    assert fila["FechaCancelacion"] == "NA"
    assert fila["PaisProveedor"] == "NA"
    assert fila["Codigo_ConvenioMarco"] == "NA"


# --- P5 / P6: sentinela 1900-01-01, incluso en campos de texto -------------


def test_p5_fecha_sentinela_en_lic():
    fila = _primera_fila("lic_head.bin")
    assert fila["FechaSoporteFisico"] == "1900-01-01"
    assert fila["FechaEstimadaFirma"] == "1900-01-01"


def test_p6_sentinela_contamina_campos_de_direccion():
    """Bug del dataset: DireccionVisita/DireccionEntrega, que deberían traer
    texto libre, quedan con la fecha sentinela en vez de NULL o vacío."""
    fila = _primera_fila("lic_head.bin")
    assert fila["DireccionVisita"] == "1900-01-01"
    assert fila["DireccionEntrega"] == "1900-01-01"


# --- P7: typos de columna del origen (no corregir) --------------------------


def test_p7_typos_presentes_en_headers():
    header_cot = _filas("cot1_head.bin")[0]
    header_oc = _filas("oc_head.bin")[0]
    header_lic = _filas("lic_head.bin")[0]
    assert "MontoTotalDisponble" in header_cot  # falta la 'i' de "Disponible"
    assert "NombreroductoGenerico" in header_oc  # falta la 'P' de "Producto"
    assert "Descripcion/Obervaciones" in header_oc  # falta la 's' de "Observaciones"
    assert "Nombre producto genrico" in header_lic  # falta la 'é' de "genérico"


# --- P8/P9: nombres con espacios, '/' y casing mixto ------------------------


def test_p8_columnas_con_espacios_y_barra():
    header_oc = _filas("oc_head.bin")[0]
    header_lic = _filas("lic_head.bin")[0]
    assert "Forma de Pago" in header_oc
    assert "Descripcion/Obervaciones" in header_oc
    assert "Tipo de Adquisicion" in header_lic
    assert "Valor Total Ofertado" in header_lic


def test_p9_casing_inconsistente_entre_columnas():
    header_oc = _filas("oc_head.bin")[0]
    # codigoEstado (camelCase) y Estado (Pascal) y NombreProveedor conviven
    assert "codigoEstado" in header_oc
    assert "Estado" in header_oc
    assert "monedaItem" in header_oc


# --- P10: columna duplicada con sufijo .1 -----------------------------------


def test_p10_columna_duplicada_con_sufijo():
    header_lic = _filas("lic_head.bin")[0]
    assert "DescripcionCriteriosRequisitosSociales" in header_lic
    assert "DescripcionCriteriosRequisitosSociales.1" in header_lic
    # son dos posiciones distintas, no un error de lectura
    assert header_lic.count("DescripcionCriteriosRequisitosSociales") == 1
    assert header_lic.count("DescripcionCriteriosRequisitosSociales.1") == 1


# --- P11: dos columnas casi homónimas, NO deduplicar -------------------------


def test_p11_forma_pago_codigo_y_texto_son_columnas_distintas():
    header_oc = _filas("oc_head.bin")[0]
    assert "FormaPago" in header_oc
    assert "Forma de Pago" in header_oc
    fila = _primera_fila("oc_head.bin")
    assert fila["FormaPago"] == "2"
    assert fila["Forma de Pago"] == "30 dias contra la recepcion conforme de la factura"


# --- P12: ';' dentro de un campo entrecomillado -----------------------------


def test_p12_criterios_evaluacion_trae_punto_y_coma_interno():
    fila = _primera_fila("lic_head.bin")
    criterios = fila["CriteriosEvaluacion"]
    assert ";" in criterios
    assert "Plazo de Entrega" in criterios
    assert "POLITICA DE CANJE" in criterios


def test_p12_delimiter_correcto_no_parte_el_campo():
    """Si el parser separase por ';' a nivel de línea en vez de respetar el
    quoting, CriteriosEvaluacion terminaría partido en varias columnas."""
    filas = _filas("lic_head.bin")
    header = filas[0]
    assert len(filas[1]) == len(header)


# --- P13: región como texto libre con espacios finales ----------------------


def test_p13_region_como_texto_con_espacios():
    fila = _primera_fila("cot1_head.bin")
    assert fila["Region"].startswith("Regi")
    assert fila["Region"] != fila["Region"].strip()  # trae espacios finales
    assert fila["Region"].strip() == fila["Region"].rstrip()


# --- P14: RUT con puntos y DV 'K' -------------------------------------------


def test_p14_rut_con_puntos_y_dv_k():
    fila = _primera_fila("cot1_head.bin")
    assert fila["RUTProveedor"] == "78.167.575-K"


# --- P15: moneda distinta de CLP contamina precioNeto -----------------------


def test_p15_moneda_no_clp_en_primera_fila_oc():
    fila = _primera_fila("oc_head.bin")
    assert fila["monedaItem"] == "CLF"
    assert fila["TipoMonedaOC"] == "CLF"
    # 279,8 UF, NO $279,8 — cualquier AVG(precioNeto) sin filtrar moneda
    # mezcla magnitudes de forma silenciosa.
    assert fila["precioNeto"] == "279,8"


# --- Deriva de esquema (fundamento de HU-8.1) -------------------------------


def test_esquema_oc_cambio_entre_2019_y_2026():
    header_2019 = set(_filas("oc2019.bin")[0])
    header_2026 = set(_filas("oc_head.bin")[0])
    assert "idPlanDeCompra" in header_2019
    assert "idPlanDeCompra" not in header_2026
    assert "Codigo_ConvenioMarco" in header_2026
    assert "Codigo_ConvenioMarco" not in header_2019


def test_esquema_oc_2010_igual_a_2019():
    assert set(_filas("oc2010.bin")[0]) == set(_filas("oc2019.bin")[0])


def test_esquema_lic_gano_columnas_de_sostenibilidad():
    header_2019 = set(_filas("lic2019.bin")[0])
    header_2026 = set(_filas("lic_head.bin")[0])
    nuevas = header_2026 - header_2019
    assert "CriteriosRequisitosAmbientales" in nuevas
    assert "CriteriosRequisitosSociales" in nuevas
    assert "CriteriosEvaluacion" in nuevas
    assert "ValorTiempoRenovacion" in (header_2019 - header_2026)


def test_esquema_lic_columnas_comunes_mantienen_orden_relativo():
    """El orden RELATIVO de las columnas presentes en ambos periodos no
    cambió. El riesgo real no es un reordenamiento general, sino que las 6
    columnas agregadas se insertan en medio del header y desplazan el
    ÍNDICE ABSOLUTO de todo lo que viene después (ver el test siguiente)."""
    header_2019 = _filas("lic2019.bin")[0]
    header_2026 = _filas("lic_head.bin")[0]
    comunes_2019 = [c for c in header_2019 if c in header_2026]
    comunes_2026 = [c for c in header_2026 if c in header_2019]
    assert comunes_2019 == comunes_2026


def test_esquema_lic_indice_absoluto_se_desplaza_por_insercion():
    """Aunque el orden relativo se preserve, mapear por posición sigue
    siendo peligroso: las 6 columnas de sostenibilidad insertadas cerca del
    inicio del header desplazan el índice absoluto de TODO lo posterior.
    'NumeroOferentes' pasa de la posición 75 a la 80 sin que su significado
    haya cambiado — leerla por índice en vez de por nombre la confundiría
    con la columna vecina."""
    header_2019 = _filas("lic2019.bin")[0]
    header_2026 = _filas("lic_head.bin")[0]
    assert header_2019.index("Tipo de Adquisicion") == 5
    assert header_2026.index("Tipo de Adquisicion") == 11
    assert header_2019.index("NumeroOferentes") == 75
    assert header_2026.index("NumeroOferentes") == 80


def test_esquema_oc_columna_renombrada_cambia_radicalmente_de_posicion():
    """idPlanDeCompra (2019) y su reemplazo Codigo_ConvenioMarco (2026) no
    ocupan la misma posición ni una cercana: leer OC por índice en vez de
    por nombre haría que la posición 12 se interprete con el significado
    equivocado entre un periodo y otro."""
    header_2019 = _filas("oc2019.bin")[0]
    header_2026 = _filas("oc_head.bin")[0]
    assert header_2019.index("idPlanDeCompra") == 12
    assert header_2026.index("Codigo_ConvenioMarco") == 58


def test_esquema_lic_cantidad_de_columnas():
    assert len(_filas("lic2019.bin")[0]) == 105
    assert len(_filas("lic2015.bin")[0]) == 105
    assert len(_filas("lic_head.bin")[0]) == 110
