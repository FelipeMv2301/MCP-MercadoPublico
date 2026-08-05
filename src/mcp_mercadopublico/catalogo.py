"""Puente catálogo Bioquímica <-> códigos ONU/UNSPSC de Mercado Público — ÉP-03.

Un servidor MCP no llama tools de otro MCP en runtime. Claude, que tiene
AMBOS conectores (este servidor y el de catálogo BQ) en la misma
conversación, es quien cruza la información: consulta el catálogo por su
lado, consulta buscar_producto_en_historial() aquí con el mismo texto, y si
confirma que calzan, llama registrar_mapeo_sku_onu() para persistirlo.

Deliberadamente NO hay fuzzy matching automático en este módulo — decidir si
"Ácido Cítrico 1 Kg" del catálogo corresponde al código ONU que aparece en
el historial es una decisión semántica que Claude toma con el contexto de la
conversación, no una heurística de similitud de texto ciega en el servidor.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

import duckdb

from mcp_mercadopublico.lake.columnas import (
    COLUMNA_CODIGO_PRODUCTO_ONU,
    COLUMNA_PRODUCTO_GENERICO,
    COLUMNA_RUT_PROVEEDOR,
    a_snake_case,
)
from mcp_mercadopublico.rut import normalizar_rut

logger = logging.getLogger(__name__)

_DATASETS = ("oc", "lic", "cot")

# UNSPSC estándar: 8 dígitos (segmento-familia-clase-producto, 2 cada uno).
# Coincide con todos los códigos ONU vistos en el spike (41116007, 25101602,
# 42718513, ...).
_PATRON_CODIGO_ONU = re.compile(r"^\d{8}$")


# --------------------------------------------------------------------------
# HU-3.1 — consulta del lake por texto o código ONU
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CoincidenciaHistorial:
    codigo_onu: str
    texto_producto: str
    dataset: str
    n_apariciones: int
    n_vendedores_distintos: int


def buscar_producto_en_historial(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    *,
    texto: str | None = None,
    codigo_onu: str | None = None,
    solo_propio: bool = True,
    rut_propio: str | None = None,
    limite: int = 20,
) -> list[CoincidenciaHistorial]:
    """Busca en el lake qué código ONU quedó asociado a un texto de producto
    (o qué texto acompaña a un código ONU conocido).

    Con solo_propio=True (default), acota a lo que Bioquimica.cl mismo
    vendió — alta confianza, es lo que un comprador del Estado clasificó al
    comprarnos. Con solo_propio=False, busca en todo el mercado.
    """
    if not texto and not codigo_onu:
        raise ValueError("buscar_producto_en_historial requiere texto o codigo_onu")
    if solo_propio and not rut_propio:
        raise ValueError("solo_propio=True requiere rut_propio")

    rut_normalizado = normalizar_rut(rut_propio) if rut_propio else None
    resultados: list[CoincidenciaHistorial] = []

    for dataset in _DATASETS:
        directorio = data_dir / dataset
        if not directorio.exists() or not any(directorio.glob("**/*.parquet")):
            continue

        texto_col = a_snake_case(COLUMNA_PRODUCTO_GENERICO[dataset])
        onu_col = a_snake_case(COLUMNA_CODIGO_PRODUCTO_ONU[dataset])
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR[dataset])
        patron = (directorio / "**" / "*.parquet").as_posix()

        condiciones = [f'"{onu_col}" IS NOT NULL']
        params: list[str] = []
        if codigo_onu:
            condiciones.append(f'"{onu_col}" = ?')
            params.append(codigo_onu)
        if texto:
            condiciones.append(f'"{texto_col}" ILIKE ?')
            params.append(f"%{texto}%")
        if solo_propio:
            condiciones.append(f'"{rut_col}" = ?')
            params.append(rut_normalizado)

        query = f"""
            SELECT "{onu_col}" AS c, "{texto_col}" AS t,
                   COUNT(*) AS n, COUNT(DISTINCT "{rut_col}") AS nv
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE {" AND ".join(condiciones)}
            GROUP BY 1, 2
            ORDER BY n DESC
            LIMIT {int(limite)}
        """
        for c, t, n, nv in con.execute(query, params).fetchall():
            resultados.append(
                CoincidenciaHistorial(
                    codigo_onu=c, texto_producto=t, dataset=dataset,
                    n_apariciones=n, n_vendedores_distintos=nv,
                )
            )

    resultados.sort(key=lambda r: r.n_apariciones, reverse=True)
    return resultados[:limite]


def lake_tiene_datos(data_dir: Path) -> bool:
    """True si al menos un dataset tiene alguna partición Parquet — permite
    distinguir 'no hay coincidencias' de 'todavía no se ha ingerido nada'."""
    return any((data_dir / ds).exists() and any((data_dir / ds).glob("**/*.parquet")) for ds in _DATASETS)


# --------------------------------------------------------------------------
# HU-3.2 — mapeo SKU<->ONU persistido, confirmado por Claude
# --------------------------------------------------------------------------

Confianza = Literal["alta", "media", "baja"]

_ESQUEMA_MAPEOS = """
CREATE TABLE IF NOT EXISTS mapeos_sku_onu (
    sku TEXT PRIMARY KEY,
    codigo_onu TEXT NOT NULL,
    confianza TEXT NOT NULL,
    nota TEXT,
    registrado_en TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass(frozen=True)
class RegistroMapeo:
    sku: str
    codigo_onu: str
    confianza: str
    nota: str | None
    registrado_en: str


@contextmanager
def _conexion(ruta: Path) -> Iterator[sqlite3.Connection]:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(_ESQUEMA_MAPEOS)
        yield con
        con.commit()
    finally:
        con.close()


def registrar_mapeo_sku_onu(
    ruta_mapeos: Path, sku: str, codigo_onu: str, confianza: Confianza, nota: str = ""
) -> None:
    """Idempotente: reemplaza el mapeo si el SKU ya tenía uno registrado."""
    with _conexion(ruta_mapeos) as con:
        con.execute(
            """
            INSERT INTO mapeos_sku_onu (sku, codigo_onu, confianza, nota, registrado_en)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(sku) DO UPDATE SET
                codigo_onu = excluded.codigo_onu,
                confianza = excluded.confianza,
                nota = excluded.nota,
                registrado_en = excluded.registrado_en
            """,
            (sku, codigo_onu, confianza, nota or None),
        )
    logger.info(
        "mapeo_sku_onu_registrado",
        extra={"extra_fields": {"sku": sku, "codigo_onu": codigo_onu, "confianza": confianza}},
    )


def obtener_mapeo_sku_onu(ruta_mapeos: Path, sku: str) -> RegistroMapeo | None:
    with _conexion(ruta_mapeos) as con:
        fila = con.execute(
            "SELECT sku, codigo_onu, confianza, nota, registrado_en "
            "FROM mapeos_sku_onu WHERE sku = ?",
            (sku,),
        ).fetchone()
    return RegistroMapeo(*fila) if fila else None


def listar_mapeos_sku_onu(ruta_mapeos: Path) -> list[RegistroMapeo]:
    with _conexion(ruta_mapeos) as con:
        filas = con.execute(
            "SELECT sku, codigo_onu, confianza, nota, registrado_en "
            "FROM mapeos_sku_onu ORDER BY sku"
        ).fetchall()
    return [RegistroMapeo(*f) for f in filas]


# --------------------------------------------------------------------------
# resolver_producto — la función que consumen las tools de precio (ÉP-05)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolucionProducto:
    codigo_onu: str | None
    metodo: Literal["mapeo_confirmado", "codigo_literal", "sin_resolucion"]
    confianza: Literal["alta", "media", "baja", "ninguna"]


def resolver_producto(sku_o_texto: str, ruta_mapeos: Path) -> ResolucionProducto:
    """Resuelve un SKU o texto a un código ONU, con la confianza declarada.

    Orden: mapeo persistido exacto (HU-3.2) -> el propio input ya es un
    código ONU literal -> sin_resolucion. No adivina por fuzzy matching —
    ver el docstring del módulo.
    """
    entrada = sku_o_texto.strip()

    mapeo = obtener_mapeo_sku_onu(ruta_mapeos, entrada)
    if mapeo:
        return ResolucionProducto(
            codigo_onu=mapeo.codigo_onu, metodo="mapeo_confirmado", confianza=mapeo.confianza
        )

    if _PATRON_CODIGO_ONU.match(entrada):
        return ResolucionProducto(codigo_onu=entrada, metodo="codigo_literal", confianza="alta")

    return ResolucionProducto(codigo_onu=None, metodo="sin_resolucion", confianza="ninguna")
