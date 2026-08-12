"""Tests de etl.py — HU-2.4/2.5.

Usa CSV sintéticos pequeños (no los 78/110/34 columnas reales completas) —
transformar_y_escribir() itera sobre las columnas que estén presentes, así
que un subconjunto que incluya las columnas referenciadas por columnas.py
(moneda, rubro, código ONU) alcanza para probar la lógica de transformación.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from mcp_mercadopublico.lake import etl
from mcp_mercadopublico.lake.manifest import obtener_periodo


def _escribir_csv(ruta: Path, contenido: str) -> Path:
    ruta.write_text(contenido, encoding="utf-8", newline="")
    return ruta


@pytest.fixture()
def con():
    conexion = duckdb.connect()
    yield conexion
    conexion.close()


# --- transformar_y_escribir: filtro por RubroN1 (OC) ------------------------


def _csv_oc_sintetico(ruta: Path) -> Path:
    contenido = (
        "ID;RubroN1;codigoProductoONU;precioNeto;monedaItem;cantidad;FechaCancelacion\n"
        '1;"Equipamiento para laboratorios";41116007;"19977,72";CLP;3;NA\n'
        '2;"Vehículos y equipamiento en general";25101602;"500,0";CLP;1;NA\n'
        '3;"Equipamiento para laboratorios";41116007;"279,8";CLF;10;1900-01-01\n'
    )
    return _escribir_csv(ruta, contenido)


def test_filtra_por_rubro_n1_y_descarta_el_resto(con, tmp_path: Path):
    csv_path = _csv_oc_sintetico(tmp_path / "2026-6.csv")
    data_dir = tmp_path / "data"

    filas_leidas, filas_escritas, ruta_parquet = etl.transformar_y_escribir(
        con,
        "oc",
        [csv_path],
        2026,
        6,
        data_dir,
        rubros_permitidos=["Equipamiento para laboratorios"],
    )

    assert filas_leidas == 3
    assert filas_escritas == 2  # sólo las 2 filas de "Equipamiento para laboratorios"
    assert ruta_parquet == data_dir / "oc" / "anio=2026" / "mes=6" / "part.parquet"


def test_decimal_coma_se_convierte_a_double(con, tmp_path: Path):
    csv_path = _csv_oc_sintetico(tmp_path / "2026-6.csv")
    data_dir = tmp_path / "data"

    _, _, ruta_parquet = etl.transformar_y_escribir(
        con, "oc", [csv_path], 2026, 6, data_dir,
        rubros_permitidos=["Equipamiento para laboratorios"],
    )

    filas = con.execute(
        f"SELECT id, precio_neto FROM read_parquet('{ruta_parquet.as_posix()}') ORDER BY id"
    ).fetchall()
    assert filas == [("1", 19977.72), ("3", 279.8)]


def test_es_clp_marca_moneda_distinta_de_clp(con, tmp_path: Path):
    csv_path = _csv_oc_sintetico(tmp_path / "2026-6.csv")
    data_dir = tmp_path / "data"

    _, _, ruta_parquet = etl.transformar_y_escribir(
        con, "oc", [csv_path], 2026, 6, data_dir,
        rubros_permitidos=["Equipamiento para laboratorios"],
    )

    filas = con.execute(
        f"SELECT id, es_clp FROM read_parquet('{ruta_parquet.as_posix()}') ORDER BY id"
    ).fetchall()
    assert dict(filas) == {"1": True, "3": False}


def test_es_clp_lic_reconoce_peso_chileno_no_el_codigo_iso(con, tmp_path: Path):
    """Bug real encontrado en producción (2026-08-11, lake ya desplegado):
    LIC trae el nombre en español ('Peso Chileno'), nunca el código ISO
    'CLP' que sí usan OC/COT — comparar contra 'CLP' fijo dejaba es_clp en
    false para el 99,996% de las filas de licitación, silenciando
    benchmark_precio/precio_para_ganar/criterios_que_deciden para ese canal
    (ver VALOR_MONEDA_CLP en columnas.py)."""
    contenido = (
        "Codigo;Rubro1;CodigoProductoONU;Moneda de la Oferta\n"
        '1;"Equipamiento para laboratorios";41116007;Peso Chileno\n'
        '2;"Equipamiento para laboratorios";41116007;Dolar\n'
    )
    csv_path = tmp_path / "lic_2026-6.csv"
    csv_path.write_text(contenido, encoding="utf-8", newline="")
    data_dir = tmp_path / "data"

    _, _, ruta_parquet = etl.transformar_y_escribir(
        con, "lic", [csv_path], 2026, 6, data_dir,
        rubros_permitidos=["Equipamiento para laboratorios"],
    )

    filas = con.execute(
        f"SELECT codigo, es_clp FROM read_parquet('{ruta_parquet.as_posix()}') ORDER BY codigo"
    ).fetchall()
    assert dict(filas) == {"1": True, "2": False}


def test_es_clp_cot_sigue_comparando_contra_el_codigo_iso(con, tmp_path: Path):
    """OC/COT no cambian de comportamiento con el fix — siguen comparando
    contra el código ISO 'CLP', no el nombre en español."""
    contenido = (
        "CodigoCotizacion;CodigoProducto;MontoTotal;moneda\n"
        "1;41116007;100,0;CLP\n"
        "2;41116007;100,0;Dolar\n"
    )
    csv_path = tmp_path / "cot_2026-6.csv"
    csv_path.write_text(contenido, encoding="utf-8", newline="")
    data_dir = tmp_path / "data"

    _, _, ruta_parquet = etl.transformar_y_escribir(
        con, "cot", [csv_path], 2026, 6, data_dir, whitelist_onu=["41116007"],
    )

    filas = con.execute(
        f"SELECT codigo_cotizacion, es_clp FROM read_parquet('{ruta_parquet.as_posix()}') ORDER BY codigo_cotizacion"
    ).fetchall()
    assert dict(filas) == {"1": True, "2": False}


def test_na_y_sentinela_fecha_se_convierten_a_null(con, tmp_path: Path):
    csv_path = _csv_oc_sintetico(tmp_path / "2026-6.csv")
    data_dir = tmp_path / "data"

    _, _, ruta_parquet = etl.transformar_y_escribir(
        con, "oc", [csv_path], 2026, 6, data_dir,
        rubros_permitidos=["Equipamiento para laboratorios"],
    )

    filas = con.execute(
        f"SELECT id, fecha_cancelacion FROM read_parquet('{ruta_parquet.as_posix()}') ORDER BY id"
    ).fetchall()
    assert dict(filas) == {"1": None, "3": None}  # "NA" y "1900-01-01" -> NULL


def test_filtro_rubro_es_case_insensitive(con, tmp_path: Path):
    """Hallazgo real de esta sesión: RubroN1 (OC) viene en Title Case pero
    Rubro1 (LIC) viene en MAYÚSCULAS para el mismo rubro exacto — un match
    por igualdad estricta descarta LIC completo en silencio."""
    contenido = (
        "Codigo;Rubro1;CodigoProductoONU;Moneda de la Oferta\n"
        '1;"EQUIPAMIENTO PARA LABORATORIOS";41116007;CLP\n'
        '2;"VEHÍCULOS Y EQUIPAMIENTO EN GENERAL";25101602;CLP\n'
    )
    csv_path = tmp_path / "lic_2026-6.csv"
    csv_path.write_text(contenido, encoding="utf-8", newline="")
    data_dir = tmp_path / "data"

    filas_leidas, filas_escritas, _ = etl.transformar_y_escribir(
        con, "lic", [csv_path], 2026, 6, data_dir,
        rubros_permitidos=["Equipamiento para laboratorios"],  # Title Case, como en OC
    )

    assert filas_leidas == 2
    assert filas_escritas == 1  # matchea pese a la diferencia de casing


def test_filas_duplicadas_se_deduplican_y_se_registra_el_delta(
    con, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Hallazgo real contra el lake desplegado (2026-08-11): ChileCompra
    publica líneas 100% idénticas en su CSV fuente (~3,8% de COT medido) —
    no es un bug de extracción propio. Se deduplican al escribir, y el
    delta se loggea (nunca se pierde/gana data en silencio)."""
    import logging

    contenido = (
        "ID;RubroN1;codigoProductoONU;precioNeto;monedaItem;cantidad;FechaCancelacion\n"
        '1;"Equipamiento para laboratorios";41116007;"19977,72";CLP;3;NA\n'
        '1;"Equipamiento para laboratorios";41116007;"19977,72";CLP;3;NA\n'  # duplicado exacto
        '2;"Equipamiento para laboratorios";25101602;"500,0";CLP;1;NA\n'
    )
    csv_path = tmp_path / "2026-6.csv"
    csv_path.write_text(contenido, encoding="utf-8", newline="")
    data_dir = tmp_path / "data"

    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.lake.etl"):
        filas_leidas, filas_escritas, ruta_parquet = etl.transformar_y_escribir(
            con, "oc", [csv_path], 2026, 6, data_dir,
            rubros_permitidos=["Equipamiento para laboratorios"],
        )

    assert filas_leidas == 3  # las 3 filas del CSV, duplicado incluido
    assert filas_escritas == 2  # el duplicado se descarta al escribir

    filas = con.execute(
        f"SELECT id FROM read_parquet('{ruta_parquet.as_posix()}') ORDER BY id"
    ).fetchall()
    assert [f[0] for f in filas] == ["1", "2"]  # no quedan dos "1"

    mensajes = [r.message for r in caplog.records]
    assert any("filas_duplicadas_descartadas" in m for m in mensajes)


