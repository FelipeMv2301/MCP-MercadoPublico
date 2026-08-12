"""Tests de server.actualizar_resumen_competencia — corre head_to_head por
cada competidor de la watchlist y escribe/reemplaza la pestaña "Resumen".

No llama a Google real (doble en memoria para el Worksheet) ni a DuckDB con
mocks — usa particiones parquet reales en tmp_path, mismo patrón que
test_server_head_to_head.py.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico import server
from mcp_mercadopublico.config import Settings, cargar_identidad

BIOQUIMICA = "76.563.320-6"
RIVAL_B = "76.502.658-K"
RIVAL_A = "78.116.970-6"

TOML_CON_WATCHLIST = """
[nosotros]
rut = "76.563.320-6"

[ingesta]
periodo_desde = "2025-1"
periodo_hasta = "2026-8"
datasets = ["oc"]
filtro = "rubro_n1"
rubros_n1 = []

[[competencia.liga_b]]
rut = "76.502.658-K"
nombre = "Rival B (comparable)"

[[competencia.liga_a]]
rut = "78.116.970-6"
nombre = "Rival A (alto ticket)"
"""

TOML_SIN_WATCHLIST = """
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


def _particion_lic(data_dir: Path, filas: list[dict]) -> None:
    destino = data_dir / "lic" / "anio=2026" / "mes=6"
    destino.mkdir(parents=True, exist_ok=True)
    valores = ", ".join(
        "('{codigo_externo}', '{rut_proveedor}', '{razon_social_proveedor}', "
        "'{nombre_producto_genrico}', {valor_total_ofertado}, '{oferta_seleccionada}', "
        "'{criterios_evaluacion}')".format(**f)
        for f in filas
    )
    con = duckdb.connect()
    try:
        con.sql(
            f"SELECT * FROM (VALUES {valores}) AS v("
            '"codigo_externo", "rut_proveedor", "razon_social_proveedor", '
            '"nombre_producto_genrico", "valor_total_ofertado", "oferta_seleccionada", '
            '"criterios_evaluacion")'
        ).write_parquet(str(destino / "part.parquet"), compression="zstd")
    finally:
        con.close()


def _cruce(codigo: str, rival: str, *, ganamos: bool) -> list[dict]:
    sel_nosotros = "Seleccionada" if ganamos else "No Seleccionada"
    sel_rival = "No Seleccionada" if ganamos else "Seleccionada"
    return [
        {"codigo_externo": codigo, "rut_proveedor": BIOQUIMICA, "razon_social_proveedor": "Bioquimica",
         "nombre_producto_genrico": "kit", "valor_total_ofertado": 100, "oferta_seleccionada": sel_nosotros,
         "criterios_evaluacion": "precio"},
        {"codigo_externo": codigo, "rut_proveedor": rival, "razon_social_proveedor": "Rival",
         "nombre_producto_genrico": "kit", "valor_total_ofertado": 110, "oferta_seleccionada": sel_rival,
         "criterios_evaluacion": "precio"},
    ]


@pytest.fixture()
def hojas() -> dict[str, HojaFalsa]:
    return {}


@pytest.fixture(autouse=True)
def _sin_llamadas_reales_a_google(monkeypatch: pytest.MonkeyPatch, hojas: dict[str, HojaFalsa]):
    monkeypatch.setattr(server.sheets, "conectar", lambda credenciales: object())

    def _obtener_hoja(cliente, sheet_id, nombre_hoja):
        return hojas.setdefault(nombre_hoja, HojaFalsa())

    monkeypatch.setattr(server.sheets, "obtener_hoja", _obtener_hoja)


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toml: str) -> Settings:
    identidad_toml = tmp_path / "identidad.toml"
    identidad_toml.write_text(toml, encoding="utf-8")
    identidad = cargar_identidad(identidad_toml)
    s = Settings(
        identidad=identidad, data_dir=tmp_path / "data",
        google_credentials={"type": "service_account"}, google_sheet_id="abc123",
    )
    monkeypatch.setattr(server, "get_settings", lambda: s)
    return s


def test_sin_credenciales_devuelve_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    identidad_toml = tmp_path / "identidad.toml"
    identidad_toml.write_text(TOML_CON_WATCHLIST, encoding="utf-8")
    identidad = cargar_identidad(identidad_toml)
    s = Settings(identidad=identidad, data_dir=tmp_path / "data")
    monkeypatch.setattr(server, "get_settings", lambda: s)

    assert "error" in server.actualizar_resumen_competencia()


def test_sin_watchlist_devuelve_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _settings(tmp_path, monkeypatch, TOML_SIN_WATCHLIST)

    assert "error" in server.actualizar_resumen_competencia()


