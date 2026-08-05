"""Extracción del ZIP + transcodificación a UTF-8 — HU-2.2.

DuckDB sólo puede leer CSV en UTF-8 (su parámetro `encoding` únicamente
valida que el archivo YA sea UTF-8, no convierte — verificado en esta
sesión: lanza BinderException con encoding='latin-1'). La transcodificación
latin-1 -> UTF-8 en streaming de bytes es independiente de la estructura
CSV (no necesita entender columnas ni comillas), así que es segura y rápida
incluso en archivos grandes: 736 MB transcodificaron en ~1,8 s.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_TAMANO_CHUNK = 8 * 1024 * 1024  # 8 MB


def _transcodificar_latin1_a_utf8(origen: Path, destino: Path) -> None:
    with origen.open("rb") as fin, destino.open("w", encoding="utf-8", newline="") as fout:
        while True:
            chunk = fin.read(_TAMANO_CHUNK)
            if not chunk:
                break
            fout.write(chunk.decode("latin-1"))


def extraer_csv_utf8(ruta_zip: Path, destino_dir: Path) -> list[Path]:
    """Extrae los CSV de un ZIP de Datos Abiertos y los transcodifica a
    UTF-8, en el orden en que aparecen dentro del ZIP.

    No asume un único archivo interno ni deriva el nombre interno del
    externo: COT_2026-06.zip contiene COT1_2026-06.csv y COT2_2026-06.csv
    (ChileCompra corta los archivos en ~1 M filas para que abran en Excel;
    son continuación del mismo periodo, no cortes semánticos distintos — la
    concatenación la decide quien llama, no este módulo).

    Descarta el CSV crudo (latin-1) apenas lo transcodifica, para no
    duplicar el uso de disco de scratch mientras procesa el resto del ZIP.
    """
    destino_dir.mkdir(parents=True, exist_ok=True)
    rutas_utf8: list[Path] = []

    with zipfile.ZipFile(ruta_zip) as zf:
        nombres_csv = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not nombres_csv:
            raise ValueError(f"{ruta_zip} no contiene ningún archivo .csv")

        for nombre_interno in nombres_csv:
            ruta_cruda = destino_dir / Path(nombre_interno).name
            with zf.open(nombre_interno) as origen, ruta_cruda.open("wb") as destino_bin:
                while True:
                    chunk = origen.read(_TAMANO_CHUNK)
                    if not chunk:
                        break
                    destino_bin.write(chunk)

            ruta_utf8 = ruta_cruda.with_suffix(".utf8.csv")
            _transcodificar_latin1_a_utf8(ruta_cruda, ruta_utf8)
            ruta_cruda.unlink()
            rutas_utf8.append(ruta_utf8)

    logger.info(
        "zip_extraido",
        extra={"extra_fields": {"zip": str(ruta_zip), "archivos_csv": len(rutas_utf8)}},
    )
    return rutas_utf8
