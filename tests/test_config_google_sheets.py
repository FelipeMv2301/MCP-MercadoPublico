"""Tests de config.py — parseo de GOOGLE_CREDENTIALS/GOOGLE_SHEET_ID.

get_settings() es un singleton (lru_cache) que lee variables de entorno reales
del proceso — a diferencia de test_config.py (que evita tocarlo), acá sí se
usa porque es la única función que hace el parseo de GOOGLE_CREDENTIALS.
cache_clear() antes Y después de cada test para no filtrar estado hacia
otros archivos de test que también llaman get_settings().
"""

from __future__ import annotations

import base64
import json
import logging

import pytest

from mcp_mercadopublico import config

CREDENCIAL_DUMMY = {
    "type": "service_account",
    "project_id": "proyecto-test",
    "client_email": "bot@proyecto-test.iam.gserviceaccount.com",
}


def _b64(datos: dict) -> str:
    return base64.b64encode(json.dumps(datos).encode("utf-8")).decode("ascii")


@pytest.fixture(autouse=True)
def _limpiar_cache():
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_sin_google_credentials_sheets_queda_deshabilitado(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GOOGLE_CREDENTIALS", raising=False)

    settings = config.get_settings()

    assert settings.google_credentials is None
    assert settings.sheets_habilitado is False


def test_google_credentials_valida_se_decodifica(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS", _b64(CREDENCIAL_DUMMY))

    settings = config.get_settings()

    assert settings.google_credentials == CREDENCIAL_DUMMY
    assert settings.sheets_habilitado is True


def test_google_sheet_id_usa_default_si_no_hay_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS", _b64(CREDENCIAL_DUMMY))
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)

    settings = config.get_settings()

    assert settings.google_sheet_id == config.GOOGLE_SHEET_ID_DEFAULT


def test_google_sheet_id_override_por_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS", _b64(CREDENCIAL_DUMMY))
    monkeypatch.setenv("GOOGLE_SHEET_ID", "otro-sheet-id")

    settings = config.get_settings()

    assert settings.google_sheet_id == "otro-sheet-id"


def test_google_credentials_no_base64_no_rompe_el_arranque(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Un valor corrupto en la env var no debe tumbar get_settings() —
    Sheets simplemente queda deshabilitado, con warning (regla del proyecto:
    nunca fallar en silencio, pero tampoco tumbar todo por una integración
    opcional)."""
    monkeypatch.setenv("GOOGLE_CREDENTIALS", "esto-no-es-base64-valido!!!")

    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.config"):
        settings = config.get_settings()

    assert settings.google_credentials is None
    assert settings.sheets_habilitado is False
    mensajes = [r.message for r in caplog.records]
    assert any("google_credentials_invalida" in m for m in mensajes)


def test_google_credentials_base64_valido_pero_no_json_no_rompe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS", base64.b64encode(b"no es json").decode("ascii"))

    settings = config.get_settings()

    assert settings.google_credentials is None
