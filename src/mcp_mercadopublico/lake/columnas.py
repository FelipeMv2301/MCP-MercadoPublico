"""Metadatos de columnas por dataset — HU-2.3.

Las listas de columnas numéricas fueron verificadas contra los CSV reales de
2026-06 con una consulta DuckDB (regex `^-?[0-9]+,[0-9]+$` sobre cada
columna), no transcritas de memoria del spike original. Esa verificación
encontró 8 columnas numéricas en OC que la documentación original no
mencionaba (PromedioCalificacion, Descuentos, Cargos, PorcentajeIva,
cantidad, totalCargos, totalDescuentos — además de las 6 ya conocidas) y
las 7 de LIC / 2 de COT, que no estaban documentadas en absoluto.

`Financiamiento` (OC) y `FuenteFinanciamiento`/`DescripcionProveedor` (LIC)
tienen un puñado de valores que matchean el patrón por coincidencia (son
campos de texto libre) — deliberadamente NO están en estas listas.
"""

from __future__ import annotations

import re

_LIMITE_MINUSCULA_MAYUSCULA = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NO_ALFANUMERICO = re.compile(r"[^0-9a-zA-Z]+")


def a_snake_case(nombre_columna: str) -> str:
    """Convierte un nombre de columna del CSV a snake_case.

    Deliberadamente NO corrige typos del origen (MontoTotalDisponble sigue
    siendo montotal_disponble, no se "arregla" a disponible) — HU-2.3 exige
    preservarlos para que el nombre siga siendo buscable contra la
    documentación de ChileCompra. Verificado sin colisiones sobre las 222
    columnas reales de OC+LIC+COT (tests/test_columnas.py).
    """
    con_guiones = _LIMITE_MINUSCULA_MAYUSCULA.sub("_", nombre_columna)
    limpio = _NO_ALFANUMERICO.sub("_", con_guiones)
    return limpio.strip("_").lower()


def renombrar_columnas(columnas: list[str]) -> dict[str, str]:
    """Mapa columna_original -> snake_case. Falla si dos columnas distintas
    colisionan al mismo nombre — más vale un error ruidoso al ingerir un
    periodo nuevo que perder una columna en silencio (HU-8.1)."""
    mapa: dict[str, str] = {}
    vistos: dict[str, str] = {}
    for original in columnas:
        snake = a_snake_case(original)
        if snake in vistos and vistos[snake] != original:
            raise ValueError(
                f"Colisión de snake_case: {original!r} y {vistos[snake]!r} "
                f"ambas mapean a {snake!r}. Requiere renombre manual explícito."
            )
        vistos[snake] = original
        mapa[original] = snake
    return mapa


# --------------------------------------------------------------------------
# Metadatos por dataset — nombres ORIGINALES (antes de renombrar a snake_case)
# --------------------------------------------------------------------------

COLUMNAS_NUMERICAS_OC: frozenset[str] = frozenset(
    {
        "PromedioCalificacion",
        "MontoTotalOC",
        "MontoTotalOC_PesosChilenos",
        "Impuestos",
        "Descuentos",
        "Cargos",
        "TotalNetoOC",
        "PorcentajeIva",
        "cantidad",
        "precioNeto",
        "totalCargos",
        "totalDescuentos",
        "totalLineaNeto",
    }
)

COLUMNAS_NUMERICAS_LIC: frozenset[str] = frozenset(
    {
        "MontoEstimado",
        "Cantidad",
        "Cantidad Ofertada",
        "MontoUnitarioOferta",
        "Valor Total Ofertado",
        "CantidadAdjudicada",
        "MontoLineaAdjudica",
    }
)

COLUMNAS_NUMERICAS_COT: frozenset[str] = frozenset(
    {
        "MontoTotalDisponble",
        "MontoTotal",
    }
)

# Columna de moneda relevante para las columnas numéricas de precio de cada
# dataset (P15: precioNeto/MontoUnitarioOferta/MontoTotal no siempre son CLP).
COLUMNA_MONEDA = {
    "oc": "monedaItem",
    "lic": "Moneda de la Oferta",
    "cot": "moneda",
}

# Valor de esa columna que significa "es pesos chilenos" — NO es el mismo
# literal en los tres datasets (bug real encontrado en producción,
# 2026-08-11): OC/COT usan el código ISO ('CLP'), pero LIC trae el nombre en
# español ('Peso Chileno' en el 99,8% de las filas verificadas contra el
# lake real) y NUNCA el string 'CLP' — comparar contra 'CLP' fijo dejaba
# es_clp en false para el 99,996% de las filas de licitación, silenciando
# benchmark_precio/precio_para_ganar/criterios_que_deciden para ese canal
# sin ningún error visible.
VALOR_MONEDA_CLP = {
    "oc": "CLP",
    "lic": "Peso Chileno",
    "cot": "CLP",
}

# Valores conocidos y legítimos de la columna de moneda de cada dataset —
# verificado contra el lake real desplegado (2026-08-11). Se usa SÓLO para
# detectar corrupción del camino tolerante de _leer_csv (ver etl.py): una
# línea malformada con columnas desplazadas puede "sobrevivir" con texto
# arbitrario en esta columna (nombres de archivo, RUT, fechas — visto en
# lic-da/2026-3) sin que el conteo de filas lo detecte. NO es un filtro de
# negocio ni se usa para calcular es_clp (eso es VALOR_MONEDA_CLP).
VALORES_MONEDA_VALIDOS = {
    "oc": frozenset({"CLP", "USD", "CLF", "UTM", "EUR"}),
    "lic": frozenset({"Peso Chileno", "Dolar", "Unidad de Fomento", "Moneda revisar", "Aceptada"}),
    "cot": frozenset({"CLP", "USD", "CLF", "UTM", "EUR"}),
}

