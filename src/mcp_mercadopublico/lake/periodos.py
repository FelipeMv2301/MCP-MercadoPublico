"""Enumeración de periodos (año, mes) — usado por la tool de ingesta masiva."""

from __future__ import annotations


def _parsear(periodo: str) -> tuple[int, int]:
    anio_str, mes_str = periodo.split("-", 1)
    return int(anio_str), int(mes_str)


def generar_periodos(desde: str, hasta: str) -> list[tuple[int, int]]:
    """('2025-1', '2026-8') -> [(2025,1), (2025,2), ..., (2026,8)]. Ambos
    extremos inclusive. Formato AAAA-M (sin cero-padding, como identidad.toml
    y como usan oc-da/lic-da; el padding de COT_ lo aplica url_dataset)."""
    anio_desde, mes_desde = _parsear(desde)
    anio_hasta, mes_hasta = _parsear(hasta)

    if (anio_desde, mes_desde) > (anio_hasta, mes_hasta):
        raise ValueError(f"periodo_desde ({desde}) es posterior a periodo_hasta ({hasta})")

    periodos: list[tuple[int, int]] = []
    anio, mes = anio_desde, mes_desde
    while (anio, mes) <= (anio_hasta, mes_hasta):
        periodos.append((anio, mes))
        mes += 1
        if mes > 12:
            mes = 1
            anio += 1
    return periodos
