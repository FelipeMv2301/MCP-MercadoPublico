"""Autenticación del endpoint HTTP — HU-7.1.

El SDK oficial de MCP sólo ofrece `token_verifier` acoplado a OAuth completo
(exige `issuer_url`/`resource_server_url` de un authorization server real —
verificado en el código del SDK: "Cannot specify auth_server_provider or
token_verifier without auth settings"). Levantar un servidor OAuth para un
despliegue de un solo usuario es desproporcionado al riesgo.

En su lugar: middleware ASGI propio que exige un bearer token estático
(`MCP_AUTH_TOKEN`) por fuera del mecanismo OAuth del SDK, envolviendo el app
de `mcp.streamable_http_app()` antes de servirlo con uvicorn.
"""

from __future__ import annotations

import hmac
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

RUTAS_PUBLICAS = frozenset({"/health"})


class AutenticacionBearerMiddleware:
    """Exige `Authorization: Bearer <token>` en todo excepto RUTAS_PUBLICAS.

    Comparación con hmac.compare_digest — evita que la diferencia de tiempo
    entre comparar tokens filtre información útil para adivinarlo carácter
    por carácter (timing attack), barato de aplicar y sin downside.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token_esperado = f"Bearer {token}".encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in RUTAS_PUBLICAS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        recibido = headers.get(b"authorization", b"")

        if not hmac.compare_digest(recibido, self._token_esperado):
            logger.warning(
                "auth_rechazada",
                extra={
                    "extra_fields": {
                        "path": scope["path"],
                        "client": scope.get("client"),
                    }
                },
            )
            respuesta = JSONResponse({"error": "unauthorized"}, status_code=401)
            await respuesta(scope, receive, send)
            return

        await self.app(scope, receive, send)
