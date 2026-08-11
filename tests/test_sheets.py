"""Tests de sheets.py — sin red: un doble en memoria reemplaza gspread.Worksheet."""

from __future__ import annotations

from mcp_mercadopublico import sheets


class HojaFalsa:
    """Doble mínimo de gspread.Worksheet: guarda filas como listas de str,
    igual que devuelve la API real (todo viene como texto)."""

    def __init__(self) -> None:
        self.filas: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(f) for f in self.filas]

    def append_rows(self, valores: list[list]) -> None:
        for fila in valores:
            self.filas.append([str(v) for v in fila])


def test_agregar_filas_en_hoja_vacia_escribe_encabezado_y_datos():
    hoja = HojaFalsa()
    filas = [
        {"codigo_proceso": "P1", "producto": "kit", "monto": 100},
        {"codigo_proceso": "P1", "producto": "reactivo", "monto": 50},
    ]

    escritas = sheets.agregar_filas(hoja, filas)

    assert escritas == 2
    assert hoja.filas == [
        ["codigo_proceso", "producto", "monto"],
        ["P1", "kit", "100"],
        ["P1", "reactivo", "50"],
    ]


def test_agregar_filas_llamada_sucesiva_no_repite_encabezado():
    """Segunda llamada (nueva licitación del mismo competidor) debe
    acumular, no volver a escribir el encabezado ni pisar lo anterior."""
    hoja = HojaFalsa()
    sheets.agregar_filas(hoja, [{"codigo_proceso": "P1", "monto": 100}])
    sheets.agregar_filas(hoja, [{"codigo_proceso": "P2", "monto": 200}])

    assert hoja.filas == [
        ["codigo_proceso", "monto"],
        ["P1", "100"],
        ["P2", "200"],
    ]


def test_agregar_filas_una_sola_llamada_batch_a_append_rows():
    """No debe hacer una llamada a la API por fila — una licitación con
    muchas líneas no puede gastar una request por línea (cuota de Sheets)."""
    llamadas: list[list[list]] = []

    class HojaQueCuenta(HojaFalsa):
        def append_rows(self, valores):
            llamadas.append(valores)
            super().append_rows(valores)

    hoja = HojaQueCuenta()
    filas = [{"codigo_proceso": f"P{i}", "monto": i} for i in range(20)]

    sheets.agregar_filas(hoja, filas)

    assert len(llamadas) == 1  # encabezado + 20 filas en un solo append_rows
    assert len(llamadas[0]) == 21


def test_agregar_filas_vacio_no_llama_a_la_api():
    llamadas = []

    class HojaQueCuenta(HojaFalsa):
        def append_rows(self, valores):
            llamadas.append(valores)

    hoja = HojaQueCuenta()

    assert sheets.agregar_filas(hoja, []) == 0
    assert llamadas == []


def test_leer_filas_reconstruye_dicts_desde_encabezado():
    hoja = HojaFalsa()
    sheets.agregar_filas(hoja, [
        {"codigo_proceso": "P1", "monto": 100},
        {"codigo_proceso": "P2", "monto": 200},
    ])

    filas = sheets.leer_filas(hoja)

    assert filas == [
        {"codigo_proceso": "P1", "monto": "100"},
        {"codigo_proceso": "P2", "monto": "200"},
    ]


def test_leer_filas_hoja_vacia_devuelve_lista_vacia():
    assert sheets.leer_filas(HojaFalsa()) == []


def test_leer_filas_hoja_con_solo_encabezado_devuelve_lista_vacia():
    hoja = HojaFalsa()
    hoja.filas.append(["codigo_proceso", "monto"])

    assert sheets.leer_filas(hoja) == []
