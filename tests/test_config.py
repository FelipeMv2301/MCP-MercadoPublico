"""Tests de config.py — HU-1.1.

No usan get_settings() (singleton con lru_cache): construyen identidad.toml
temporales con cargar_identidad() para poder probar los casos de falla sin
tocar el config/identidad.toml real del repositorio.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from mcp_mercadopublico.config import RUTA_IDENTIDAD_DEFAULT, cargar_identidad

TOML_MINIMO_VALIDO = """
[nosotros]
rut = "76.563.320-6"

[ingesta]
periodo_desde = "2025-1"
periodo_hasta = "2026-8"
datasets = ["oc"]
filtro = "rubro_n1"
rubros_n1 = []
"""


def _escribir(tmp_path: Path, contenido: str) -> Path:
    ruta = tmp_path / "identidad.toml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def test_identidad_real_del_repositorio_carga_sin_error():
    identidad = cargar_identidad(RUTA_IDENTIDAD_DEFAULT)
    assert identidad.nosotros.rut == "76.563.320-6"
    assert identidad.nosotros.codigo_proveedor == "1202804"


def test_identidad_real_tiene_siete_rubros_de_ingesta():
    identidad = cargar_identidad(RUTA_IDENTIDAD_DEFAULT)
    assert len(identidad.ingesta.rubros_n1) == 7


def test_identidad_real_watchlist_tiene_32_ruts_validos_mas_1_dudoso():
    identidad = cargar_identidad(RUTA_IDENTIDAD_DEFAULT)
    assert len(identidad.competencia.todos_los_rut()) == 32
    assert len(identidad.competencia.dudosos) == 1
    assert identidad.competencia.dudosos[0].rut_entregado == "77.814.808-2"


def test_rut_vacio_falla_al_cargar(tmp_path: Path):
    contenido = TOML_MINIMO_VALIDO.replace('rut = "76.563.320-6"', 'rut = ""')
    ruta = _escribir(tmp_path, contenido)
    with pytest.raises(Exception, match="RUT propio"):
        cargar_identidad(ruta)


def test_rut_invalido_no_declarado_genera_warning_pero_no_falla(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Un RUT con DV incorrecto que NO está en [[competencia.dudosos]] debe
    quedar registrado como warning, sin tumbar la carga (HU-1.1: 'no se
    descartan en silencio')."""
    contenido = TOML_MINIMO_VALIDO + """
[competencia]
sin_actividad_2026_06 = ["12.345.678-9"]
"""
    ruta = _escribir(tmp_path, contenido)
    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.config"):
        identidad = cargar_identidad(ruta)

    assert "12.345.678-9" in identidad.competencia.sin_actividad_2026_06
    mensajes = [r.message for r in caplog.records if r.name == "mcp_mercadopublico.config"]
    assert any("rut_dv_invalido" in m for m in mensajes)


def test_rut_dudoso_ya_declarado_no_se_reporta_dos_veces(caplog: pytest.LogCaptureFixture):
    """77.814.808-2 ya está documentado en [[competencia.dudosos]] — no debe
    generar un segundo warning genérico por aparecer también en otra lista."""
    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.config"):
        cargar_identidad(RUTA_IDENTIDAD_DEFAULT)

    avisos_sobre_ese_rut = [
        r for r in caplog.records
        if r.name == "mcp_mercadopublico.config" and "77.814.808-2" in str(r.__dict__)
    ]
    assert avisos_sobre_ese_rut == []
