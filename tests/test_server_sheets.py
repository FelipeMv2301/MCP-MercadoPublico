"""Tests de server.exportar_a_sheets / leer_sheets — wiring de la tool.

No llama a Google real: monkeypatchea server.sheets.conectar/obtener_hoja
para devolver una hoja falsa en memoria, igual que test_server_head_to_head.py
monkeypatchea get_settings en vez de tocar el proceso real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_mercadopublico import server
from mcp_mercadopublico.config import Settings, cargar_identidad

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


class HojaFalsa:
    def __init__(self) -> None:
        self.filas: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(f) for f in self.filas]

    def append_rows(self, valores: list[list]) -> None:
        for fila in valores:
            self.filas.append([str(v) for v in fila])

    def clear(self) -> None:
        self.filas = []


@pytest.fixture()
def settings_sin_sheets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    identidad_toml = tmp_path / "identidad.toml"
    identidad_toml.write_text(TOML_MINIMO, encoding="utf-8")
    identidad = cargar_identidad(identidad_toml)
    s = Settings(identidad=identidad, data_dir=tmp_path / "data")
    monkeypatch.setattr(server, "get_settings", lambda: s)
    return s


@pytest.fixture()
def settings_con_sheets(settings_sin_sheets: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = settings_sin_sheets.model_copy(
        update={"google_credentials": {"type": "service_account"}, "google_sheet_id": "abc123"}
    )
    monkeypatch.setattr(server, "get_settings", lambda: s)
    return s


@pytest.fixture()
def hojas() -> dict[str, HojaFalsa]:
    """Simula el spreadsheet: nombre_hoja -> HojaFalsa, se crea sola al pedirla."""
    return {}


@pytest.fixture(autouse=True)
def _sin_llamadas_reales_a_google(monkeypatch: pytest.MonkeyPatch, hojas: dict[str, HojaFalsa]):
    monkeypatch.setattr(server.sheets, "conectar", lambda credenciales: object())

    def _obtener_hoja(cliente, sheet_id, nombre_hoja):
        return hojas.setdefault(nombre_hoja, HojaFalsa())

    monkeypatch.setattr(server.sheets, "obtener_hoja", _obtener_hoja)


def test_exportar_a_sheets_sin_credenciales_devuelve_error(settings_sin_sheets):
    resultado = server.exportar_a_sheets("Rival Uno", [{"codigo_proceso": "P1"}])
    assert "error" in resultado


def test_exportar_a_sheets_con_filas_vacias_devuelve_error(settings_con_sheets):
    resultado = server.exportar_a_sheets("Rival Uno", [])
    assert "error" in resultado


def test_exportar_a_sheets_escribe_en_la_pestana_del_competidor(settings_con_sheets, hojas):
    resultado = server.exportar_a_sheets(
        "Rival Uno",
        [
            {"codigo_proceso": "P1", "producto": "kit", "monto": 100},
            {"codigo_proceso": "P1", "producto": "reactivo", "monto": 50},
        ],
    )

    assert resultado == {"hoja": "Rival Uno", "filas_escritas": 2}
    assert hojas["Rival Uno"].filas == [
        ["codigo_proceso", "producto", "monto"],
        ["P1", "kit", "100"],
        ["P1", "reactivo", "50"],
    ]


def test_exportar_a_sheets_dos_competidores_van_a_pestanas_distintas(settings_con_sheets, hojas):
    server.exportar_a_sheets("Rival Uno", [{"codigo_proceso": "P1"}])
    server.exportar_a_sheets("Rival Dos", [{"codigo_proceso": "P2"}])

    assert set(hojas.keys()) == {"Rival Uno", "Rival Dos"}
    assert hojas["Rival Uno"].filas == [["codigo_proceso"], ["P1"]]
    assert hojas["Rival Dos"].filas == [["codigo_proceso"], ["P2"]]


def test_exportar_a_sheets_llamadas_sucesivas_acumulan(settings_con_sheets, hojas):
    server.exportar_a_sheets("Rival Uno", [{"codigo_proceso": "P1", "monto": 100}])
    server.exportar_a_sheets("Rival Uno", [{"codigo_proceso": "P2", "monto": 200}])

    assert hojas["Rival Uno"].filas == [
        ["codigo_proceso", "monto"],
        ["P1", "100"],
        ["P2", "200"],
    ]


def test_exportar_a_sheets_falla_de_la_api_no_rompe_devuelve_error(
    settings_con_sheets, monkeypatch: pytest.MonkeyPatch
):
    def _obtener_hoja_falla(cliente, sheet_id, nombre_hoja):
        raise RuntimeError("API de Google caída")

    monkeypatch.setattr(server.sheets, "obtener_hoja", _obtener_hoja_falla)

    resultado = server.exportar_a_sheets("Rival Uno", [{"codigo_proceso": "P1"}])

    assert "error" in resultado


def test_leer_sheets_sin_credenciales_devuelve_error(settings_sin_sheets):
    assert "error" in server.leer_sheets("Rival Uno")


def test_leer_sheets_devuelve_lo_ya_exportado(settings_con_sheets, hojas):
    server.exportar_a_sheets(
        "Rival Uno",
        [{"codigo_proceso": "P1", "monto": 100}, {"codigo_proceso": "P2", "monto": 200}],
    )

    resultado = server.leer_sheets("Rival Uno")

    assert resultado["n_filas"] == 2
    assert resultado["filas"] == [
        {"codigo_proceso": "P1", "monto": "100"},
        {"codigo_proceso": "P2", "monto": "200"},
    ]


def test_leer_sheets_pestana_vacia_devuelve_cero_filas(settings_con_sheets):
    resultado = server.leer_sheets("Competidor Nuevo")
    assert resultado == {"hoja": "Competidor Nuevo", "n_filas": 0, "filas": []}
