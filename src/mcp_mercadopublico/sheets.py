"""Integración con Google Sheets — reportes de competidores visibles al equipo.

Una pestaña por competidor (licitaciones + sus líneas), nombre decidido por
quien llama (Claude, siguiendo la instrucción de su tool) — no hay whitelist
de nombres de pestaña, sólo el spreadsheet destino está fijo (ver
config.GOOGLE_SHEET_ID_DEFAULT): el modelo elige la pestaña, nunca el
documento.

Las funciones reciben el cliente/worksheet ya conectado en vez de armarlo
adentro, para poder testear la lógica de escritura/lectura con un doble en
memoria sin llamar a la API real de Google.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class Worksheet(Protocol):
    """Subconjunto de la interfaz de gspread.Worksheet que usamos — permite
    testear con un doble en memoria en vez de la API real."""

    def get_all_values(self) -> list[list[str]]: ...
    def append_rows(self, valores: list[list[Any]]) -> None: ...


def conectar(credenciales: dict):
    """Abre un cliente gspread autenticado con la service account.

    Import de gspread/google-auth adentro de la función: son dependencias
    sólo de esta integración — si alguien corre el resto del MCP sin
    Sheets configurado, no necesita tenerlas instaladas para nada más."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(credenciales, scopes=_SCOPES)
    return gspread.authorize(creds)


def obtener_hoja(cliente, sheet_id: str, nombre_hoja: str) -> Worksheet:
    """Pestaña `nombre_hoja` del spreadsheet `sheet_id` — la crea si no
    existe (primera vez que se reporta un competidor nuevo)."""
    import gspread

    spreadsheet = cliente.open_by_key(sheet_id)
    try:
        return spreadsheet.worksheet(nombre_hoja)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=nombre_hoja, rows=1000, cols=26)


def agregar_filas(hoja: Worksheet, filas: list[dict[str, Any]]) -> int:
    """Anexa `filas` a la pestaña en una sola llamada batch. Si está vacía,
    el encabezado (llaves del primer dict) va incluido en ese mismo batch —
    llamadas sucesivas para el mismo competidor van acumulando
    licitaciones/líneas, nunca pisan lo anterior.

    Una sola llamada a la API en vez de una por fila: una licitación con
    decenas de líneas no debe gastar decenas de requests contra la cuota de
    Sheets (60 escrituras/min por defecto).

    Devuelve cuántas filas de datos se escribieron (sin contar encabezado).
    """
    if not filas:
        return 0

    encabezado = list(filas[0].keys())
    filas_valores = [[fila.get(col, "") for col in encabezado] for fila in filas]

    hay_encabezado = bool(hoja.get_all_values())
    lote = filas_valores if hay_encabezado else [encabezado, *filas_valores]
    hoja.append_rows(lote)

    return len(filas)


def leer_filas(hoja: Worksheet) -> list[dict[str, Any]]:
    """Devuelve el contenido de la pestaña como lista de dicts (primera fila
    = encabezado), para que una tool de análisis pueda releer lo acumulado."""
    valores = hoja.get_all_values()
    if len(valores) < 2:
        return []
    encabezado, *filas = valores
    return [dict(zip(encabezado, fila)) for fila in filas]
