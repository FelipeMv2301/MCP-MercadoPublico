"""Pipeline completo de ingesta: descarga -> extracción -> transform -> Parquet -> manifest.

HU-2.4 (transformar_y_escribir) + HU-2.5 (ingerir_periodo, el orquestador).
Van juntas porque una sin la otra queda a medio construir: transformar sin
persistir el resultado en el manifest no es una ingesta utilizable.
"""

from __future__ import annotations

import csv
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from mcp_mercadopublico.lake.columnas import (
    COLUMNA_CODIGO_PRODUCTO_ONU,
    COLUMNA_MONEDA,
    COLUMNA_RUBRO_N1,
    COLUMNAS_NUMERICAS,
    VALOR_MONEDA_CLP,
    VALORES_MONEDA_VALIDOS,
    a_snake_case,
    renombrar_columnas,
)
from mcp_mercadopublico import limites
from mcp_mercadopublico.lake.descarga import Dataset, descargar_periodo
from mcp_mercadopublico.lake.extraccion import extraer_csv_utf8
from mcp_mercadopublico.lake.manifest import obtener_periodo, registrar_periodo
from mcp_mercadopublico.logging_setup import log_evento_etl

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultadoIngesta:
    dataset: str
    periodo: str
    estado: str  # "ingerido" | "sin_cambios" | "no_publicado"
    filas_leidas: int = 0
    filas_escritas: int = 0
    filas_descartadas: int = 0
    ruta_parquet: Path | None = None


# --------------------------------------------------------------------------
# Construcción de la proyección SQL (renombre + tipado + nulos) — HU-2.3/2.4
# --------------------------------------------------------------------------


def _escapar_identificador(nombre: str) -> str:
    return '"' + nombre.replace('"', '""') + '"'


def _expresion_columna(original: str, snake: str, numericas: frozenset[str]) -> str:
    ident = _escapar_identificador(original)
    if original in numericas:
        # P2 (decimal con coma) + P4 (NA/vacío nulo). Las columnas numéricas
        # no traen el sentinela de fecha, así que no hace falta ese NULLIF.
        valor = f"NULLIF(NULLIF(REPLACE({ident}, ',', '.'), 'NA'), '')"
        expr = f"TRY_CAST({valor} AS DOUBLE)"
    else:
        # P4/P5/P6: "NA", "" y el sentinela 1900-01-01 -> NULL, incluso en
        # columnas de texto libre (DireccionVisita/DireccionEntrega quedan
        # contaminadas con la fecha sentinela por un bug del dataset).
        expr = ident
        for nulo in ("'NA'", "''", "'1900-01-01'"):
            expr = f"NULLIF({expr}, {nulo})"
    return f"{expr} AS {_escapar_identificador(snake)}"


def _construir_proyeccion(columnas_originales: list[str], mapa: dict[str, str], dataset: str) -> str:
    numericas = COLUMNAS_NUMERICAS[dataset]
    piezas = [_expresion_columna(c, mapa[c], numericas) for c in columnas_originales]

    # P15: precioNeto/MontoUnitarioOferta/MontoTotal no siempre son CLP.
    # es_clp deja explícito el filtro que toda tool de precios debe aplicar.
    # El literal que significa "es CLP" NO es el mismo en los tres datasets
    # (OC/COT traen el código ISO, LIC el nombre en español) — ver
    # VALOR_MONEDA_CLP; comparar contra 'CLP' fijo dejaba es_clp siempre en
    # false para LIC (bug real encontrado en producción, 2026-08-11).
    moneda_original = COLUMNA_MONEDA[dataset]
    moneda_snake = mapa[moneda_original]
    valor_clp = VALOR_MONEDA_CLP[dataset].replace("'", "''")
    piezas.append(
        f"(UPPER(TRIM({_escapar_identificador(moneda_snake)})) = UPPER('{valor_clp}')) AS es_clp"
    )

    return ", ".join(piezas)


# --------------------------------------------------------------------------
# Filtro: por RubroN1 (OC/LIC) o por whitelist de código ONU (COT) — HU-2.4
# --------------------------------------------------------------------------


def whitelist_codigos_onu_vigente(con: duckdb.DuckDBPyConnection, data_dir: Path) -> list[str]:
    """Códigos ONU/UNSPSC presentes en el lake de OC+LIC ya ingerido.

    COT no tiene columna de rubro (ver columnas.py) — se filtra por esta
    whitelist en vez de por RubroN1. Por eso el orden de ingesta importa:
    ingerir al menos un periodo de OC o LIC antes de ingerir COT, o esto
    vuelve vacío y COT no retiene ninguna fila (se advierte, no falla en
    silencio — ver _clausula_filtro).
    """
    piezas = []
    for ds in ("oc", "lic"):
        directorio = data_dir / ds
        if not directorio.exists() or not any(directorio.glob("**/*.parquet")):
            continue
        snake = a_snake_case(COLUMNA_CODIGO_PRODUCTO_ONU[ds])
        ident = _escapar_identificador(snake)
        patron = (directorio / "**" / "*.parquet").as_posix()
        piezas.append(
            f"SELECT DISTINCT {ident} AS c FROM read_parquet('{patron}', union_by_name=true) "
            f"WHERE {ident} IS NOT NULL"
        )
    if not piezas:
        return []
    filas = con.execute(" UNION ".join(piezas)).fetchall()
    return [f[0] for f in filas]


def _clausula_filtro(
    dataset: str,
    mapa: dict[str, str],
    rubros_permitidos: list[str] | None,
    whitelist_onu: list[str] | None,
) -> tuple[str, list]:
    rubro_original = COLUMNA_RUBRO_N1[dataset]

    if rubro_original is not None:
        if not rubros_permitidos:
            raise ValueError(
                f"dataset {dataset!r} tiene columna de rubro pero no se pasó rubros_permitidos"
            )
        # Comparación case-insensitive: verificado que RubroN1 (OC) viene en
        # Title Case ("Equipamiento para laboratorios") pero Rubro1 (LIC)
        # viene en MAYÚSCULAS ("EQUIPAMIENTO PARA LABORATORIOS") para el
        # mismo rubro — un match exacto habría descartado LIC completo.
        ident = _escapar_identificador(mapa[rubro_original])
        rubros_upper = [r.upper() for r in rubros_permitidos]
        return f"UPPER({ident}) = ANY($1)", [rubros_upper]

    if whitelist_onu is None:
        raise ValueError(
            "dataset 'cot' no tiene columna de rubro — requiere whitelist_onu "
            "(ver whitelist_codigos_onu_vigente, derivada de OC+LIC ya ingeridos)"
        )
    if not whitelist_onu:
        logger.warning(
            "whitelist_onu_vacia",
            extra={
                "extra_fields": {
                    "dataset": dataset,
                    "detalle": "COT no retendrá ninguna fila; ingerir un periodo de OC o LIC primero",
                }
            },
        )
    ident = _escapar_identificador(mapa[COLUMNA_CODIGO_PRODUCTO_ONU[dataset]])
    return f"{ident} = ANY($1)", [whitelist_onu]


# --------------------------------------------------------------------------
# Transform + escritura Parquet — HU-2.4
# --------------------------------------------------------------------------


def _header_con_python(ruta: Path) -> list[str]:
    """Lee el header con el parser CSV de Python, que es más tolerante que el
    de DuckDB. Usado para armar `columns=` explícito y saltar el sniffer."""
    csv.field_size_limit(10**9)
    with ruta.open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f, delimiter=";", quotechar='"'))


def _contar_filas_con_python(rutas: list[Path]) -> int:
    """Cuenta filas de datos con el parser de Python (tolerante), para poder
    reportar cuántas descartó DuckDB en el camino tolerante."""
    csv.field_size_limit(10**9)
    total = 0
    for ruta in rutas:
        with ruta.open(encoding="utf-8", newline="") as f:
            lector = csv.reader(f, delimiter=";", quotechar='"')
            next(lector, None)  # header
            total += sum(1 for _ in lector)
    return total


def _leer_csv(
    con: duckdb.DuckDBPyConnection,
    origen: str | list[str],
    rutas_csv: list[Path],
    dataset: str,
    anio: int,
    mes: int,
) -> duckdb.DuckDBPyRelation:
    """Lee los CSV con DuckDB, con un camino tolerante para archivos que no
    cumplen RFC 4180.

    Bug real encontrado en producción (2026-08-06): `lic-da/2026-3` aborta con
    "The CSV Parser state machine reached an invalid state". El archivo trae
    5 filas malformadas entre 160.271 (comillas sin escapar) — el parser de
    Python las tolera, el sniffer de dialecto de DuckDB aborta el archivo
    entero. Un periodo así se perdía por completo.

    Camino rápido (la mayoría de los periodos): read_csv normal.
    Camino tolerante: columnas explícitas (salta el sniffer, que es lo que
    realmente falla) + strict_mode=False + ignore_errors. Ese camino SÍ
    descarta filas, así que se cuenta con Python y se registra el delta —
    nunca se pierde data en silencio (regla transversal del proyecto).
    """
    try:
        relacion_rapida = con.read_csv(
            origen,
            delimiter=";",
            quotechar='"',
            encoding="UTF-8",
            header=True,
            all_varchar=True,
            sample_size=200_000,
        )
        # read_csv() es LAZY: no valida el archivo hasta que se consulta la
        # relación. Sin este COUNT dentro del try, el error de parseo escapa
        # del except y el camino tolerante nunca se usa.
        con.execute("SELECT COUNT(*) FROM relacion_rapida").fetchone()
        return relacion_rapida
    except duckdb.Error as exc:
        logger.warning(
            "csv_no_rfc4180_usando_camino_tolerante",
            extra={
                "extra_fields": {
                    "dataset": dataset,
                    "periodo": f"{anio}-{mes}",
                    "error_duckdb": str(exc)[:200],
                }
            },
        )

    columnas = {nombre: "VARCHAR" for nombre in _header_con_python(rutas_csv[0])}
    relacion = con.read_csv(
        origen,
        delimiter=";",
        quotechar='"',
        encoding="UTF-8",
        header=True,
        columns=columnas,
        strict_mode=False,
        ignore_errors=True,
    )

    filas_duckdb = con.execute("SELECT COUNT(*) FROM relacion").fetchone()[0]
    filas_python = _contar_filas_con_python(rutas_csv)
    descartadas = filas_python - filas_duckdb
    if descartadas > 0:
        logger.warning(
            "csv_filas_descartadas_por_malformacion",
            extra={
                "extra_fields": {
                    "dataset": dataset,
                    "periodo": f"{anio}-{mes}",
                    "filas_parseables": filas_python,
                    "filas_leidas": filas_duckdb,
                    "descartadas": descartadas,
                    "pct_descartado": round(100 * descartadas / max(filas_python, 1), 3),
                }
            },
        )

    return _descartar_filas_moneda_no_reconocida(con, relacion, dataset, anio, mes)


def _descartar_filas_moneda_no_reconocida(
    con: duckdb.DuckDBPyConnection,
    relacion: duckdb.DuckDBPyRelation,
    dataset: str,
    anio: int,
    mes: int,
) -> duckdb.DuckDBPyRelation:
    """El camino tolerante (ignore_errors=True) puede 'rescatar' una línea
    malformada con las columnas desplazadas en vez de descartarla — el
    conteo de filas (filas_python vs filas_duckdb, más arriba) no detecta
    esto porque la fila sigue existiendo, sólo con datos corruptos.

    Bug real (lic-da/2026-3): ~25 filas quedaron con texto arbitrario
    (nombre de archivo, RUT, fecha) en la columna de moneda. Se valida esa
    columna contra los valores conocidos del dataset (VALORES_MONEDA_VALIDOS)
    y se descarta la fila si no calza — no se intenta "corregir" el
    desplazamiento, no hay forma confiable de saber a qué columna real
    pertenecía cada valor."""
    moneda_col = COLUMNA_MONEDA[dataset]
    if moneda_col not in relacion.columns:
        return relacion

    ident = _escapar_identificador(moneda_col)
    # UPPER(TRIM(...)) — mismo criterio que usa es_clp en _construir_proyeccion.
    # Sin esto, un valor legítimo con distinto casing/espacios ("PESO CHILENO",
    # "Peso Chileno ") pasaría el chequeo de es_clp pero se descartaría acá
    # como "corrupto", perdiendo filas válidas en vez de sólo mal-clasificarlas.
    lista_sql = ", ".join(f"UPPER('{v}')" for v in VALORES_MONEDA_VALIDOS[dataset])
    condicion_valida = f"{ident} IS NULL OR UPPER(TRIM({ident})) IN ({lista_sql})"

    total = con.execute("SELECT COUNT(*) FROM relacion").fetchone()[0]
    validas = con.execute(f"SELECT COUNT(*) FROM relacion WHERE {condicion_valida}").fetchone()[0]
    invalidas = total - validas

    if invalidas == 0:
        return relacion

    logger.warning(
        "csv_filas_con_moneda_no_reconocida_tras_camino_tolerante",
        extra={
            "extra_fields": {
                "dataset": dataset,
                "periodo": f"{anio}-{mes}",
                "columna": moneda_col,
                "filas_descartadas": invalidas,
                "detalle": (
                    "Valor de moneda no reconocido tras el camino tolerante — probable "
                    "desplazamiento de columnas en una línea malformada; se descarta la "
                    "fila en vez de dejar el dato corrupto."
                ),
            }
        },
    )
    return con.sql(f"SELECT * FROM relacion WHERE {condicion_valida}")