def test_filas_sin_duplicados_no_generan_warning(con, tmp_path: Path, caplog: pytest.LogCaptureFixture):
    import logging

    csv_path = _csv_oc_sintetico(tmp_path / "2026-6.csv")
    data_dir = tmp_path / "data"

    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.lake.etl"):
        etl.transformar_y_escribir(
            con, "oc", [csv_path], 2026, 6, data_dir,
            rubros_permitidos=["Equipamiento para laboratorios"],
        )

    mensajes = [r.message for r in caplog.records]
    assert not any("filas_duplicadas_descartadas" in m for m in mensajes)


# --- _descartar_filas_moneda_no_reconocida (corrupción del camino tolerante) --


def test_descartar_filas_moneda_no_reconocida_saca_filas_corruptas(
    con, caplog: pytest.LogCaptureFixture
):
    """Simula lo que dejó lic-da/2026-3: una fila con texto arbitrario en la
    columna de moneda (columnas desplazadas por el camino tolerante) — se
    descarta en vez de dejar el dato corrupto, y se loggea el conteo."""
    import logging

    con.execute(
        """
        CREATE TABLE relacion AS SELECT * FROM (VALUES
            (1, 'Peso Chileno'),
            (2, 'Ficha técnica 235.pdf'),
            (3, 'Dolar')
        ) AS v(id, "Moneda de la Oferta")
        """
    )
    relacion = con.table("relacion")

    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.lake.etl"):
        resultado = etl._descartar_filas_moneda_no_reconocida(con, relacion, "lic", 2026, 3)

    filas = con.execute("SELECT id FROM resultado ORDER BY id").fetchall()
    assert [f[0] for f in filas] == [1, 3]  # la fila 2 (corrupta) se descarta

    mensajes = [r.message for r in caplog.records]
    assert any("csv_filas_con_moneda_no_reconocida_tras_camino_tolerante" in m for m in mensajes)


