"""Tests de scheduler.py — HU-7.3."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_mercadopublico import scheduler
from mcp_mercadopublico.config import cargar_identidad, RUTA_IDENTIDAD_DEFAULT, Settings


def _settings_de_prueba(tmp_path: Path, *, habilitado: bool = False, intervalo: float = 60.0) -> Settings:
    return Settings(
        identidad=cargar_identidad(RUTA_IDENTIDAD_DEFAULT),
        data_dir=tmp_path / "data",
        manifest_path=tmp_path / "data" / "manifest.sqlite",
        cache_path=tmp_path / "data" / "cache.sqlite",
        mapeos_path=tmp_path / "data" / "mapeos.sqlite",
        scratch_dir=tmp_path / "scratch",
        scheduler_habilitado=habilitado,
        scheduler_intervalo_segundos=intervalo,
    )


# --- lifespan_con_ingesta_periodica -----------------------------------------


@pytest.mark.asyncio
async def test_lifespan_deshabilitado_no_arranca_tarea(tmp_path: Path):
    settings = _settings_de_prueba(tmp_path, habilitado=False)
    async with scheduler.lifespan_con_ingesta_periodica(lambda: settings):
        tareas = [t for t in asyncio.all_tasks() if "ciclo_ingesta_periodica" in str(t.get_coro())]
        assert tareas == []


@pytest.mark.asyncio
async def test_lifespan_habilitado_arranca_y_cancela_limpio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    llegó_a_correr = asyncio.Event()

    async def ciclo_falso(settings, intervalo):
        llegó_a_correr.set()
        await asyncio.sleep(100)  # nunca debe llegar a completarse

    monkeypatch.setattr(scheduler, "ciclo_ingesta_periodica", ciclo_falso)
    settings = _settings_de_prueba(tmp_path, habilitado=True, intervalo=1.0)

    async with scheduler.lifespan_con_ingesta_periodica(lambda: settings):
        await asyncio.wait_for(llegó_a_correr.wait(), timeout=2)
    # si el lifespan no canceló bien, quedaría una tarea sin cerrar
    await asyncio.sleep(0)  # deja correr el loop de eventos una vuelta más


# --- _ingerir_ciclo_completo -------------------------------------------------


def test_ciclo_completo_ingiere_oc_lic_con_rubros_cot_sin_rubros(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    llamadas = []

    def ingerir_falso(dataset, anio, mes, *, data_dir, manifest_path, scratch_dir, rubros_permitidos=None):
        llamadas.append((dataset, anio, mes, rubros_permitidos))
        from mcp_mercadopublico.lake.etl import ResultadoIngesta
        return ResultadoIngesta(dataset=dataset, periodo=f"{anio}-{mes}", estado="sin_cambios")

    monkeypatch.setattr(scheduler, "ingerir_periodo", ingerir_falso)
    settings = _settings_de_prueba(tmp_path)
    # acotar el rango para que el test sea rápido
    settings.identidad.ingesta.periodo_desde = "2026-6"
    settings.identidad.ingesta.periodo_hasta = "2026-6"

    scheduler._ingerir_ciclo_completo(settings)

    datasets_llamados = {c[0] for c in llamadas}
    assert datasets_llamados == {"oc", "lic", "cot"}
    for dataset, anio, mes, rubros in llamadas:
        if dataset == "cot":
            assert rubros is None
        else:
            assert rubros  # oc/lic sí llevan la lista de rubros


def test_ciclo_completo_no_se_detiene_si_un_periodo_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    llamadas = []

    def ingerir_falso(dataset, anio, mes, **kwargs):
        llamadas.append((dataset, anio, mes))
        if dataset == "oc":
            raise RuntimeError("falla simulada de red")
        from mcp_mercadopublico.lake.etl import ResultadoIngesta
        return ResultadoIngesta(dataset=dataset, periodo=f"{anio}-{mes}", estado="sin_cambios")

    monkeypatch.setattr(scheduler, "ingerir_periodo", ingerir_falso)
    settings = _settings_de_prueba(tmp_path)
    settings.identidad.ingesta.periodo_desde = "2026-6"
    settings.identidad.ingesta.periodo_hasta = "2026-6"

    scheduler._ingerir_ciclo_completo(settings)  # no debe lanzar

    assert {c[0] for c in llamadas} == {"oc", "lic", "cot"}  # siguió con lic/cot pese al fallo en oc


# --- ciclo_ingesta_periodica: propagación de CancelledError -----------------


@pytest.mark.asyncio
async def test_ciclo_se_cancela_limpio_durante_el_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    llamadas_a_ingerir = {"n": 0}
    monkeypatch.setattr(scheduler, "_ingerir_ciclo_completo", lambda settings: llamadas_a_ingerir.update(n=llamadas_a_ingerir["n"] + 1))

    settings = _settings_de_prueba(tmp_path, intervalo=60.0)
    tarea = asyncio.create_task(scheduler.ciclo_ingesta_periodica(settings, 60.0))
    await asyncio.sleep(0.05)  # deja que corra una vuelta y entre al sleep
    tarea.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarea

    assert llamadas_a_ingerir["n"] >= 1