def test_escribe_una_fila_por_competidor_con_liga_correcta(tmp_path: Path, monkeypatch, hojas):
    settings = _settings(tmp_path, monkeypatch, TOML_CON_WATCHLIST)
    filas = []
    filas += _cruce("P1", RIVAL_B, ganamos=True)
    filas += _cruce("P2", RIVAL_B, ganamos=False)
    _particion_lic(settings.data_dir, filas)

    resultado = server.actualizar_resumen_competencia()

    assert resultado["hoja"] == "Resumen"
    assert resultado["competidores_procesados"] == 2
    filas_resumen = hojas["Resumen"].filas
    encabezado = filas_resumen[0]
    assert encabezado == ["competidor", "rut", "liga", "n_cruces", "ganados_por_nosotros", "pct_ganado", "diferencia_pct_mediana", "nota"]

    por_competidor = {fila[encabezado.index("competidor")]: fila for fila in filas_resumen[1:]}
    fila_b = por_competidor["Rival B (comparable)"]
    assert fila_b[encabezado.index("liga")] == "B"
    assert fila_b[encabezado.index("n_cruces")] == "2"
    assert fila_b[encabezado.index("ganados_por_nosotros")] == "1"
    assert fila_b[encabezado.index("pct_ganado")] == "50.0"

    fila_a = por_competidor["Rival A (alto ticket)"]
    assert fila_a[encabezado.index("liga")] == "A"
    assert fila_a[encabezado.index("n_cruces")] == "0"  # sin cruces registrados


def test_ordena_por_n_cruces_descendente(tmp_path: Path, monkeypatch, hojas):
    settings = _settings(tmp_path, monkeypatch, TOML_CON_WATCHLIST)
    # Rival B tiene 2 cruces, Rival A tiene 0 -> B debe ir primero
    _particion_lic(settings.data_dir, _cruce("P1", RIVAL_B, ganamos=True) + _cruce("P2", RIVAL_B, ganamos=True))

    server.actualizar_resumen_competencia()

    filas_resumen = hojas["Resumen"].filas
    competidores_en_orden = [fila[0] for fila in filas_resumen[1:]]
    assert competidores_en_orden == ["Rival B (comparable)", "Rival A (alto ticket)"]


def test_reemplaza_no_acumula_entre_llamadas(tmp_path: Path, monkeypatch, hojas):
    settings = _settings(tmp_path, monkeypatch, TOML_CON_WATCHLIST)
    _particion_lic(settings.data_dir, _cruce("P1", RIVAL_B, ganamos=True))

    server.actualizar_resumen_competencia()
    server.actualizar_resumen_competencia()  # segunda corrida, mismo dato

    filas_resumen = hojas["Resumen"].filas
    # encabezado + 2 competidores, no el doble por correrlo dos veces
    assert len(filas_resumen) == 3


def test_falla_de_un_competidor_no_rompe_el_resto(tmp_path: Path, monkeypatch, hojas):
    settings = _settings(tmp_path, monkeypatch, TOML_CON_WATCHLIST)
    _particion_lic(settings.data_dir, _cruce("P1", RIVAL_B, ganamos=True))

    from mcp_mercadopublico import limites

    original = limites.consultar
    llamadas = {"n": 0}

    def falla_para_rival_a(funcion, *args, **kwargs):
        llamadas["n"] += 1
        if RIVAL_A in args:
            raise limites.ConsultaExcedioTiempoLimite("timeout simulado")
        return original(funcion, *args, **kwargs)

    monkeypatch.setattr(server.limites, "consultar", falla_para_rival_a)

    resultado = server.actualizar_resumen_competencia()

    assert resultado["competidores_procesados"] == 2  # ambos aparecen igual
    filas_resumen = hojas["Resumen"].filas
    encabezado = filas_resumen[0]
    por_competidor = {fila[0]: fila for fila in filas_resumen[1:]}
    fila_a = por_competidor["Rival A (alto ticket)"]
    assert fila_a[encabezado.index("nota")] == "timeout simulado"


def test_falla_de_la_api_de_sheets_devuelve_error(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch, TOML_CON_WATCHLIST)
    _particion_lic(settings.data_dir, _cruce("P1", RIVAL_B, ganamos=True))

    def _obtener_hoja_falla(cliente, sheet_id, nombre_hoja):
        raise RuntimeError("API de Google caída")

    monkeypatch.setattr(server.sheets, "obtener_hoja", _obtener_hoja_falla)

    resultado = server.actualizar_resumen_competencia()

    assert "error" in resultado


def test_canal_se_pasa_a_head_to_head(tmp_path: Path, monkeypatch, hojas):
    """canal='cot' no debe encontrar los cruces armados en 'lic'."""
    settings = _settings(tmp_path, monkeypatch, TOML_CON_WATCHLIST)
    _particion_lic(settings.data_dir, _cruce("P1", RIVAL_B, ganamos=True))

    server.actualizar_resumen_competencia(canal="cot")

    filas_resumen = hojas["Resumen"].filas
    encabezado = filas_resumen[0]
    por_competidor = {fila[0]: fila for fila in filas_resumen[1:]}
    assert por_competidor["Rival B (comparable)"][encabezado.index("n_cruces")] == "0"
