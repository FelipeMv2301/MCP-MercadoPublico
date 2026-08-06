"""Autenticación del endpoint HTTP — HU-7.1.

El SDK oficial de MCP sólo ofrece `token_verifier` acoplado a OAuth completo
(exige `issuer_url`/`resource_server_url` de un authorization server real —
verificado en el código del SDK: "Cannot specify auth_server_provider or
token_verifier without auth settings"). Levantar un servidor OAuth para un
despliegue de un solo usuario es desproporcionado al riesgo.

En su lugar: middleware ASGI propio que exige un bearer token estático
(`MCP_AUTH_TOKEN`) por fuera del mecanismo OAuth del SDK, envolviendo el app
de `mcp.streamable_http_app()` antes de servirlo con uvicorn.

Acepta el token por header O por query param (`?key=...`) — verificado en
vivo: el modal de "conector personalizado" de claude.ai sólo expone campos
de OAuth Client ID/Secret (ambos opcionales) para autenticación; no hay un
campo simple de API key/header. Sin el query param, no hay forma de pasar
el token desde esa UI sin construir OAuth real. El token en la URL es más
débil que un header (puede quedar en logs de acceso) — trade-off consciente,
no un descuido; ver HU-7.4/docs/conector-claude-ai.md.
"""

from __future__ import annotations

import hmac
import logging
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

RUTAS_PUBLICAS = frozenset({"/health"})


class AutenticacionBearerMiddleware:
    """Exige el token (header `Authorization: Bearer <token>` o query param
    `?key=<token>`) en todo excepto RUTAS_PUBLICAS.

    Comparación con hmac.compare_digest — evita que la diferencia de tiempo
    entre comparar tokens filtre información útil para adivinarlo carácter
    por carácter (timing attack), barato de aplicar y sin downside.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token
        self._token_esperado_header = f"Bearer {token}".encode("utf-8")

    def _autenticado(self, scope: Scope) -> bool:
        headers = dict(scope.get("headers") or [])
        recibido_header = headers.get(b"authorization", b"")
        if hmac.compare_digest(recibido_header, self._token_esperado_header):
            return True

        query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
        valores = parse_qs(query_string).get("key", [])
        if valores and hmac.compare_digest(valores[0], self._token):
            return True

        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in RUTAS_PUBLICAS:
            await self.app(scope, receive, send)
            return

        if not self._autenticado(scope):
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
