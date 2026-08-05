"""Validación y normalización de RUT chileno (módulo 11).

Usado tanto por la carga de configuración (HU-1.1) como por el ETL del lake
(HU-2.3) para los joins entre CSV de Datos Abiertos y el catálogo propio.
"""

from __future__ import annotations

import re

_RUT_FORMATEADO = re.compile(r"^(\d{1,2}(?:\.\d{3}){2})-([0-9Kk])$")
_RUT_SIN_PUNTOS = re.compile(r"^(\d{7,8})-([0-9Kk])$")


def calcular_dv(cuerpo: str) -> str:
    """Dígito verificador módulo 11 para un cuerpo de RUT sin puntos ni guion."""
    suma = 0
    multiplicador = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2
    resto = 11 - (suma % 11)
    return {11: "0", 10: "K"}.get(resto, str(resto))


def normalizar_rut(rut: str) -> str:
    """'76.563.320-6' -> '76563320-6'. Sólo formatea, no valida el DV.

    Necesario porque el RUT llega con puntos desde el TOML de identidad y sin
    puntos desde los CSV de Datos Abiertos (columna RutSucursal) — el join
    entre ambos falla en silencio si no se normaliza primero.
    """
    limpio = rut.strip().upper().replace(".", "")
    return limpio


def dv_esperado(rut: str) -> str | None:
    """DV que debería tener este RUT. None si el formato es irreconocible."""
    limpio = normalizar_rut(rut)
    if "-" not in limpio:
        return None
    cuerpo, _, _dv = limpio.partition("-")
    if not cuerpo.isdigit():
        return None
    return calcular_dv(cuerpo)


def rut_valido(rut: str) -> bool:
    """True si el dígito verificador módulo 11 coincide con el declarado."""
    limpio = normalizar_rut(rut)
    if "-" not in limpio:
        return False
    cuerpo, _, dv = limpio.partition("-")
    if not cuerpo.isdigit() or len(cuerpo) < 7:
        return False
    return calcular_dv(cuerpo) == dv.upper()