def transformar_y_escribir(
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    rutas_csv: list[Path],
    anio: int,
    mes: int,
    data_dir: Path,
    *,
    rubros_permitidos: list[str] | None = None,
    whitelist_onu: list[str] | None = None,
) -> tuple[int, int, Path]:
    """Lee los CSV ya extraídos/transcodificados a UTF-8, renombra y tipa
    columnas, filtra y escribe una partición Parquet.

    Devuelve (filas_leidas, filas_escritas, ruta_parquet). `filas_leidas` ya
    viene neto de lo que _leer_csv descartó por corrupción del camino
    tolerante (ver _descartar_filas_moneda_no_reconocida) — no aparece en
    ese log separado. La diferencia entre filas_leidas y filas_escritas es
    el filtro de rubro/whitelist MÁS la deduplicación de filas 100%
    idénticas (ver `duplicadas` en el log `filas_duplicadas_descartadas`) —
    ninguno de los dos se trunca en silencio, pero quedan mezclados en este
    delta; el llamador que necesite separarlos debe leer los logs, no sólo
    este número.
    """
    origen = str(rutas_csv[0]) if len(rutas_csv) == 1 else [str(r) for r in rutas_csv]
    rel_origen = _leer_csv(con, origen, rutas_csv, dataset, anio, mes)
    filas_leidas = con.execute("SELECT COUNT(*) FROM rel_origen").fetchone()[0]

    columnas_originales = rel_origen.columns
    mapa = renombrar_columnas(columnas_originales)
    proyeccion = _construir_proyeccion(columnas_originales, mapa, dataset)
    where_sql, params = _clausula_filtro(dataset, mapa, rubros_permitidos, whitelist_onu)

    rel_filtrada = con.sql(
        f"SELECT {proyeccion} FROM rel_origen WHERE {where_sql}", params=params
    )

    # ChileCompra publica líneas 100% idénticas en su CSV fuente (verificado
    # contra el lake real, 2026-08-11: ~3,8% de las filas de COT) — no es un
    # bug de extracción propio, se deduplica al escribir. DISTINCT sobre
    # todas las columnas: dos líneas de producto distinto de un mismo
    # proceso NUNCA son iguales en todas las columnas a la vez, así que esto
    # no puede confundir líneas legítimas con duplicados.
    rel_deduplicada = con.sql("SELECT DISTINCT * FROM rel_filtrada")
    filas_tras_filtro = con.execute("SELECT COUNT(*) FROM rel_filtrada").fetchone()[0]
    filas_unicas = con.execute("SELECT COUNT(*) FROM rel_deduplicada").fetchone()[0]
    duplicadas = filas_tras_filtro - filas_unicas
    if duplicadas > 0:
        logger.warning(
            "filas_duplicadas_descartadas",
            extra={
                "extra_fields": {
                    "dataset": dataset,
                    "periodo": f"{anio}-{mes}",
                    "duplicadas": duplicadas,
                    "pct_duplicado": round(100 * duplicadas / max(filas_tras_filtro, 1), 3),
                }
            },
        )

    destino_dir = data_dir / dataset / f"anio={anio}" / f"mes={mes}"
    destino_dir.mkdir(parents=True, exist_ok=True)
    ruta_parquet = destino_dir / "part.parquet"
    rel_deduplicada.write_parquet(str(ruta_parquet), compression="zstd")

    filas_escritas = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{ruta_parquet.as_posix()}')"
    ).fetchone()[0]

    return filas_leidas, filas_escritas, ruta_parquet


