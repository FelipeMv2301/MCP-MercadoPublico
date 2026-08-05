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
