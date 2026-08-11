"""Límites de recursos — HU-7.2.

DuckDB no tiene timeout de consulta nativo en esta versión (verificado:
'query_timeout' no es un parámetro reconocido — SET lo rechaza). Se
implementa a nivel de aplicación: la consulta corre en un hilo aparte y, si
excede el plazo, se interrumpe con con.interrupt() — la única forma
documentada de cancelar una consulta DuckDB en curso desde otro hilo.

Endpoint público sobre un lake de decenas de millones de filas: el riesgo no
es confidencialidad (los datos son públicos), es que una consulta sin acotar
tumbe el proceso para todos los demás. Ninguna tool expone SQL arbitrario a
Claude (ver server.py) — esto es la segunda capa, por si un filtro amplio
(sin producto/organismo) igual termina escaneando de más.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, ParamSpec, TypeVar

import duckdb

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS_DEFAULT = 10.0
MAX_PERIODOS_POR_INGESTA = 36  # 3 años — una ingesta más larga se pide en tandas
MAX_CRUCES_HEAD_TO_HEAD = 50  # head_to_head() no tenía límite propio (HU-7.2)
LIMITE_MAXIMO_HEAD_TO_HEAD = 200  # tope duro del parámetro `limite` — evita que
# un cliente pida una página gigante y vuelva a inundar el contexto del LLM.

P = ParamSpec("P")
R = TypeVar("R")


class ConsultaExcedioTiempoLimite(Exception):
    """Se interrumpió la consulta por exceder el plazo — no es un bug, es
    la protección de HU-7.2 actuando. El mensaje ya viene listo para Claude."""


def consultar(
    funcion: Callable[..., R],
    *args: object,
    timeout: float = TIMEOUT_SEGUNDOS_DEFAULT,
    **kwargs: object,
) -> R:
    """Abre una conexión DuckDB propia, corre funcion(con, *args, **kwargs)
    con un plazo máximo, y la cierra siempre. Si se excede el plazo,
    interrumpe la conexión y lanza ConsultaExcedioTiempoLimite en vez de
    dejar el hilo colgado indefinidamente."""
    con = duckdb.connect()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(funcion, con, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                con.interrupt()
                nombre_funcion = getattr(funcion, "__name__", str(funcion))
                logger.warning(
                    "consulta_excedio_tiempo_limite",
                    extra={"extra_fields": {"funcion": nombre_funcion, "timeout": timeout}},
                )
                raise ConsultaExcedioTiempoLimite(
                    f"La consulta excedió el límite de {timeout:.1f}s. "
                    "Acota el rango de fechas o el filtro de producto/organismo."
                ) from None
    finally:
        con.close()


# --------------------------------------------------------------------------
# Lock por periodo de ingesta — evita que dos ingestas del mismo
# (dataset, periodo) corran a la vez y se pisen escribiendo el mismo
# part.parquet. Server (tool manual) y scheduler (ciclo de fondo) corren en
# el mismo proceso (ver scheduler.py) — un lock en memoria alcanza; no
# protege entre réplicas/procesos distintos si algún día se escala así.
# --------------------------------------------------------------------------

_locks_periodo: dict[tuple[str, str], threading.Lock] = {}
_locks_periodo_guardian = threading.Lock()


@contextmanager
def bloqueo_periodo(dataset: str, periodo: str) -> Iterator[None]:
    """Serializa las ingestas de un mismo (dataset, periodo). Una segunda
    llamada para la misma clave espera a que la primera termine en vez de
    correr en paralelo y pisar el parquet/manifest del otro."""
    clave = (dataset, periodo)
    with _locks_periodo_guardian:
        lock = _locks_periodo.setdefault(clave, threading.Lock())
    with lock:
        yield
