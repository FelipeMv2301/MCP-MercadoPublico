"""Ingesta periódica en background — HU-7.3.

Corre DENTRO del mismo proceso/servicio que el servidor MCP: Railway no
comparte Volumes entre servicios (ver Backlog §HU-7.3), así que la ingesta
no puede ser un servicio Railway aparte — tiene que ser una tarea async en
el mismo proceso, arrancada por el `lifespan` de MCPServer.

Después del primer backfill completo, los ciclos siguientes son baratos: la
descarga condicional por ETag (HU-2.1) devuelve 304 para casi todo, así que
recorrer los ~20 periodos configurados no vuelve a bajar los ZIP.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from mcp_mercadopublico.config import Settings
from mcp_mercadopublico.lake.etl import ingerir_periodo
from mcp_mercadopublico.lake.periodos import generar_periodos

logger = logging.getLogger(__name__)

INTERVALO_SEGUNDOS_DEFAULT = 6 * 60 * 60  # cada 6 horas


def _ingerir_ciclo_completo(settings: Settings) -> None:
    """oc/lic primero, siempre — cot depende de la whitelist de códigos ONU
    que se deriva de ellos (ver lake/etl.py: whitelist_codigos_onu_vigente).
    Un fallo en un periodo puntual no debe frenar el resto del ciclo."""
    identidad = settings.identidad
    periodos = generar_periodos(identidad.ingesta.periodo_desde, identidad.ingesta.periodo_hasta)
    rubros = [r.nombre for r in identidad.ingesta.rubros_n1]

    for dataset, rubros_permitidos in (("oc", rubros), ("lic", rubros), ("cot", None)):
        for anio, mes in periodos:
            try:
                resultado = ingerir_periodo(
                    dataset, anio, mes,
                    data_dir=settings.data_dir,
                    manifest_path=settings.manifest_path,
                    scratch_dir=settings.scratch_dir,
                    rubros_permitidos=rubros_permitidos,
                )
                if resultado.estado == "ingerido":
                    logger.info(
                        "ingesta_periodica_periodo_actualizado",
                        extra={
                            "extra_fields": {
                                "dataset": dataset, "periodo": resultado.periodo,
                                "filas_escritas": resultado.filas_escritas,
                            }
                        },
                    )
            except Exception:
                logger.exception(
                    "ingesta_periodica_fallo_periodo",
                    extra={"extra_fields": {"dataset": dataset, "periodo": f"{anio}-{mes}"}},
                )


async def ciclo_ingesta_periodica(settings: Settings, intervalo_segundos: float) -> None:
    """Bucle de fondo: ingiere el rango configurado, duerme, repite.

    CancelledError se deja propagar (no se traga) — es la señal de que el
    servidor está apagando y la tarea debe terminar, no un error a loggear.
    """
    while True:
        try:
            await asyncio.to_thread(_ingerir_ciclo_completo, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ciclo_ingesta_periodica_fallo")
        await asyncio.sleep(intervalo_segundos)


@contextlib.asynccontextmanager
async def lifespan_con_ingesta_periodica(get_settings_fn):
    """Lifespan de MCPServer: arranca la tarea de fondo si
    SCHEDULER_ENABLED=true, la cancela limpio al apagar.

    Deliberadamente apagado por default — sin esto, cada corrida local de
    desarrollo dispararía una ingesta completa de 20 meses sin que nadie lo
    pidiera. Railway lo activa explícitamente vía variable de entorno.
    """
    settings = get_settings_fn()
    tarea: asyncio.Task | None = None

    if settings.scheduler_habilitado:
        logger.info(
            "scheduler_habilitado",
            extra={"extra_fields": {"intervalo_segundos": settings.scheduler_intervalo_segundos}},
        )
        tarea = asyncio.create_task(
            ciclo_ingesta_periodica(settings, settings.scheduler_intervalo_segundos)
        )

    try:
        yield {}
    finally:
        if tarea is not None:
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea
