"""Tests de limites.py — HU-7.2."""

from __future__ import annotations

import logging
import threading

import pytest

from mcp_mercadopublico.limites import ConsultaExcedioTiempoLimite, bloqueo_periodo, consultar


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


# --- bloqueo_periodo -----------------------------------------------------


def test_bloqueo_periodo_serializa_la_misma_clave():
    """Dos hilos pidiendo el mismo (dataset, periodo): el segundo debe
    esperar a que el primero libere, no correr en paralelo — este es el
    escenario real que motiva el lock: scheduler + ingesta manual sobre el
    mismo periodo al mismo tiempo."""
    sosteniendo = threading.Event()
    liberar = threading.Event()
    b_entro = threading.Event()

    def hilo_a():
        with bloqueo_periodo("lic", "2026-6"):
            sosteniendo.set()
            liberar.wait(timeout=5)

    def hilo_b():
        with bloqueo_periodo("lic", "2026-6"):
            b_entro.set()

    a = threading.Thread(target=hilo_a)
    b = threading.Thread(target=hilo_b)
    a.start()
    assert sosteniendo.wait(timeout=2), "hilo_a nunca tomó el lock"
    b.start()

    # Mientras A sostiene el lock, B no debería haber podido entrar todavía.
    assert not b_entro.wait(timeout=0.3)

    liberar.set()
    assert b_entro.wait(timeout=2), "hilo_b nunca pudo entrar tras liberar A"

    a.join(timeout=2)
    b.join(timeout=2)


def test_bloqueo_periodo_no_serializa_claves_distintas():
    """(dataset, periodo) distintos no deben compartir lock — si lo
    compartieran, ingerir 'oc' bloquearía sin necesidad a una ingesta de
    'lic' que no tiene nada que ver."""
    a_dentro = threading.Event()
    b_entro = threading.Event()
    liberar_a = threading.Event()

    def hilo_a():
        with bloqueo_periodo("oc", "2026-6"):
            a_dentro.set()
            liberar_a.wait(timeout=5)

    def hilo_b():
        with bloqueo_periodo("lic", "2026-6"):
            b_entro.set()

    a = threading.Thread(target=hilo_a)
    a.start()
    assert a_dentro.wait(timeout=2)

    b = threading.Thread(target=hilo_b)
    b.start()
    assert b_entro.wait(timeout=2), "clave distinta no debería bloquearse con la de A"

    liberar_a.set()
    a.join(timeout=2)
    b.join(timeout=2)


def test_bloqueo_periodo_libera_el_lock_si_el_cuerpo_lanza_excepcion():
    """Una ingesta que falla a mitad de camino no debe dejar el lock tomado
    para siempre — la siguiente ingesta del mismo periodo debe poder entrar."""
    with pytest.raises(ValueError, match="boom"):
        with bloqueo_periodo("cot", "2026-7"):
            raise ValueError("boom")

    entro = threading.Event()

    def hilo():
        with bloqueo_periodo("cot", "2026-7"):
            entro.set()

    t = threading.Thread(target=hilo)
    t.start()
    assert entro.wait(timeout=1), "el lock quedó tomado tras la excepción"
    t.join(timeout=1)
