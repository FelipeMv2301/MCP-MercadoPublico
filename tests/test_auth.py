"""Tests de auth.py — HU-7.1. Sin red real: httpx.ASGITransport."""

from __future__ import annotations

import logging

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_mercadopublico.auth import AutenticacionBearerMiddleware

TOKEN = "secreto-de-prueba"


async def _ok(request):
    return JSONResponse({"ok": True})


async def _health(request):
    return JSONResponse({"servidor": "ok"})


def _app_protegida() -> AutenticacionBearerMiddleware:
    app = Starlette(
        routes=[
            Route("/mcp", _ok, methods=["POST"]),
            Route("/health", _health, methods=["GET"]),
        ]
    )
    return AutenticacionBearerMiddleware(app, TOKEN)


async def _cliente(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_sin_header_rechaza_401():
    async with await _cliente(_app_protegida()) as client:
        resp = await client.post("/mcp")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_incorrecto_rechaza_401():
    async with await _cliente(_app_protegida()) as client:
        resp = await client.post("/mcp", headers={"Authorization": "Bearer token-equivocado"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_correcto_pasa():
    async with await _cliente(_app_protegida()) as client:
        resp = await client.post("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_health_no_requiere_auth():
    async with await _cliente(_app_protegida()) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_esquema_basic_en_vez_de_bearer_rechaza(caplog: pytest.LogCaptureFixture):
    async with await _cliente(_app_protegida()) as client:
        with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.auth"):
            resp = await client.post("/mcp", headers={"Authorization": f"Basic {TOKEN}"})
    assert resp.status_code == 401
    assert any("auth_rechazada" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_rechazo_queda_registrado_en_el_log(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.auth"):
        async with await _cliente(_app_protegida()) as client:
            await client.post("/mcp")
    mensajes = [r.message for r in caplog.records]
    assert any("auth_rechazada" in m for m in mensajes)