def test_descartar_filas_moneda_no_reconocida_no_toca_nulos(con):
    """Un valor NULL de moneda es dato faltante, no corrupción — no debe
    descartarse por este chequeo (es un problema distinto, ya cubierto por
    NULLIF de NA/vacío en _expresion_columna)."""
    con.execute(
        """
        CREATE TABLE relacion AS SELECT * FROM (VALUES
            (1, 'Peso Chileno'),
            (2, NULL)
        ) AS v(id, "Moneda de la Oferta")
        """
    )
    relacion = con.table("relacion")

    resultado = etl._descartar_filas_moneda_no_reconocida(con, relacion, "lic", 2026, 3)

    filas = con.execute("SELECT id FROM resultado ORDER BY id").fetchall()
    assert [f[0] for f in filas] == [1, 2]


def test_descartar_filas_moneda_no_reconocida_sin_columna_moneda_no_hace_nada(con):
    """Si la relación no tiene la columna de moneda (caso defensivo, no
    debería pasar con los datasets reales), no debe fallar — pasa igual."""
    con.execute("CREATE TABLE relacion AS SELECT * FROM (VALUES (1), (2)) AS v(id)")
    relacion = con.table("relacion")

    resultado = etl._descartar_filas_moneda_no_reconocida(con, relacion, "lic", 2026, 3)

    assert con.execute("SELECT COUNT(*) FROM resultado").fetchone()[0] == 2


