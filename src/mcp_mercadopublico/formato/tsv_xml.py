"""TSV envuelto en XML — optimización de tokens (referencia técnica §8).

TSV en vez de Markdown ahorra ~40% de tokens en tablas grandes: sin pipes ni
guiones de alineación. Los atributos filas/truncado le dicen a Claude si le
falta data sin que tenga que contar manualmente ni asumir que vio todo.
"""

from __future__ import annotations

from typing import Any


def _celda(valor: Any) -> str:
    """Nulos como celda vacía, no 'None'/'null' — menos ruido para Claude."""
    if valor is None:
        return ""
    return str(valor).replace("\t", " ").replace("\n", " ")


def filas_a_tsv_xml(
    etiqueta: str,
    columnas: list[str],
    filas: list[list[Any]],
    *,
    limite: int | None = None,
) -> str:
    """Envuelve una tabla en <etiqueta formato="TSV" filas="N" truncado="true|false">.

    `filas` es la cantidad de filas MOSTRADAS (no el total real) — si se
    trunca, Claude sabe exactamente cuántas vio y que hay más.
    """
    total = len(filas)
    truncado = limite is not None and total > limite
    mostradas = filas[:limite] if truncado else filas

    lineas = ["\t".join(columnas)]
    lineas.extend("\t".join(_celda(v) for v in fila) for fila in mostradas)
    cuerpo = "\n".join(lineas)

    return (
        f'<{etiqueta} formato="TSV" filas="{len(mostradas)}" '
        f'truncado="{"true" if truncado else "false"}">\n'
        f"{cuerpo}\n"
        f"</{etiqueta}>"
    )
