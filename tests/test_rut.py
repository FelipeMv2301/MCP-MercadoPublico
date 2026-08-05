"""Tests del validador de RUT (módulo 11) — HU-1.1."""

from __future__ import annotations

from mcp_mercadopublico.rut import calcular_dv, dv_esperado, normalizar_rut, rut_valido


def test_normalizar_quita_puntos_y_mantiene_guion():
    assert normalizar_rut("76.563.320-6") == "76563320-6"


def test_normalizar_pasa_dv_a_mayuscula():
    assert normalizar_rut("76.502.658-k") == "76502658-K"


def test_rut_propio_de_bioquimica_es_valido():
    assert rut_valido("76.563.320-6")


def test_rut_dudoso_de_la_watchlist_es_invalido():
    """77.814.808-2, entregado por el usuario, tiene DV incorrecto — ver
    config/identidad.toml [[competencia.dudosos]]."""
    assert not rut_valido("77.814.808-2")
    assert dv_esperado("77.814.808-2") == "0"


def test_rut_corregido_de_la_watchlist_es_valido():
    assert rut_valido("77.814.808-0")


def test_rival_1_real_descubierto_en_el_spike_es_valido():
    """76.502.658-K: rival #1 en compra ágil (61 cruces), figuraba en la
    watchlist original como 'sin actividad' — ver HU-4.1."""
    assert rut_valido("76.502.658-K")


def test_calcular_dv_casos_conocidos():
    assert calcular_dv("76563320") == "6"
    assert calcular_dv("76502658") == "K"
    assert calcular_dv("77814808") == "0"


def test_rut_con_formato_irreconocible_no_es_valido():
    assert not rut_valido("no-es-un-rut")
    assert not rut_valido("")


def test_dv_esperado_none_si_formato_irreconocible():
    assert dv_esperado("no-es-un-rut") is None