def test_csv_malformado_usa_camino_tolerante_y_avisa(
    con, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Bug real (lic-da/2026-3): el parser estricto de DuckDB aborta el
    archivo ENTERO por unas pocas filas con comillas sin escapar, y el
    periodo se perdía completo. El camino tolerante lo rescata y registra
    cuántas filas se descartaron — nunca en silencio.

    Además cubre que read_csv() es lazy: sin forzar la materialización
    dentro del try, la excepción escapaba y el fallback no se usaba.
    """
    import logging

    contenido = (
        "ID;RubroN1;codigoProductoONU;precioNeto;monedaItem\n"
        '1;"Equipamiento para laboratorios";41116007;"100,0";CLP\n'
        # fila malformada: comilla sin cerrar dentro del campo
        '2;"Equipamiento para laboratorios";41116008;"20"0,0";CLP\n'
        '3;"Equipamiento para laboratorios";41116009;"300,0";CLP\n'
    )
    csv_path = tmp_path / "malformado.csv"
    csv_path.write_text(contenido, encoding="utf-8", newline="")

    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.lake.etl"):
        filas_leidas, filas_escritas, ruta = etl.transformar_y_escribir(
            con, "oc", [csv_path], 2026, 3, tmp_path / "data",
            rubros_permitidos=["Equipamiento para laboratorios"],
        )

    # No debe lanzar: el periodo se rescata en vez de perderse entero.
    assert ruta.exists()
    assert filas_leidas >= 2  # al menos las filas bien formadas
    mensajes = [r.message for r in caplog.records]
    assert any("csv_no_rfc4180_usando_camino_tolerante" in m for m in mensajes)


def test_oc_sin_rubros_permitidos_falla(con, tmp_path: Path):
    csv_path = _csv_oc_sintetico(tmp_path / "2026-6.csv")
    with pytest.raises(ValueError, match="rubros_permitidos"):
        etl.transformar_y_escribir(con, "oc", [csv_path], 2026, 6, tmp_path / "data")


# --- COT: filtro por whitelist de código ONU (no tiene columna de rubro) ---


def _csv_cot_sintetico(ruta: Path) -> Path:
    contenido = (
        "CodigoCotizacion;CodigoProducto;MontoTotal;moneda\n"
        "1079967-350-COT26;41116007;2187559,0;CLP\n"
        "1079967-351-COT26;99999999;150000,0;CLP\n"
    )
    return _escribir_csv(ruta, contenido)


def test_cot_filtra_por_whitelist_onu(con, tmp_path: Path):
    csv_path = _csv_cot_sintetico(tmp_path / "COT1_2026-06.csv")
    data_dir = tmp_path / "data"

    _, filas_escritas, ruta_parquet = etl.transformar_y_escribir(
        con, "cot", [csv_path], 2026, 6, data_dir, whitelist_onu=["41116007"]
    )

    assert filas_escritas == 1
    fila = con.execute(
        f"SELECT codigo_producto FROM read_parquet('{ruta_parquet.as_posix()}')"
    ).fetchone()
    assert fila[0] == "41116007"


def test_cot_sin_whitelist_onu_falla(con, tmp_path: Path):
    csv_path = _csv_cot_sintetico(tmp_path / "COT1_2026-06.csv")
    with pytest.raises(ValueError, match="whitelist_onu"):
        etl.transformar_y_escribir(con, "cot", [csv_path], 2026, 6, tmp_path / "data")


def test_cot_whitelist_vacia_no_retiene_nada_pero_advierte(
    con, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    csv_path = _csv_cot_sintetico(tmp_path / "COT1_2026-06.csv")
    import logging

    with caplog.at_level(logging.WARNING, logger="mcp_mercadopublico.lake.etl"):
        _, filas_escritas, _ = etl.transformar_y_escribir(
            con, "cot", [csv_path], 2026, 6, tmp_path / "data", whitelist_onu=[]
        )

    assert filas_escritas == 0
    mensajes = [r.message for r in caplog.records]
    assert any("whitelist_onu_vacia" in m for m in mensajes)


# --- whitelist_codigos_onu_vigente: derivada del lake OC+LIC ya ingerido ---


def test_whitelist_vacia_si_no_hay_lake_todavia(con, tmp_path: Path):
    assert etl.whitelist_codigos_onu_vigente(con, tmp_path / "data") == []


def test_whitelist_se_deriva_de_oc_y_lic_ingeridos(con, tmp_path: Path):
    data_dir = tmp_path / "data"
    csv_oc = _csv_oc_sintetico(tmp_path / "oc.csv")
    etl.transformar_y_escribir(
        con, "oc", [csv_oc], 2026, 6, data_dir,
        rubros_permitidos=["Equipamiento para laboratorios", "Vehículos y equipamiento en general"],
    )

    whitelist = etl.whitelist_codigos_onu_vigente(con, data_dir)

    assert set(whitelist) == {"41116007", "25101602"}


# --- ingerir_periodo: orquestador completo, con manifest ------------------


def test_ingerir_periodo_no_publicado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from mcp_mercadopublico.lake.descarga import ResultadoDescarga

    monkeypatch.setattr(
        etl, "descargar_periodo", lambda *a, **k: ResultadoDescarga(estado="no_publicado")
    )

    resultado = etl.ingerir_periodo(
        "oc", 2027, 1,
        data_dir=tmp_path / "data", manifest_path=tmp_path / "manifest.sqlite",
        scratch_dir=tmp_path / "scratch", rubros_permitidos=["Equipamiento para laboratorios"],
    )

    assert resultado.estado == "no_publicado"


def test_ingerir_periodo_completo_registra_en_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from mcp_mercadopublico.lake.descarga import ResultadoDescarga

    scratch = tmp_path / "scratch"

    def descarga_falsa(dataset, anio, mes, destino_dir, etag_previo=None, **kw):
        destino_dir.mkdir(parents=True, exist_ok=True)
        import zipfile

        zip_path = destino_dir / "2026-6.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "2026-6.csv",
                (
                    "ID;RubroN1;codigoProductoONU;precioNeto;monedaItem\n"
                    '1;"Equipamiento para laboratorios";41116007;"100,0";CLP\n'
                ).encode("latin-1"),
            )
        return ResultadoDescarga(estado="descargado", ruta=zip_path, etag='"etag-1"')

    monkeypatch.setattr(etl, "descargar_periodo", descarga_falsa)

    resultado = etl.ingerir_periodo(
        "oc", 2026, 6,
        data_dir=tmp_path / "data", manifest_path=tmp_path / "manifest.sqlite",
        scratch_dir=scratch, rubros_permitidos=["Equipamiento para laboratorios"],
    )

    assert resultado.estado == "ingerido"
    assert resultado.filas_leidas == 1
    assert resultado.filas_escritas == 1
    assert resultado.ruta_parquet.exists()

    registro = obtener_periodo(tmp_path / "manifest.sqlite", "oc", "2026-6")
    assert registro.etag == '"etag-1"'
    assert registro.filas_escritas == 1

    # el scratch de este periodo se limpia siempre
    assert not (scratch / "oc_2026_6").exists()


def test_ingerir_periodo_reingesta_es_idempotente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from mcp_mercadopublico.lake.descarga import ResultadoDescarga
    import zipfile

    def descarga_falsa(dataset, anio, mes, destino_dir, etag_previo=None, **kw):
        destino_dir.mkdir(parents=True, exist_ok=True)
        zip_path = destino_dir / "2026-6.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "2026-6.csv",
                (
                    "ID;RubroN1;codigoProductoONU;precioNeto;monedaItem\n"
                    '1;"Equipamiento para laboratorios";41116007;"100,0";CLP\n'
                    '2;"Equipamiento para laboratorios";41116008;"200,0";CLP\n'
                ).encode("latin-1"),
            )
        return ResultadoDescarga(estado="descargado", ruta=zip_path, etag='"etag-2"')

    monkeypatch.setattr(etl, "descargar_periodo", descarga_falsa)

    kwargs = dict(
        data_dir=tmp_path / "data", manifest_path=tmp_path / "manifest.sqlite",
        scratch_dir=tmp_path / "scratch", rubros_permitidos=["Equipamiento para laboratorios"],
    )
    etl.ingerir_periodo("oc", 2026, 6, **kwargs)
    resultado2 = etl.ingerir_periodo("oc", 2026, 6, **kwargs)

    assert resultado2.filas_escritas == 2
    from mcp_mercadopublico.lake.manifest import listar_periodos

    todos = listar_periodos(tmp_path / "manifest.sqlite", "oc")
    assert len(todos) == 1  # no duplicó el registro


def test_ingerir_periodo_sin_cambios_no_reprocesa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from mcp_mercadopublico.lake.descarga import ResultadoDescarga
    from mcp_mercadopublico.lake.manifest import registrar_periodo

    registrar_periodo(
        tmp_path / "manifest.sqlite", dataset="oc", periodo="2026-6",
        etag='"ya-tengo-esta"', last_modified=None,
        filas_leidas=10, filas_escritas=5, filas_descartadas=5, estado="ingerido",
    )

    llamadas = {"n": 0}

    def descarga_falsa(dataset, anio, mes, destino_dir, etag_previo=None, **kw):
        llamadas["n"] += 1
        assert etag_previo == '"ya-tengo-esta"'  # debe pasar el etag guardado
        return ResultadoDescarga(estado="sin_cambios", etag=etag_previo)

    monkeypatch.setattr(etl, "descargar_periodo", descarga_falsa)

    resultado = etl.ingerir_periodo(
        "oc", 2026, 6,
        data_dir=tmp_path / "data", manifest_path=tmp_path / "manifest.sqlite",
        scratch_dir=tmp_path / "scratch", rubros_permitidos=["Equipamiento para laboratorios"],
    )

    assert resultado.estado == "sin_cambios"
    assert llamadas["n"] == 1


def test_ingerir_periodo_forzar_ignora_el_etag_guardado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """forzar=True es lo que hace falta para que un fix de transformar_y_escribir
    (es_clp, deduplicación) llegue a un periodo ya ingerido cuyo archivo en
    ChileCompra no cambió — sin esto, el ETag guardado devuelve 'sin_cambios'
    y el periodo se salta entero con código nuevo o no."""
    from mcp_mercadopublico.lake.descarga import ResultadoDescarga
    from mcp_mercadopublico.lake.manifest import registrar_periodo
    import zipfile

    registrar_periodo(
        tmp_path / "manifest.sqlite", dataset="oc", periodo="2026-6",
        etag='"ya-tengo-esta"', last_modified=None,
        filas_leidas=10, filas_escritas=5, filas_descartadas=5, estado="ingerido",
    )

    llamadas = {"n": 0}

    def descarga_falsa(dataset, anio, mes, destino_dir, etag_previo=None, **kw):
        llamadas["n"] += 1
        assert etag_previo is None  # forzar=True no debe pasar el etag guardado
        destino_dir.mkdir(parents=True, exist_ok=True)
        zip_path = destino_dir / "2026-6.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "2026-6.csv",
                (
                    "ID;RubroN1;codigoProductoONU;precioNeto;monedaItem\n"
                    '1;"Equipamiento para laboratorios";41116007;"100,0";CLP\n'
                ).encode("latin-1"),
            )
        return ResultadoDescarga(estado="descargado", ruta=zip_path, etag='"etag-nuevo"')

    monkeypatch.setattr(etl, "descargar_periodo", descarga_falsa)

    resultado = etl.ingerir_periodo(
        "oc", 2026, 6,
        data_dir=tmp_path / "data", manifest_path=tmp_path / "manifest.sqlite",
        scratch_dir=tmp_path / "scratch", rubros_permitidos=["Equipamiento para laboratorios"],
        forzar=True,
    )

    assert resultado.estado == "ingerido"  # se reprocesó, no "sin_cambios"
    assert llamadas["n"] == 1
    registro = obtener_periodo(tmp_path / "manifest.sqlite", "oc", "2026-6")
    assert registro.etag == '"etag-nuevo"'
