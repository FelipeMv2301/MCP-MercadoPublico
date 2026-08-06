"""Tests de limites.py — HU-7.2."""

from __future__ import annotations

import logging

import pytest

from mcp_mercadopublico.limites import ConsultaExcedioTiempoLimite, consultar


def _rapida(con, valor: int) -> int:
    return con.execute("SELECT ?", [valor]).fetchone()[0]


def _lenta(con) -> None:
    con.execute("SELECT SUM(i) FROM range(100000000000) t(i)").fetchone()


def test_consulta_rapida_devuelve_resultado():
    assert consultar(_rapida, 42) == 42


def test_consulta_lenta_se_interrumpe(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.limites"):
        with pytest.raises(ConsultaExcedioTiempoLimite, match="excedió el límite"):
            consultar(_lenta, timeout=0.3)

    mensajes = [r.message for r in caplog.records]
    assert any("consulta_excedio_tiempo_limite" in m for m in mensajes)


def test_pasa_kwargs_correctamente():
    def con_kwarg(con, *, valor):
        return con.execute("SELECT ?", [valor]).fetchone()[0]

    assert consultar(con_kwarg, valor=7) == 7


def test_excepcion_de_la_funcion_se_propaga():
    def falla(con):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        consultar(falla)
