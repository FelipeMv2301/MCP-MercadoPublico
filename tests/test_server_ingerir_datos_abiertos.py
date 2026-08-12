"""Tests de server.ingerir_datos_abiertos — wiring del parámetro `forzar`.

No llama a descargar_periodo real (red) — monkeypatchea server.ingerir_periodo
para capturar con qué `forzar` se le llama, mismo patrón que
test_server_head_to_head.py usa para get_settings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mercadopublico import server
from mcp_mercadopublico.config import Settings, cargar_identidad
from mcp_mercadopublico.lake.etl import ResultadoIngesta

TOML_MINIMO = """
[nosotros]
rut = "76.563.320-6"

[ingesta]
periodo_desde = "2025-1"
periodo_hasta = "2026-8"
datasets = ["oc"]
filtro = "rubro_n1"
rubros_n1 = []
"""


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    identidad_toml = tmp_path / "identidad.toml"
    identidad_toml.write_text(TOML_MINIMO, encoding="utf-8")
    identidad = cargar_identidad(identidad_toml)
    s = Settings(identidad=identidad, data_dir=tmp_path / "data")
    monkeypatch.setattr(server, "get_settings", lambda: s)
    return s


def test_forzar_default_false_se_pasa_a_ingerir_periodo(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    llamadas = []

    def falso(dataset, anio, mes, **kwargs):
        llamadas.append(kwargs.get("forzar"))
        return ResultadoIngesta(dataset=dataset, periodo=f"{anio}-{mes}", estado="sin_cambios")

    monkeypatch.setattr(server, "ingerir_periodo", falso)

    server.ingerir_datos_abiertos("oc", periodo_desde="2026-1", periodo_hasta="2026-1")

    assert llamadas == [False]


def test_forzar_true_se_propaga_a_todos_los_periodos_del_rango(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    llamadas = []

    def falso(dataset, anio, mes, **kwargs):
        llamadas.append(kwargs.get("forzar"))
        return ResultadoIngesta(dataset=dataset, periodo=f"{anio}-{mes}", estado="ingerido")

    monkeypatch.setattr(server, "ingerir_periodo", falso)

    server.ingerir_datos_abiertos("oc", periodo_desde="2026-1", periodo_hasta="2026-3", forzar=True)

    assert llamadas == [True, True, True]