# COT no tiene columna de rubro — ver lake/etl.py para cómo se filtra
# (whitelist de codigoProductoONU derivada de OC+LIC).
COLUMNA_RUBRO_N1 = {
    "oc": "RubroN1",
    "lic": "Rubro1",
    "cot": None,
}

COLUMNA_CODIGO_PRODUCTO_ONU = {
    "oc": "codigoProductoONU",
    "lic": "CodigoProductoONU",
    "cot": "CodigoProducto",
}

# Nombre genérico del producto en texto libre — usado por ÉP-03 para que
# Claude pueda buscar por texto en vez de por código exacto.
COLUMNA_PRODUCTO_GENERICO = {
    "oc": "NombreroductoGenerico",  # typo del origen, ver docs/esquema-datos-abiertos.md
    "lic": "Nombre producto genrico",  # típo del origen, con espacios
    "cot": "NombreProductoGenerico",
}

# RUT de quien vendió esa línea — distinto por dataset: OC identifica al
# vendedor por la sucursal (RutSucursal), LIC/COT por el proveedor directo.
COLUMNA_RUT_PROVEEDOR = {
    "oc": "RutSucursal",
    "lic": "RutProveedor",
    "cot": "RUTProveedor",
}

# --------------------------------------------------------------------------
# Metadatos adicionales para ÉP-04 (inteligencia competitiva)
# --------------------------------------------------------------------------

# Razón social del proveedor de esa línea.
COLUMNA_NOMBRE_PROVEEDOR = {
    "oc": "NombreProveedor",
    "lic": "RazonSocialProveedor",
    "cot": "RazonSocialProveedor",
}

# Organismo comprador.
COLUMNA_ORGANISMO = {
    "oc": "OrganismoPublico",
    "lic": "NombreOrganismo",
    "cot": "NombreOOPP",
}

COLUMNA_RUBRO_N2 = {
    "oc": "RubroN2",
    "lic": "Rubro2",
    "cot": None,  # COT no tiene columna de rubro en absoluto (ver COLUMNA_RUBRO_N1)
}

# Identificador del PROCESO (licitación/cotización) — la clave de
# co-participación: mismo código = mismo proceso, distintos RutProveedor =
# rivales en ese proceso. OC no tiene una columna equivalente útil aquí: una
# OC es la orden YA ganada (un solo proveedor por fila), no expone a quién
# más compitió — por eso descubrir_rivales/head_to_head operan sobre LIC y
# COT, nunca sobre OC.
COLUMNA_CODIGO_PROCESO = {
    "lic": "CodigoExterno",
    "cot": "CodigoCotizacion",
}

# Si esa oferta/cotización específica fue la ganadora. Valores de texto
# distintos por dataset (verificado): LIC usa "Seleccionada"/"No Seleccionada",
# COT usa "si"/"no".
COLUMNA_SELECCIONADO = {
    "lic": "Oferta seleccionada",
    "cot": "ProveedorSeleccionado",
}

# Monto de esa oferta/cotización específica (no confundir con el monto de la
# OC ya adjudicada, que vive en el dataset 'oc').
COLUMNA_MONTO_OFERTA = {
    "lic": "Valor Total Ofertado",
    "cot": "MontoTotal",
}

# Motivo/criterio de adjudicación declarado.
COLUMNA_CRITERIO = {
    "lic": "CriteriosEvaluacion",
    "cot": "NombreCriterio",
}

# Tamaño de empresa (MiPyme, etc.) — sólo existe en COT, verificado contra
# los headers reales de OC/LIC (no está presente en ninguno de los dos).
COLUMNA_TAMANO = {
    "cot": "Tamano",
}

# Valor de texto que marca "esta oferta/cotización ganó" — verificado contra
# datos reales (lic-da/2026-6: 'Seleccionada'/'No Seleccionada'; COT:
# 'si'/'no'). Comparar en minúsculas (LOWER(TRIM(...))).
VALOR_GANADOR = {"lic": "seleccionada", "cot": "si"}

# Cantidad de unidades de esa línea — para normalizar COT a precio unitario
# (MontoTotal es el total de la línea, no el precio por unidad).
COLUMNA_CANTIDAD = {
    "oc": "cantidad",
    "lic": "Cantidad Ofertada",
    "cot": "CantidadSolicitada",
}

# Precio unitario YA calculado en el dataset (no requiere dividir por
# cantidad) — sólo existe en OC y LIC; COT se deriva vía COLUMNA_CANTIDAD.
COLUMNA_PRECIO_UNITARIO = {
    "oc": "precioNeto",
    "lic": "MontoUnitarioOferta",
}

# RUT de la unidad de compra (el organismo específico que compró/licitó).
COLUMNA_RUT_UNIDAD_COMPRA = {
    "oc": "RutUnidadCompra",
    "lic": "RutUnidad",
    "cot": "RUTUnidaddeCompra",
}

# Canal de origen de la OC — sólo existe en 'oc'. Valores reales observados:
# "NA" (compra ágil / trato directo, 76,4% del negocio medido para
# Bioquimica.cl), "Proveniente de licitación pública",
# "Proveniente de licitación privada".
COLUMNA_PROCEDENCIA = {
    "oc": "ProcedenciaOC",
}

# Valores que representan NULL, sin importar la columna (P4, P5, P6).
VALORES_NULOS = frozenset({"NA", "", "1900-01-01"})

COLUMNAS_NUMERICAS = {
    "oc": COLUMNAS_NUMERICAS_OC,
    "lic": COLUMNAS_NUMERICAS_LIC,
    "cot": COLUMNAS_NUMERICAS_COT,
}
