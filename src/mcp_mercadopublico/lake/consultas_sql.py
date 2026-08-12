"""Consulta SQL de sólo lectura sobre el data lake — para análisis ad hoc
que las tools fijas de inteligencia.py no cubren.

Dos capas de control, ninguna es un sandbox contra un atacante externo (para
eso está MCP_AUTH_TOKEN, ver auth.py) — son protección contra que una query
mal pensada del modelo escriba, borre o cambie configuración de la sesión en
vez de sólo leer:

1. Vistas fijas (oc/lic/cot), nunca una ruta de archivo: el modelo escribe
   `SELECT ... FROM lic WHERE ...`, no un read_parquet() con su propia ruta
   — así no hay forma de leer nada fuera del lake.
2. Sólo SELECT/WITH: se bloquean DDL/DML y comandos de sistema (ATTACH,
   COPY, INSTALL, LOAD, PRAGMA, SET, etc.) con un filtro de dos capas
   (allowlist del inicio + blocklist de palabras clave) — no es un parser
   SQL completo, es barato y alcanza para el caso real (una query escrita
   por el modelo, no alguien tratando de saltárselo a propósito).

Paginación con el mismo patrón que head_to_head: se pide limite+1 filas y se
recorta la última para saber `hay_mas`, sin pagar un COUNT(*) aparte sobre
una query arbitraria (podría costar tanto como la query misma).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

DATASETS = ("oc", "lic", "cot")

_PALABRAS_PROHIBIDAS = (
    "ATTACH", "DETACH", "COPY", "INSTALL", "LOAD", "PRAGMA", "SET", "RESET",
    "EXPORT", "IMPORT", "CALL", "CREATE", "DROP", "ALTER", "INSERT",
    "UPDATE", "DELETE", "VACUUM", "CHECKPOINT", "GRANT", "REVOKE",
)
_PATRON_PALABRA_PROHIBIDA = re.compile(
    r"\b(" + "|".join(_PALABRAS_PROHIBIDAS) + r")\b", re.IGNORECASE
)


class ConsultaSqlInvalida(ValueError):
    """La query no pasó la validación de sólo-lectura — no es un bug, es la
    tool rechazando algo que no es un SELECT/WITH simple."""


def _validar_solo_lectura(sql: str) -> str:
    limpio = sql.strip()
    if not limpio:
        raise ConsultaSqlInvalida("sql está vacío.")

    sin_punto_y_coma_final = limpio[:-1] if limpio.endswith(";") else limpio
    if ";" in sin_punto_y_coma_final:
        raise ConsultaSqlInvalida(
            "sql debe ser un único statement — no se permite ';' salvo al final."
        )

    inicio = sin_punto_y_coma_final.lstrip().upper()
    if not (inicio.startswith("SELECT") or inicio.startswith("WITH")):
        raise ConsultaSqlInvalida("sql debe empezar con SELECT o WITH — sólo lectura.")

    coincidencia = _PATRON_PALABRA_PROHIBIDA.search(sin_punto_y_coma_final)
    if coincidencia:
        raise ConsultaSqlInvalida(
            f"sql contiene '{coincidencia.group(0)}' — no permitido, sólo SELECT "
            "de lectura sobre las vistas oc/lic/cot."
        )

    return sin_punto_y_coma_final


def _registrar_vistas(con: duckdb.DuckDBPyConnection, data_dir: Path) -> list[str]:
    """Una vista por dataset con datos ya ingeridos — sólo esas quedan
    disponibles como FROM en la query del modelo. Los nombres de dataset
    vienen de la constante fija DATASETS, no de sql — no hay riesgo de
    inyección al interpolar el patrón de archivos."""
    disponibles = []
    for dataset in DATASETS:
        directorio = data_dir / dataset
        if not directorio.exists() or not any(directorio.glob("**/*.parquet")):
            continue
        patron = (directorio / "**" / "*.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE VIEW \"{dataset}\" AS SELECT * FROM read_parquet('{patron}', union_by_name=true)")
        disponibles.append(dataset)
    return disponibles


def _valor_serializable(valor: object) -> object:
    """DuckDB puede devolver Decimal/date/datetime — ninguno serializa a
    JSON directo; el resto de las tools ya castea explícito por lo mismo
    (ver inteligencia.py) — acá se generaliza porque las columnas son
    arbitrarias, no se conocen de antemano."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def ejecutar_consulta(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    sql: str,
    offset: int,
    limite: int,
) -> tuple[list[dict], bool, list[str]]:
    """Valida `sql`, registra las vistas del lake disponibles y la corre
    paginada. Devuelve (filas, hay_mas, datasets_disponibles)."""
    sql_validado = _validar_solo_lectura(sql)
    disponibles = _registrar_vistas(con, data_dir)

    sql_paginado = f"SELECT * FROM ({sql_validado}) AS _consulta LIMIT {limite + 1} OFFSET {offset}"
    resultado = con.execute(sql_paginado)
    columnas = [c[0] for c in resultado.description]
    crudo = resultado.fetchall()

    hay_mas = len(crudo) > limite
    filas = [
        {col: _valor_serializable(valor) for col, valor in zip(columnas, fila)}
        for fila in crudo[:limite]
    ]
    return filas, hay_mas, disponibles
