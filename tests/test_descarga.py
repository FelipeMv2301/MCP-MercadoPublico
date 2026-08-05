"""Tests de descarga.py — HU-2.1. Sin red real: httpx.MockTransport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import tenacity

from mcp_mercadopublico.lake.descarga import (
    _request_con_reintentos,
    descargar_periodo,
    url_dataset,
)


# --- url_dataset: la trampa del padding ------------------------------------


def test_url_oc_sin_padding():
    assert url_dataset("oc", 2026, 6) == "https://transparenciachc.blob.core.windows.net/oc-da/2026-6.zip"


def test_url_lic_sin_padding():
    assert url_dataset("lic", 2026, 6) == "https://transparenciachc.blob.core.windows.net/lic-da/2026-6.zip"


def test_url_cot_con_padding():
    assert url_dataset("cot", 2026, 6) == "https://transparenciachc.blob.core.windows.net/trnspchc/COT_2026-06.zip"


def test_url_oc_nunca_con_padding_aunque_el_mes_sea_de_un_digito():
    """oc-da/2026-06.zip (con padding) da 404 real — nunca debe generarse."""
    url = url_dataset("oc", 2026, 6)
    assert "2026-06.zip" not in url
    assert url.endswith("2026-6.zip")


def test_url_dataset_desconocido_falla():
    with pytest.raises(ValueError, match="desconocido"):
        url_dataset("zgen", 2026, 6)  # type: ignore[arg-type]


# --- descargar_periodo: casos de estado -------------------------------------


def _cliente_mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_descarga_exitosa_escribe_archivo_y_devuelve_etag(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04contenido-zip-falso", headers={"etag": '"abc123"'})

    resultado = descargar_periodo(
        "oc", 2026, 6, tmp_path, client=_cliente_mock(handler)
    )

    assert resultado.estado == "descargado"
    assert resultado.ruta == tmp_path / "2026-6.zip"
    assert resultado.ruta.read_bytes().startswith(b"PK\x03\x04")
    assert resultado.etag == '"abc123"'


def test_etag_previo_se_envia_como_if_none_match(tmp_path: Path):
    headers_recibidos = {}

    def handler(request: httpx.Request) -> httpx.Response:
        headers_recibidos.update(request.headers)
        return httpx.Response(304)

    descargar_periodo(
        "oc", 2026, 6, tmp_path, etag_previo='"viejo-etag"', client=_cliente_mock(handler)
    )

    assert headers_recibidos.get("if-none-match") == '"viejo-etag"'


def test_304_no_modifica_no_escribe_archivo(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    resultado = descargar_periodo(
        "oc", 2026, 6, tmp_path, etag_previo='"abc"', client=_cliente_mock(handler)
    )

    assert resultado.estado == "sin_cambios"
    assert resultado.etag == '"abc"'  # conserva el que ya tenía
    assert list(tmp_path.iterdir()) == []


def test_404_periodo_no_publicado_no_es_error(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="The specified blob does not exist.")

    resultado = descargar_periodo("cot", 2027, 1, tmp_path, client=_cliente_mock(handler))

    assert resultado.estado == "no_publicado"
    assert resultado.ruta is None


def test_5xx_reintenta_y_finalmente_falla(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Override de tenacity.wait a wait_none() — mismo patrón usado para
    verificar el comportamiento sin esperar los backoffs reales en el test."""
    monkeypatch.setattr(_request_con_reintentos.retry, "wait", tenacity.wait_none())

    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(503)

    with pytest.raises(httpx.HTTPStatusError):
        descargar_periodo("oc", 2026, 6, tmp_path, client=_cliente_mock(handler))

    assert llamadas["n"] == 4  # stop_after_attempt(4)


def test_5xx_se_recupera_si_un_reintento_posterior_funciona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(_request_con_reintentos.retry, "wait", tenacity.wait_none())

    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"contenido-ok", headers={"etag": '"final"'})

    resultado = descargar_periodo("oc", 2026, 6, tmp_path, client=_cliente_mock(handler))

    assert resultado.estado == "descargado"
    assert llamadas["n"] == 3


def test_404_no_dispara_reintentos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Un 404 es 'no publicado', no un error transitorio — un solo intento."""
    monkeypatch.setattr(_request_con_reintentos.retry, "wait", tenacity.wait_none())
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(404)

    descargar_periodo("oc", 2026, 6, tmp_path, client=_cliente_mock(handler))

    assert llamadas["n"] == 1
