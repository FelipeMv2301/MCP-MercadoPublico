"""Descarga condicional de los ZIP de Datos Abiertos — HU-2.1.

Usa GET condicional (If-None-Match) en vez de HEAD+GET: un solo round-trip
en vez de dos, y el servidor no envía el cuerpo cuando responde 304.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import tenacity

logger = logging.getLogger(__name__)

BASE_URL = "https://transparenciachc.blob.core.windows.net"

Dataset = Literal["oc", "lic", "cot"]

# Verificado empíricamente (docs/esquema-datos-abiertos.md §1.1): oc-da/lic-da
# NO llevan cero-padding en el mes; COT_ SÍ lo lleva. No es una regla global.
_PREFIJOS_SIN_PADDING = {"oc": "oc-da", "lic": "lic-da"}


def url_dataset(dataset: Dataset, anio: int, mes: int) -> str:
    """Construye la URL de descarga del periodo (anio, mes) para el dataset.

    ❌ TRAMPA (ver referencia): oc-da/2026-06.zip (con padding) da 404;
    oc-da/2026-6.zip (sin padding) da 200. COT_ es al revés.
    """
    if dataset in _PREFIJOS_SIN_PADDING:
        return f"{BASE_URL}/{_PREFIJOS_SIN_PADDING[dataset]}/{anio}-{mes}.zip"
    if dataset == "cot":
        return f"{BASE_URL}/trnspchc/COT_{anio}-{mes:02d}.zip"
    raise ValueError(f"dataset desconocido: {dataset!r} (usar 'oc', 'lic' o 'cot')")


EstadoDescarga = Literal["descargado", "sin_cambios", "no_publicado"]


@dataclass(frozen=True)
class ResultadoDescarga:
    estado: EstadoDescarga
    ruta: Path | None = None
    etag: str | None = None
    last_modified: str | None = None


def _es_transitorio(exc: BaseException) -> bool:
    """5xx y errores de transporte/timeout ameritan reintento. 4xx no —
    un 404 es 'periodo no publicado', reintentarlo no lo va a cambiar."""
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


@tenacity.retry(
    retry=tenacity.retry_if_exception(_es_transitorio),
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential_jitter(initial=1, max=20),
    reraise=True,
)
def _request_con_reintentos(
    client: httpx.Client, method: str, url: str, **kwargs: object
) -> httpx.Response:
    resp = client.request(method, url, **kwargs)  # type: ignore[arg-type]
    if resp.status_code >= 500:
        resp.raise_for_status()
    return resp


def descargar_periodo(
    dataset: Dataset,
    anio: int,
    mes: int,
    destino_dir: Path,
    etag_previo: str | None = None,
    *,
    client: httpx.Client | None = None,
    timeout: float = 60.0,
) -> ResultadoDescarga:
    """Descarga el ZIP de un periodo si cambió desde etag_previo.

    No usa MERCADO_PUBLICO_TICKET — Datos Abiertos es público, sin
    autenticación. `client` es inyectable para poder testear con
    httpx.MockTransport sin tocar la red real.
    """
    url = url_dataset(dataset, anio, mes)
    nombre_archivo = url.rsplit("/", 1)[-1]
    periodo = f"{anio}-{mes}"

    headers: dict[str, str] = {}
    if etag_previo:
        headers["If-None-Match"] = etag_previo

    propio = client is None
    if propio:
        client = httpx.Client(timeout=timeout, follow_redirects=True)

    try:
        resp = _request_con_reintentos(client, "GET", url, headers=headers)
    finally:
        if propio:
            client.close()

    if resp.status_code == 304:
        logger.info(
            "periodo_sin_cambios",
            extra={"extra_fields": {"dataset": dataset, "periodo": periodo, "etag": etag_previo}},
        )
        return ResultadoDescarga(estado="sin_cambios", etag=etag_previo)

    if resp.status_code == 404:
        logger.info(
            "periodo_no_publicado",
            extra={"extra_fields": {"dataset": dataset, "periodo": periodo, "url": url}},
        )
        return ResultadoDescarga(estado="no_publicado")

    resp.raise_for_status()  # cualquier otro código no manejado -> error real

    destino_dir.mkdir(parents=True, exist_ok=True)
    ruta_destino = destino_dir / nombre_archivo
    ruta_destino.write_bytes(resp.content)

    etag = resp.headers.get("etag")
    last_modified = resp.headers.get("last-modified")
    logger.info(
        "periodo_descargado",
        extra={
            "extra_fields": {
                "dataset": dataset,
                "periodo": periodo,
                "bytes": len(resp.content),
                "etag": etag,
            }
        },
    )
    return ResultadoDescarga(
        estado="descargado", ruta=ruta_destino, etag=etag, last_modified=last_modified
    )
