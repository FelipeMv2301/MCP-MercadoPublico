from __future__ import annotations

from mcp_mercadopublico.formato.tsv_xml import filas_a_tsv_xml


def test_estructura_basica():
    xml = filas_a_tsv_xml("cuadro", ["a", "b"], [[1, 2], [3, 4]])
    assert xml == (
        '<cuadro formato="TSV" filas="2" truncado="false">\n'
        "a\tb\n1\t2\n3\t4\n"
        "</cuadro>"
    )


def test_nulos_como_celda_vacia_no_none():
    xml = filas_a_tsv_xml("t", ["a", "b"], [[1, None]])
    assert "\t\n" in xml or xml.endswith("1\t")
    assert "None" not in xml
    assert "null" not in xml


def test_trunca_y_marca_atributo():
    filas = [[i] for i in range(10)]
    xml = filas_a_tsv_xml("t", ["a"], filas, limite=3)
    assert 'filas="3"' in xml
    assert 'truncado="true"' in xml
    lineas = xml.splitlines()
    assert lineas[0].startswith("<t ")
    assert lineas[-1] == "</t>"
    assert lineas[1:-1] == ["a", "0", "1", "2"]  # header + 3 filas, ninguna de más


def test_sin_truncar_cuando_cabe_dentro_del_limite():
    xml = filas_a_tsv_xml("t", ["a"], [[1], [2]], limite=10)
    assert 'filas="2"' in xml
    assert 'truncado="false"' in xml


def test_tab_y_newline_embebidos_no_rompen_la_tabla():
    xml = filas_a_tsv_xml("t", ["a"], [["con\ttab y\nnewline"]])
    lineas = xml.splitlines()
    assert len(lineas) == 4  # apertura, header, 1 fila, cierre
    assert "\t" not in lineas[2].replace("con tab y newline", "")  # no quedan tabs internos sin escapar
