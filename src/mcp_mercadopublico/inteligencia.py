"""Inteligencia competitiva — ÉP-04.

descubrir_rivales() y head_to_head() operan sobre LIC y COT (múltiples
ofertantes por proceso) — OC es la orden YA adjudicada, un solo proveedor
por fila, no expone contra quién se compitió. perfil_competidor() y
radar_competencia() usan OC para el monto real transado (dinero
efectivamente pagado, es_clp=true) y LIC/COT para la tasa de éxito.

Regla transversal (backlog §ÉP-04): market-centric. Estas funciones agregan
sobre TODO el mercado en el lake — nunca asumen que el historial de un solo
RUT (propio o rival) alcanza por sí solo. Por eso toda salida trae su `n`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from mcp_mercadopublico.lake.columnas import (
    COLUMNA_CODIGO_PROCESO,
    COLUMNA_CRITERIO,
    COLUMNA_MONTO_OFERTA,
    COLUMNA_NOMBRE_PROVEEDOR,
    COLUMNA_ORGANISMO,
    COLUMNA_PRODUCTO_GENERICO,
    COLUMNA_RUBRO_N1,
    COLUMNA_RUBRO_N2,
    COLUMNA_RUT_PROVEEDOR,
    COLUMNA_SELECCIONADO,
    COLUMNA_TAMANO,
    VALOR_GANADOR,
    a_snake_case,
)

CANALES_RIVALES = ("lic", "cot")


def _rut_comparable(rut: str) -> str:
    return rut.strip().upper()


def _hay_particiones(data_dir: Path, dataset: str) -> bool:
    directorio = data_dir / dataset
    return directorio.exists() and any(directorio.glob("**/*.parquet"))


def _patron(data_dir: Path, dataset: str) -> str:
    return (data_dir / dataset / "**" / "*.parquet").as_posix()


# --------------------------------------------------------------------------
# HU-4.1 — Descubrimiento de rivales por co-participación
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RivalDescubierto:
    rut: str
    nombre: str | None
    canal: str
    n_cruces: int
    en_watchlist: bool


def descubrir_rivales(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    rut_propio: str,
    *,
    canal: str | None = None,
    ruts_watchlist: set[str] | None = None,
    limite: int = 30,
) -> list[RivalDescubierto]:
    """Rivales descubiertos por co-participación: mismo proceso (licitación
    o cotización) en el que Bioquimica.cl ofertó/cotizó y aparece otro RUT.

    No usa OC — ver el docstring del módulo. La watchlist manual es
    complementaria: esta función es la fuente de verdad sobre quién compite.
    """
    rut_norm = _rut_comparable(rut_propio)
    watchlist_norm = {_rut_comparable(r) for r in (ruts_watchlist or set())}
    canales = [canal] if canal else list(CANALES_RIVALES)

    resultados: list[RivalDescubierto] = []
    for ds in canales:
        if ds not in CANALES_RIVALES:
            raise ValueError(f"canal {ds!r} inválido — usar 'lic' o 'cot'")
        if not _hay_particiones(data_dir, ds):
            continue

        proceso_col = a_snake_case(COLUMNA_CODIGO_PROCESO[ds])
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR[ds])
        nombre_col = a_snake_case(COLUMNA_NOMBRE_PROVEEDOR[ds])
        patron = _patron(data_dir, ds)

        query = f"""
            SELECT UPPER(TRIM(t."{rut_col}")) AS rut,
                   ANY_VALUE(t."{nombre_col}") AS nombre,
                   COUNT(*) AS n
            FROM read_parquet('{patron}', union_by_name=true) AS t
            WHERE t."{proceso_col}" IN (
                SELECT DISTINCT "{proceso_col}"
                FROM read_parquet('{patron}', union_by_name=true)
                WHERE UPPER(TRIM("{rut_col}")) = ?
            )
            AND UPPER(TRIM(t."{rut_col}")) != ?
            AND t."{rut_col}" IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC
            LIMIT {int(limite)}
        """
        for rut, nombre, n in con.execute(query, [rut_norm, rut_norm]).fetchall():
            resultados.append(
                RivalDescubierto(
                    rut=rut, nombre=nombre, canal=ds, n_cruces=n,
                    en_watchlist=rut in watchlist_norm,
                )
            )

    resultados.sort(key=lambda r: r.n_cruces, reverse=True)
    return resultados[:limite]


# --------------------------------------------------------------------------
# HU-4.2 — Perfil de competidor
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PerfilCompetidor:
    rut: str
    nombre: str | None
    liga: str | None
    monto_total_clp: float
    n_lineas: int
    ticket_promedio: float | None
    evolucion_mensual: list[dict] = field(default_factory=list)
    top_organismos: list[dict] = field(default_factory=list)
    top_rubros: list[dict] = field(default_factory=list)
    top_productos: list[dict] = field(default_factory=list)
    win_rate: dict | None = None
    tamano_empresa: str | None = None


def perfil_competidor(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    rut: str,
    *,
    liga_a: set[str] | None = None,
    liga_b: set[str] | None = None,
    top_n: int = 5,
) -> PerfilCompetidor:
    """Perfil de un competidor: volumen y monto real transado (de OC, en
    CLP), evolución mensual, top organismos/rubros/productos, tasa de éxito
    (de LIC+COT) y tamaño de empresa (sólo disponible vía COT).

    `liga` compara contra las listas de la watchlist (config/identidad.toml)
    para advertir cuando el competidor no es comparable en escala con el
    catálogo de Bioquímica (liga A: instrumental de alto ticket a hospitales;
    liga B: suministros a universidades, la competencia real).
    """
    rut_norm = _rut_comparable(rut)
    liga_a_norm = {_rut_comparable(r) for r in (liga_a or set())}
    liga_b_norm = {_rut_comparable(r) for r in (liga_b or set())}
    liga = "A" if rut_norm in liga_a_norm else ("B" if rut_norm in liga_b_norm else None)

    nombre: str | None = None
    monto_total = 0.0
    n_lineas = 0
    evolucion: list[dict] = []
    top_organismos: list[dict] = []
    top_rubros: list[dict] = []
    top_productos: list[dict] = []

    if _hay_particiones(data_dir, "oc"):
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR["oc"])
        nombre_col = a_snake_case(COLUMNA_NOMBRE_PROVEEDOR["oc"])
        organismo_col = a_snake_case(COLUMNA_ORGANISMO["oc"])
        rubro_col = a_snake_case(COLUMNA_RUBRO_N2["oc"])
        producto_col = a_snake_case(COLUMNA_PRODUCTO_GENERICO["oc"])
        patron = _patron(data_dir, "oc")

        fila = con.execute(
            f"""
            SELECT ANY_VALUE("{nombre_col}"), SUM(total_linea_neto), COUNT(*)
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE UPPER(TRIM("{rut_col}")) = ? AND es_clp = true
            """,
            [rut_norm],
        ).fetchone()
        if fila and fila[2]:
            nombre, monto_total, n_lineas = fila[0], (fila[1] or 0.0), fila[2]

        evolucion = [
            {"periodo": f"{a}-{m}", "monto": mo or 0.0, "n": n}
            for a, m, mo, n in con.execute(
                f"""
                SELECT anio, mes, SUM(total_linea_neto), COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true)
                WHERE UPPER(TRIM("{rut_col}")) = ? AND es_clp = true
                GROUP BY anio, mes ORDER BY anio, mes
                """,
                [rut_norm],
            ).fetchall()
        ]

        top_organismos = [
            {"organismo": o, "monto": mo or 0.0, "n": n}
            for o, mo, n in con.execute(
                f"""
                SELECT "{organismo_col}", SUM(total_linea_neto), COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true)
                WHERE UPPER(TRIM("{rut_col}")) = ? AND es_clp = true
                GROUP BY 1 ORDER BY 2 DESC LIMIT {int(top_n)}
                """,
                [rut_norm],
            ).fetchall()
        ]

        top_rubros = [
            {"rubro": r, "monto": mo or 0.0, "n": n}
            for r, mo, n in con.execute(
                f"""
                SELECT "{rubro_col}", SUM(total_linea_neto), COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true)
                WHERE UPPER(TRIM("{rut_col}")) = ? AND es_clp = true
                GROUP BY 1 ORDER BY 2 DESC LIMIT {int(top_n)}
                """,
                [rut_norm],
            ).fetchall()
        ]

        top_productos = [
            {"producto": p, "n": n}
            for p, n in con.execute(
                f"""
                SELECT "{producto_col}", COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true)
                WHERE UPPER(TRIM("{rut_col}")) = ?
                GROUP BY 1 ORDER BY 2 DESC LIMIT {int(top_n)}
                """,
                [rut_norm],
            ).fetchall()
        ]

    ganadas_total = 0
    ofertas_total = 0
    tamano_empresa: str | None = None
    for ds in CANALES_RIVALES:
        if not _hay_particiones(data_dir, ds):
            continue
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR[ds])
        sel_col = a_snake_case(COLUMNA_SELECCIONADO[ds])
        patron = _patron(data_dir, ds)

        fila = con.execute(
            f"""
            SELECT COUNT(*) FILTER (WHERE LOWER(TRIM("{sel_col}")) = ?), COUNT(*)
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE UPPER(TRIM("{rut_col}")) = ?
            """,
            [VALOR_GANADOR[ds], rut_norm],
        ).fetchone()
        ganadas_total += fila[0] or 0
        ofertas_total += fila[1] or 0
        if nombre is None and (fila[1] or 0) > 0:
            nombre_col = a_snake_case(COLUMNA_NOMBRE_PROVEEDOR[ds])
            f_nombre = con.execute(
                f'SELECT ANY_VALUE("{nombre_col}") FROM read_parquet(\'{patron}\', union_by_name=true) '
                f'WHERE UPPER(TRIM("{rut_col}")) = ?',
                [rut_norm],
            ).fetchone()
            nombre = f_nombre[0] if f_nombre else nombre

        if ds == "cot":
            tam_col = a_snake_case(COLUMNA_TAMANO["cot"])
            f_tam = con.execute(
                f'SELECT ANY_VALUE("{tam_col}") FROM read_parquet(\'{patron}\', union_by_name=true) '
                f'WHERE UPPER(TRIM("{rut_col}")) = ? AND "{tam_col}" IS NOT NULL',
                [rut_norm],
            ).fetchone()
            tamano_empresa = f_tam[0] if f_tam else None

    win_rate = None
    if ofertas_total > 0:
        win_rate = {
            "ganadas": ganadas_total,
            "ofertadas": ofertas_total,
            "tasa": round(ganadas_total / ofertas_total, 3),
        }

    return PerfilCompetidor(
        rut=rut,
        nombre=nombre,
        liga=liga,
        monto_total_clp=monto_total,
        n_lineas=n_lineas,
        ticket_promedio=(monto_total / n_lineas) if n_lineas else None,
        evolucion_mensual=evolucion,
        top_organismos=top_organismos,
        top_rubros=top_rubros,
        top_productos=top_productos,
        win_rate=win_rate,
        tamano_empresa=tamano_empresa,
    )


# --------------------------------------------------------------------------
# HU-4.3 — Radar de movimiento
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MovimientoCompetidor:
    rut: str
    nombre: str | None
    monto_periodo_actual: float
    monto_periodo_anterior: float
    delta_monto: float
    delta_pct: float | None
    n_periodo_actual: int
    n_periodo_anterior: int
    es_entrante: bool
    es_saliente: bool


def radar_competencia(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    *,
    anio: int,
    mes: int,
    anio_comparar: int,
    mes_comparar: int,
    rubro_n1: str | None = None,
    limite: int = 20,
) -> list[MovimientoCompetidor]:
    """Compara el monto de OC por proveedor entre dos periodos puntuales.

    Usa OC (dinero efectivamente transado, es_clp=true), no LIC/COT — el
    radar mide quién factura más o menos, no quién oferta más o menos.
    Ordena por magnitud absoluta del cambio, no por tamaño: un entrante
    chico que triplica importa más que un grande estable.
    """
    if not _hay_particiones(data_dir, "oc"):
        return []

    rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR["oc"])
    nombre_col = a_snake_case(COLUMNA_NOMBRE_PROVEEDOR["oc"])
    patron = _patron(data_dir, "oc")

    condicion_rubro = ""
    params_rubro: list[str] = []
    if rubro_n1:
        rubro_col = a_snake_case(COLUMNA_RUBRO_N1["oc"])
        condicion_rubro = f' AND UPPER("{rubro_col}") = UPPER(?)'
        params_rubro = [rubro_n1]

    def _montos_por_rut(a: int, m: int) -> dict[str, tuple]:
        query = f"""
            SELECT UPPER(TRIM("{rut_col}")) AS rut, ANY_VALUE("{nombre_col}") AS nombre,
                   SUM(total_linea_neto) AS monto, COUNT(*) AS n
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE anio = ? AND mes = ? AND es_clp = true {condicion_rubro}
              AND "{rut_col}" IS NOT NULL
            GROUP BY 1
        """
        filas = con.execute(query, [a, m] + params_rubro).fetchall()
        return {rut: (nombre, monto or 0.0, n) for rut, nombre, monto, n in filas}

    actual = _montos_por_rut(anio, mes)
    anterior = _montos_por_rut(anio_comparar, mes_comparar)

    movimientos: list[MovimientoCompetidor] = []
    for rut in set(actual) | set(anterior):
        nombre_a, monto_a, n_a = actual.get(rut, (None, 0.0, 0))
        nombre_p, monto_p, n_p = anterior.get(rut, (None, 0.0, 0))
        delta = monto_a - monto_p
        delta_pct = round(delta / monto_p, 4) if monto_p else None
        movimientos.append(
            MovimientoCompetidor(
                rut=rut,
                nombre=nombre_a or nombre_p,
                monto_periodo_actual=monto_a,
                monto_periodo_anterior=monto_p,
                delta_monto=delta,
                delta_pct=delta_pct,
                n_periodo_actual=n_a,
                n_periodo_anterior=n_p,
                es_entrante=(n_p == 0 and n_a > 0),
                es_saliente=(n_a == 0 and n_p > 0),
            )
        )

    movimientos.sort(key=lambda m: abs(m.delta_monto), reverse=True)
    return movimientos[:limite]


# --------------------------------------------------------------------------
# HU-4.4 — Head-to-head contra un competidor
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CruceHeadToHead:
    canal: str
    codigo_proceso: str
    producto: str | None
    nuestro_monto: float | None
    su_monto: float | None
    diferencia_pct: float | None
    ganador: str | None  # "nosotros" | "rival" | "otro"
    criterio: str | None


def head_to_head(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    rut_propio: str,
    rut_rival: str,
    *,
    canal: str | None = None,
) -> list[CruceHeadToHead]:
    """Procesos (licitación/cotización) donde AMBOS RUT participaron,
    comparando precio, ganador y criterio declarado línea por línea."""
    rut_propio_norm = _rut_comparable(rut_propio)
    rut_rival_norm = _rut_comparable(rut_rival)
    canales = [canal] if canal else list(CANALES_RIVALES)

    cruces: list[CruceHeadToHead] = []
    for ds in canales:
        if not _hay_particiones(data_dir, ds):
            continue

        proceso_col = a_snake_case(COLUMNA_CODIGO_PROCESO[ds])
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR[ds])
        producto_col = a_snake_case(COLUMNA_PRODUCTO_GENERICO[ds])
        monto_col = a_snake_case(COLUMNA_MONTO_OFERTA[ds])
        sel_col = a_snake_case(COLUMNA_SELECCIONADO[ds])
        criterio_col = a_snake_case(COLUMNA_CRITERIO[ds])
        patron = _patron(data_dir, ds)

        procesos_query = f"""
            SELECT "{proceso_col}"
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE UPPER(TRIM("{rut_col}")) IN (?, ?)
            GROUP BY 1
            HAVING COUNT(DISTINCT UPPER(TRIM("{rut_col}"))) = 2
        """
        procesos = [r[0] for r in con.execute(procesos_query, [rut_propio_norm, rut_rival_norm]).fetchall()]
        if not procesos:
            continue

        detalle_query = f"""
            SELECT "{proceso_col}", UPPER(TRIM("{rut_col}")), "{producto_col}",
                   "{monto_col}", "{sel_col}", "{criterio_col}"
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE "{proceso_col}" = ANY(?) AND UPPER(TRIM("{rut_col}")) IN (?, ?)
        """
        filas = con.execute(detalle_query, [procesos, rut_propio_norm, rut_rival_norm]).fetchall()

        por_proceso: dict[str, dict] = {}
        for proceso, rut, producto, monto, sel, criterio in filas:
            lado = "nosotros" if rut == rut_propio_norm else "rival"
            # float() explícito: el monto viene directo de la columna, podría
            # llegar como Decimal — mezclarlo con un float de Python en la
            # resta/división de más abajo lanzaría TypeError.
            por_proceso.setdefault(proceso, {})[lado] = {
                "producto": producto,
                "monto": (float(monto) if monto is not None else None),
                "seleccionado": sel,
                "criterio": criterio,
            }

        valor_ganador = VALOR_GANADOR[ds]
        for proceso, datos in por_proceso.items():
            nuestro = datos.get("nosotros")
            rival = datos.get("rival")
            if not nuestro or not rival:
                continue

            nuestro_monto = nuestro["monto"]
            su_monto = rival["monto"]
            diferencia_pct = None
            if nuestro_monto and su_monto:
                diferencia_pct = round((nuestro_monto - su_monto) / su_monto, 4)

            nuestro_gano = (nuestro["seleccionado"] or "").strip().lower() == valor_ganador
            rival_gano = (rival["seleccionado"] or "").strip().lower() == valor_ganador
            ganador = "nosotros" if nuestro_gano else ("rival" if rival_gano else "otro")

            cruces.append(
                CruceHeadToHead(
                    canal=ds,
                    codigo_proceso=proceso,
                    producto=nuestro["producto"] or rival["producto"],
                    nuestro_monto=nuestro_monto,
                    su_monto=su_monto,
                    diferencia_pct=diferencia_pct,
                    ganador=ganador,
                    criterio=nuestro["criterio"] or rival["criterio"],
                )
            )

    # Orden estable y determinístico: sin esto, la paginación por offset en
    # server.py podría solapar o saltarse registros entre llamadas (el orden
    # de por_proceso sigue el scan del parquet, que no está garantizado).
    return sorted(cruces, key=lambda c: (c.canal, c.codigo_proceso))
