"""Logging estructurado a archivo (HU-1.2).

Regla dura: cero print() en el proceso del servidor. En transporte stdio,
cualquier print() rompe el JSON-RPC del protocolo MCP — aunque el transporte
elegido sea HTTP (D1), la regla se mantiene porque un print() contamina los
logs igual y porque nada impide agregar stdio más adelante.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any

_CAMPOS_ESTANDAR = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class FormateadorJSON(logging.Formatter):
    """Un objeto JSON por línea. Los campos pasados vía extra={...} se
    incorporan tal cual al payload — es la forma en que log_evento_etl()
    adjunta dataset/periodo/filas sin ensuciar el mensaje de texto."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        for clave, valor in record.__dict__.items():
            if clave not in _CAMPOS_ESTANDAR and clave != "extra_fields":
                payload[clave] = valor
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configurar_logging(
    log_dir: Path,
    nivel: str = "INFO",
    nombre_archivo: str = "mcp_mercadopublico.log",
) -> None:
    """Redirige el logging raíz a un archivo rotado. Nunca a stdout/stderr:
    en transporte stdio eso corrompería el canal JSON-RPC del MCP."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / nombre_archivo,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(FormateadorJSON())

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    raiz.handlers = [handler]


def log_evento_etl(
    logger: logging.Logger,
    *,
    dataset: str,
    periodo: str,
    filas_leidas: int,
    filas_escritas: int,
    filas_descartadas: int,
    motivo_descarte: str | None = None,
) -> None:
    """Evento estándar de un periodo procesado por el ingestor (HU-2.x).

    Centralizado para que todo el ETL registre las mismas columnas y un
    dashboard (HU-8.3) pueda agregarlas sin parsear mensajes de texto libre.
    """
    logger.info(
        "etl_periodo_procesado",
        extra={
            "extra_fields": {
                "dataset": dataset,
                "periodo": periodo,
                "filas_leidas": filas_leidas,
                "filas_escritas": filas_escritas,
                "filas_descartadas": filas_descartadas,
                "motivo_descarte": motivo_descarte,
            }
        },
    )