# --------------------------------------------------------------------------
# Orquestador completo — HU-2.5
# --------------------------------------------------------------------------


def ingerir_periodo(
    dataset: Dataset,
    anio: int,
    mes: int,
    *,
    data_dir: Path,
    manifest_path: Path,
    scratch_dir: Path,
    rubros_permitidos: list[str] | None = None,
    forzar: bool = False,
) -> ResultadoIngesta:
    """Pipeline de un periodo: manifest -> descarga condicional -> extracción
    -> transform -> Parquet -> actualizar manifest -> limpiar scratch.

    Idempotente: reingerir el mismo periodo reemplaza su partición (mismo
    nombre de archivo) y su fila en el manifest — seguro de volver a llamar.
    El scratch se limpia siempre (éxito o excepción), nunca deja el ZIP ni
    los CSV intermedios ocupando disco entre ingestas.

    Serializado por (dataset, periodo) (ver limites.bloqueo_periodo): sin
    esto, dos llamadas concurrentes al mismo periodo (ej. el scheduler de
    fondo y una ingesta manual) escribirían al mismo part.parquet a la vez.

    `forzar=True` ignora el ETag guardado y siempre descarga/reprocesa —
    necesario para que un fix de transformar_y_escribir (ej. es_clp,
    deduplicación) llegue a periodos YA ingeridos: si el archivo de
    ChileCompra no cambió, el ETag hace que el servidor responda 304 y el
    periodo se salte entero, código nuevo o no.
    """
    periodo = f"{anio}-{mes}"
    with limites.bloqueo_periodo(dataset, periodo):
        registro_previo = None if forzar else obtener_periodo(manifest_path, dataset, periodo)
        etag_previo = registro_previo.etag if registro_previo else None

        scratch_periodo = scratch_dir / f"{dataset}_{anio}_{mes}"

        try:
            resultado_descarga = descargar_periodo(
                dataset, anio, mes, scratch_periodo, etag_previo=etag_previo
            )

            if resultado_descarga.estado == "no_publicado":
                return ResultadoIngesta(dataset=dataset, periodo=periodo, estado="no_publicado")

            if resultado_descarga.estado == "sin_cambios":
                return ResultadoIngesta(dataset=dataset, periodo=periodo, estado="sin_cambios")

            con = duckdb.connect()
            try:
                rutas_csv = extraer_csv_utf8(resultado_descarga.ruta, scratch_periodo / "extraido")

                whitelist_onu = (
                    whitelist_codigos_onu_vigente(con, data_dir) if dataset == "cot" else None
                )

                filas_leidas, filas_escritas, ruta_parquet = transformar_y_escribir(
                    con,
                    dataset,
                    rutas_csv,
                    anio,
                    mes,
                    data_dir,
                    rubros_permitidos=rubros_permitidos,
                    whitelist_onu=whitelist_onu,
                )
            finally:
                con.close()
        finally:
            shutil.rmtree(scratch_periodo, ignore_errors=True)

        filas_descartadas = filas_leidas - filas_escritas
        registrar_periodo(
            manifest_path,
            dataset=dataset,
            periodo=periodo,
            etag=resultado_descarga.etag,
            last_modified=resultado_descarga.last_modified,
            filas_leidas=filas_leidas,
            filas_escritas=filas_escritas,
            filas_descartadas=filas_descartadas,
            estado="ingerido",
        )
        log_evento_etl(
            logger,
            dataset=dataset,
            periodo=periodo,
            filas_leidas=filas_leidas,
            filas_escritas=filas_escritas,
            filas_descartadas=filas_descartadas,
            motivo_descarte="fuera de rubros/whitelist configurados",
        )

        return ResultadoIngesta(
            dataset=dataset,
            periodo=periodo,
            estado="ingerido",
            filas_leidas=filas_leidas,
            filas_escritas=filas_escritas,
            filas_descartadas=filas_descartadas,
            ruta_parquet=ruta_parquet,
        )
