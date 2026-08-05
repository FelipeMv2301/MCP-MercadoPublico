from __future__ import annotations

import pytest

from mcp_mercadopublico.lake.periodos import generar_periodos


def test_rango_dentro_del_mismo_anio():
    assert generar_periodos("2026-3", "2026-6") == [(2026, 3), (2026, 4), (2026, 5), (2026, 6)]


def test_rango_cruza_anio():
    assert generar_periodos("2025-11", "2026-2") == [
        (2025, 11), (2025, 12), (2026, 1), (2026, 2),
    ]


def test_un_solo_mes():
    assert generar_periodos("2026-6", "2026-6") == [(2026, 6)]


def test_rango_real_de_identidad_toml_tiene_20_periodos():
    periodos = generar_periodos("2025-1", "2026-8")
    assert len(periodos) == 20
    assert periodos[0] == (2025, 1)
    assert periodos[-1] == (2026, 8)


def test_desde_posterior_a_hasta_falla():
    with pytest.raises(ValueError, match="posterior"):
        generar_periodos("2026-6", "2026-1")
