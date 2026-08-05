"""Cero print() en el proceso del servidor (HU-1.2).

En transporte stdio, cualquier print() rompe el JSON-RPC del protocolo MCP.
Este test falla si aparece una LLAMADA real a print( en src/ — el logging
estructurado (logging_setup.py) es la única vía permitida para emitir texto.

Usa el AST en vez de una regex: una regex sobre texto también dispara con
la palabra "print(" dentro de un docstring o comentario (como el de este
mismo módulo, o el de logging_setup.py, que explican la regla en prosa).
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).parent.parent
SRC = RAIZ / "src"


def _llamadas_a_print(archivo: Path) -> list[int]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    lineas: list[int] = []
    for nodo in ast.walk(arbol):
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "print"
        ):
            lineas.append(nodo.lineno)
    return lineas


def test_src_no_contiene_llamadas_a_print():
    ofensores: list[str] = []
    for archivo in sorted(SRC.rglob("*.py")):
        for numero in _llamadas_a_print(archivo):
            ofensores.append(f"{archivo.relative_to(RAIZ)}:{numero}")

    assert not ofensores, "print() encontrado en src/ (rompe stdio):\n" + "\n".join(ofensores)
