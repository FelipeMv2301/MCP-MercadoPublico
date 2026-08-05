"""Manifest de ingesta — HU-2.5.

Registra qué periodo de qué dataset está en el lake, con qué ETag, para que
la reingesta sea condicional (HU-2.1) e idempotente (reemplaza la fila del
periodo, no duplica). WAL mode porque el servidor MCP y la tarea de ingesta
comparten el mismo proceso en Railway y pueden escribir cerca en el tiempo
(ver Backlog/backlog-mcp-mercadopublico.md HU-7.3).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS periodos_ingeridos (
    dataset TEXT NOT NULL,
    periodo TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    filas_leidas INTEGER NOT NULL DEFAULT 0,
    filas_escritas INTEGER NOT NULL DEFAULT 0,
    filas_descartadas INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL,
    ingerido_en TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (dataset, periodo)
);
"""


@dataclass(frozen=True)
class RegistroPeriodo:
    dataset: str
    periodo: str
    etag: str | None
    last_modified: str | None
    filas_leidas: int
    filas_escritas: int
    filas_descartadas: int
    estado: str
    ingerido_en: str


@contextmanager
def _conexion(ruta: Path) -> Iterator[sqlite3.Connection]:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(_ESQUEMA)
        yield con
        con.commit()
    finally:
        con.close()


def obtener_periodo(ruta_manifest: Path, dataset: str, periodo: str) -> RegistroPeriodo | None:
    with _conexion(ruta_manifest) as con:
        fila = con.execute(
            "SELECT dataset, periodo, etag, last_modified, filas_leidas, "
            "filas_escritas, filas_descartadas, estado, ingerido_en "
            "FROM periodos_ingeridos WHERE dataset = ? AND periodo = ?",
            (dataset, periodo),
        ).fetchone()
    return RegistroPeriodo(*fila) if fila else None


def registrar_periodo(
    ruta_manifest: Path,
    *,
    dataset: str,
    periodo: str,
    etag: str | None,
    last_modified: str | None,
    filas_leidas: int,
    filas_escritas: int,
    filas_descartadas: int,
    estado: str,
) -> None:
    """Idempotente: reemplaza el registro del periodo si ya existía."""
    with _conexion(ruta_manifest) as con:
        con.execute(
            """
            INSERT INTO periodos_ingeridos
                (dataset, periodo, etag, last_modified, filas_leidas,
                 filas_escritas, filas_descartadas, estado, ingerido_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(dataset, periodo) DO UPDATE SET
                etag = excluded.etag,
                last_modified = excluded.last_modified,
                filas_leidas = excluded.filas_leidas,
                filas_escritas = excluded.filas_escritas,
                filas_descartadas = excluded.filas_descartadas,
                estado = excluded.estado,
                ingerido_en = excluded.ingerido_en
            """,
            (
                dataset,
                periodo,
                etag,
                last_modified,
                filas_leidas,
                filas_escritas,
                filas_descartadas,
                estado,
            ),
        )


def listar_periodos(ruta_manifest: Path, dataset: str | None = None) -> list[RegistroPeriodo]:
    with _conexion(ruta_manifest) as con:
        if dataset:
            filas = con.execute(
                "SELECT dataset, periodo, etag, last_modified, filas_leidas, "
                "filas_escritas, filas_descartadas, estado, ingerido_en "
                "FROM periodos_ingeridos WHERE dataset = ? ORDER BY periodo",
                (dataset,),
            ).fetchall()
        else:
            filas = con.execute(
                "SELECT dataset, periodo, etag, last_modified, filas_leidas, "
                "filas_escritas, filas_descartadas, estado, ingerido_en "
                "FROM periodos_ingeridos ORDER BY dataset, periodo"
            ).fetchall()
    return [RegistroPeriodo(*f) for f in filas]
