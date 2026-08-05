"""Calibración de ofertas — ÉP-05.

benchmark_precio/precio_para_ganar normalizan a PRECIO UNITARIO: OC y LIC ya
lo traen calculado (precioNeto, MontoUnitarioOferta); COT sólo trae el total
de la línea (MontoTotal), así que se divide por CantidadSolicitada.

precio_para_ganar/criterios_que_deciden requieren contraste ganador vs.
perdedor en el MISMO proceso — sólo existe en LIC y COT (OC es la orden ya
adjudicada, sin perdedores visibles). Pedir canal='oc' en esas dos funciones
es un error de uso, no un caso silencioso.

Toda función reporta su `n` y declara muestra insuficiente bajo el umbral —
regla transversal del proyecto (67% del catálogo propio tiene 1 sola línea
de historial: ninguna conclusión de precio puede apoyarse en eso solo).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from mcp_mercadopublico.lake.columnas import (
    COLUMNA_CANTIDAD,
    COLUMNA_CODIGO_PRODUCTO_ONU,
    COLUMNA_CODIGO_PROCESO,
    COLUMNA_CRITERIO,
    COLUMNA_MONTO_OFERTA,
    COLUMNA_NOMBRE_PROVEEDOR,
    COLUMNA_ORGANISMO,
    COLUMNA_PRECIO_UNITARIO,
    COLUMNA_PROCEDENCIA,
    COLUMNA_PRODUCTO_GENERICO,
    COLUMNA_RUBRO_N1,
    COLUMNA_RUBRO_N2,
    COLUMNA_RUT_PROVEEDOR,
    COLUMNA_SELECCIONADO,
    VALOR_GANADOR,
    a_snake_case,
)

UMBRAL_MUESTRA_MINIMA = 10
CANALES_CON_PERDEDORES = ("lic", "cot")


def _hay_particiones(data_dir: Path, dataset: str) -> bool:
    directorio = data_dir / dataset
    return directorio.exists() and any(directorio.glob("**/*.parquet"))


def _patron(data_dir: Path, dataset: str) -> str:
    return (data_dir / dataset / "**" / "*.parquet").as_posix()


def _expr_precio_unitario(dataset: str) -> str:
    """precio_neto/monto_unitario_oferta ya son unitarios; COT no trae
    precio unitario directo — se deriva de MontoTotal/CantidadSolicitada.

    CAST(... AS DOUBLE) explícito: garantiza que MIN/MEDIAN/PERCENTILE_CONT
    devuelvan float de Python, nunca Decimal — mezclar Decimal con un float
    literal en una resta/división de Python lanza TypeError, y Decimal no
    serializa a JSON por defecto (rompería la respuesta de la tool).
    """
    if dataset in ("oc", "lic"):
        col = a_snake_case(COLUMNA_PRECIO_UNITARIO[dataset])
        return f'CAST("{col}" AS DOUBLE)'
    if dataset == "cot":
        monto_col = a_snake_case(COLUMNA_MONTO_OFERTA["cot"])
        cant_col = a_snake_case(COLUMNA_CANTIDAD["cot"])
        return f'(CAST("{monto_col}" AS DOUBLE) / NULLIF(CAST("{cant_col}" AS DOUBLE), 0))'
    raise ValueError(f"dataset {dataset!r} inválido — usar 'oc', 'lic' o 'cot'")


# --------------------------------------------------------------------------
# HU-5.1 — Benchmark de precios
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkPrecio:
    codigo_onu: str
    n: int
    n_proveedores_distintos: int
    minimo: float | None
    p25: float | None
    mediana: float | None
    p75: float | None
    maximo: float | None
    ganadores: dict | None
    perdedores: dict | None
    muestra_insuficiente: bool


def benchmark_precio(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    codigo_onu: str,
    *,
    canal: str | None = None,
) -> BenchmarkPrecio:
    """Distribución de precio unitario de mercado para un código ONU, en
    CLP, separando ofertas ganadoras de perdedoras.

    OC sólo aporta al lado 'ganador' (dinero efectivamente pagado); LIC/COT
    aportan a ambos lados. Con n < 10, muestra_insuficiente=True — repórtalo
    al usuario antes de sacar conclusiones.
    """
    canales = [canal] if canal else ["oc", "lic", "cot"]
    subconsultas: list[str] = []
    params: list = []

    for ds in canales:
        if ds not in ("oc", "lic", "cot"):
            raise ValueError(f"canal {ds!r} inválido — usar 'oc', 'lic' o 'cot'")
        if not _hay_particiones(data_dir, ds):
            continue

        onu_col = a_snake_case(COLUMNA_CODIGO_PRODUCTO_ONU[ds])
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR[ds])
        precio_expr = _expr_precio_unitario(ds)
        patron = _patron(data_dir, ds)
        condiciones = [
            f'"{onu_col}" = ?', "es_clp = true",
            f"{precio_expr} IS NOT NULL", f"{precio_expr} > 0",
        ]

        if ds == "oc":
            subconsultas.append(
                f"""SELECT {precio_expr} AS precio, UPPER(TRIM("{rut_col}")) AS rut, TRUE AS gano
                    FROM read_parquet('{patron}', union_by_name=true)
                    WHERE {' AND '.join(condiciones)}"""
            )
            params.append(codigo_onu)
        else:
            sel_col = a_snake_case(COLUMNA_SELECCIONADO[ds])
            subconsultas.append(
                f"""SELECT {precio_expr} AS precio, UPPER(TRIM("{rut_col}")) AS rut,
                           (LOWER(TRIM("{sel_col}")) = ?) AS gano
                    FROM read_parquet('{patron}', union_by_name=true)
                    WHERE {' AND '.join(condiciones)}"""
            )
            params.extend([VALOR_GANADOR[ds], codigo_onu])

    if not subconsultas:
        return BenchmarkPrecio(
            codigo_onu=codigo_onu, n=0, n_proveedores_distintos=0,
            minimo=None, p25=None, mediana=None, p75=None, maximo=None,
            ganadores=None, perdedores=None, muestra_insuficiente=True,
        )

    query = f"""
        WITH combinado AS ({' UNION ALL '.join(subconsultas)})
        SELECT
            COUNT(*), COUNT(DISTINCT rut),
            MIN(precio), PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY precio),
            MEDIAN(precio), PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY precio),
            MAX(precio),
            COUNT(*) FILTER (WHERE gano), MIN(precio) FILTER (WHERE gano),
            MEDIAN(precio) FILTER (WHERE gano), MAX(precio) FILTER (WHERE gano),
            COUNT(*) FILTER (WHERE NOT gano), MIN(precio) FILTER (WHERE NOT gano),
            MEDIAN(precio) FILTER (WHERE NOT gano), MAX(precio) FILTER (WHERE NOT gano)
        FROM combinado
    """
    (
        n, n_prov, minimo, p25, mediana, p75, maximo,
        n_gan, min_gan, med_gan, max_gan,
        n_perd, min_perd, med_perd, max_perd,
    ) = con.execute(query, params).fetchone()

    def _bloque(n_, mn, md, mx):
        return {"n": n_, "minimo": mn, "mediana": md, "maximo": mx} if n_ else None

    return BenchmarkPrecio(
        codigo_onu=codigo_onu,
        n=n or 0,
        n_proveedores_distintos=n_prov or 0,
        minimo=minimo, p25=p25, mediana=mediana, p75=p75, maximo=maximo,
        ganadores=_bloque(n_gan, min_gan, med_gan, max_gan),
        perdedores=_bloque(n_perd, min_perd, med_perd, max_perd),
        muestra_insuficiente=(n or 0) < UMBRAL_MUESTRA_MINIMA,
    )


# --------------------------------------------------------------------------
# HU-5.2 — Precio para ganar
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PrecioParaGanar:
    codigo_onu: str
    n: int
    umbral_observado: float | None
    precio_ganador_mas_caro: float | None
    precio_perdedor_mas_barato: float | None
    procesos_con_ganador: int
    veces_gano_sin_ser_el_mas_barato: int
    por_organismo: list[dict] = field(default_factory=list)


def precio_para_ganar(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    codigo_onu: str,
    *,
    organismo: str | None = None,
    canal: str | None = None,
) -> PrecioParaGanar:
    """Umbral de precio observado para ganar, a partir de casos históricos.

    Requiere LIC o COT — nunca 'oc' (no tiene ofertas perdedoras contra qué
    comparar). Cuando el ganador NO fue el más barato del proceso, cuenta
    esos casos explícitamente: el precio no es el único criterio (ver
    criterios_que_deciden) y esta función no debe leerse como "bajar el
    precio garantiza ganar".
    """
    canales = [canal] if canal else list(CANALES_CON_PERDEDORES)
    for c in canales:
        if c not in CANALES_CON_PERDEDORES:
            raise ValueError(
                f"canal {c!r} inválido para precio_para_ganar — usar 'lic' o 'cot' "
                "('oc' es la orden ya adjudicada, sin ofertas perdedoras)"
            )

    filas: list[tuple] = []
    for ds in canales:
        if not _hay_particiones(data_dir, ds):
            continue
        onu_col = a_snake_case(COLUMNA_CODIGO_PRODUCTO_ONU[ds])
        proceso_col = a_snake_case(COLUMNA_CODIGO_PROCESO[ds])
        organismo_col = a_snake_case(COLUMNA_ORGANISMO[ds])
        sel_col = a_snake_case(COLUMNA_SELECCIONADO[ds])
        precio_expr = _expr_precio_unitario(ds)
        patron = _patron(data_dir, ds)

        condiciones = [
            f'"{onu_col}" = ?', "es_clp = true",
            f"{precio_expr} IS NOT NULL", f"{precio_expr} > 0",
        ]
        params = [codigo_onu]
        if organismo:
            condiciones.append(f'UPPER("{organismo_col}") = UPPER(?)')
            params.append(organismo)

        query = f"""
            SELECT "{proceso_col}", "{organismo_col}", {precio_expr},
                   (LOWER(TRIM("{sel_col}")) = ?)
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE {' AND '.join(condiciones)}
        """
        filas.extend(con.execute(query, [VALOR_GANADOR[ds]] + params).fetchall())

    if not filas:
        return PrecioParaGanar(
            codigo_onu=codigo_onu, n=0, umbral_observado=None,
            precio_ganador_mas_caro=None, precio_perdedor_mas_barato=None,
            procesos_con_ganador=0, veces_gano_sin_ser_el_mas_barato=0,
        )

    precios_ganadores = sorted(p for _, _, p, g in filas if g)
    precios_perdedores = sorted(p for _, _, p, g in filas if not g)

    por_proceso: dict[str, list[tuple]] = defaultdict(list)
    for proceso, organismo_, precio, gano in filas:
        por_proceso[proceso].append((organismo_, precio, gano))

    procesos_con_ganador = 0
    veces_gano_sin_ser_mas_barato = 0
    por_organismo_raw: dict[str, list[float]] = defaultdict(list)
    for proceso, ofertas in por_proceso.items():
        precios_del_proceso = [p for _, p, _ in ofertas]
        ganadoras = [p for _, p, g in ofertas if g]
        if not ganadoras:
            continue
        procesos_con_ganador += 1
        precio_ganador = min(ganadoras)
        if precio_ganador > min(precios_del_proceso):
            veces_gano_sin_ser_mas_barato += 1
        organismo_proceso = ofertas[0][0]
        por_organismo_raw[organismo_proceso or "(sin organismo)"].append(precio_ganador)

    por_organismo = []
    for org, precios_org in por_organismo_raw.items():
        if len(precios_org) < 3:
            continue  # muy pocos datos de ESE organismo para reportarlo aparte
        precios_org_ordenados = sorted(precios_org)
        por_organismo.append(
            {
                "organismo": org,
                "n_ganadores": len(precios_org),
                "umbral_observado": precios_org_ordenados[len(precios_org_ordenados) // 2],
            }
        )
    por_organismo.sort(key=lambda o: -o["n_ganadores"])

    return PrecioParaGanar(
        codigo_onu=codigo_onu,
        n=len(filas),
        umbral_observado=(
            precios_ganadores[len(precios_ganadores) // 2] if precios_ganadores else None
        ),
        precio_ganador_mas_caro=(precios_ganadores[-1] if precios_ganadores else None),
        precio_perdedor_mas_barato=(precios_perdedores[0] if precios_perdedores else None),
        procesos_con_ganador=procesos_con_ganador,
        veces_gano_sin_ser_el_mas_barato=veces_gano_sin_ser_mas_barato,
        por_organismo=por_organismo,
    )


# --------------------------------------------------------------------------
# HU-5.3 — Criterios que deciden
# --------------------------------------------------------------------------

_PALABRAS_CLAVE_CRITERIO: dict[str, list[str]] = {
    "precio": ["precio", "económic", "menor valor", "oferta econ"],
    "plazo_entrega": ["plazo de entrega", "plazo", "tiempo de entrega"],
    "experiencia": ["experiencia"],
    "canje_garantia": ["canje", "garantía", "garantia"],
    "cumplimiento_formal": ["cumplimiento", "requisitos formales", "formal"],
    "integridad": ["integridad"],
}


def _clasificar_criterio(texto: str) -> str:
    texto_bajo = texto.lower()
    for categoria, palabras in _PALABRAS_CLAVE_CRITERIO.items():
        if any(p in texto_bajo for p in palabras):
            return categoria
    return "otro"


@dataclass(frozen=True)
class CriteriosDecision:
    n_procesos_ganadores: int
    frecuencias: list[dict] = field(default_factory=list)


def criterios_que_deciden(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    *,
    codigo_onu: str | None = None,
    rubro_n1: str | None = None,
    canal: str | None = None,
) -> CriteriosDecision:
    """Por qué se gana: clasifica el criterio declarado de las ofertas
    ganadoras y cuantifica, por categoría, cuánto más caro pudo ser el
    ganador respecto al oferente más barato del mismo proceso.

    Fuentes: NombreCriterio (COT, un motivo por cotización ganada) y
    CriteriosEvaluacion (LIC, lista `;`-separada dentro de un campo
    entrecomillado — P12: el parser CSV ya resolvió esto en el ETL, aquí
    sólo se separa el texto ya limpio). Un proceso con criterios combinados
    ("precio; plazo de entrega") aporta su prima de precio a AMBAS
    categorías — es una simplificación deliberada, no atribución exacta.

    `rubro_n1` sólo filtra LIC (COT no tiene columna de rubro — ver
    columnas.py); si se pasa y el canal es 'cot', ese canal se incluye sin
    filtrar por rubro, no se descarta.
    """
    canales = [canal] if canal else list(CANALES_CON_PERDEDORES)
    for c in canales:
        if c not in CANALES_CON_PERDEDORES:
            raise ValueError(f"canal {c!r} inválido — usar 'lic' o 'cot'")

    conteo: Counter[str] = Counter()
    ejemplos: dict[str, list[str]] = defaultdict(list)
    primas: dict[str, list[float]] = defaultdict(list)
    n_procesos = 0

    for ds in canales:
        if not _hay_particiones(data_dir, ds):
            continue
        proceso_col = a_snake_case(COLUMNA_CODIGO_PROCESO[ds])
        criterio_col = a_snake_case(COLUMNA_CRITERIO[ds])
        onu_col = a_snake_case(COLUMNA_CODIGO_PRODUCTO_ONU[ds])
        sel_col = a_snake_case(COLUMNA_SELECCIONADO[ds])
        precio_expr = _expr_precio_unitario(ds)
        patron = _patron(data_dir, ds)

        condiciones = [
            f'LOWER(TRIM("{sel_col}")) = ?', f'"{criterio_col}" IS NOT NULL',
            "es_clp = true",
        ]
        params: list = [VALOR_GANADOR[ds]]
        if codigo_onu:
            condiciones.append(f'"{onu_col}" = ?')
            params.append(codigo_onu)
        if rubro_n1 and ds == "lic":
            rubro_col = a_snake_case(COLUMNA_RUBRO_N1["lic"])
            condiciones.append(f'UPPER("{rubro_col}") = UPPER(?)')
            params.append(rubro_n1)

        query_ganadores = f"""
            SELECT "{proceso_col}", "{criterio_col}", {precio_expr}
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE {' AND '.join(condiciones)}
        """
        ganadores = con.execute(query_ganadores, params).fetchall()
        if not ganadores:
            continue

        procesos = [g[0] for g in ganadores]
        query_minimos = f"""
            SELECT "{proceso_col}", MIN({precio_expr})
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE "{proceso_col}" = ANY(?) AND {precio_expr} IS NOT NULL AND {precio_expr} > 0
              AND es_clp = true
            GROUP BY 1
        """
        minimos = dict(con.execute(query_minimos, [procesos]).fetchall())

        for proceso, texto_criterio, precio_ganador in ganadores:
            if not texto_criterio:
                continue
            n_procesos += 1
            partes = (
                [p.strip() for p in texto_criterio.split(";") if p.strip()]
                if ds == "lic"
                else [texto_criterio.strip()]
            )
            precio_minimo = minimos.get(proceso)
            prima = None
            if precio_minimo and precio_ganador and precio_minimo > 0:
                prima = (precio_ganador - precio_minimo) / precio_minimo

            categorias_vistas = set()
            for parte in partes:
                categoria = _clasificar_criterio(parte)
                categorias_vistas.add(categoria)
                conteo[categoria] += 1
                if len(ejemplos[categoria]) < 3:
                    ejemplos[categoria].append(parte)
            for categoria in categorias_vistas:
                if prima is not None:
                    primas[categoria].append(prima)

    frecuencias = []
    for categoria, n in conteo.most_common():
        primas_cat = primas.get(categoria, [])
        frecuencias.append(
            {
                "categoria": categoria,
                "n": n,
                "ejemplos": ejemplos[categoria],
                "prima_precio_mediana_pct": (
                    round(sorted(primas_cat)[len(primas_cat) // 2], 4) if primas_cat else None
                ),
            }
        )

    return CriteriosDecision(n_procesos_ganadores=n_procesos, frecuencias=frecuencias)


# --------------------------------------------------------------------------
# HU-5.4 — Post-mortem de un proceso específico
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OfertaEnProceso:
    rut: str
    nombre: str | None
    producto: str | None
    precio: float | None
    seleccionado: bool
    criterio: str | None


@dataclass(frozen=True)
class Postmortem:
    codigo_proceso: str
    canal: str | None
    ofertas: list[OfertaEnProceso] = field(default_factory=list)
    ganador_rut: str | None = None
    nuestra_posicion: dict | None = None


def postmortem(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    codigo_proceso: str,
    *,
    rut_propio: str | None = None,
) -> Postmortem:
    """Reconstruye un proceso (licitación o cotización) específico: todas
    las ofertas, quién ganó, el criterio declarado, y — si se pasa
    rut_propio — nuestra posición relativa frente al ganador."""
    for ds in CANALES_CON_PERDEDORES:
        if not _hay_particiones(data_dir, ds):
            continue

        proceso_col = a_snake_case(COLUMNA_CODIGO_PROCESO[ds])
        rut_col = a_snake_case(COLUMNA_RUT_PROVEEDOR[ds])
        nombre_col = a_snake_case(COLUMNA_NOMBRE_PROVEEDOR[ds])
        producto_col = a_snake_case(COLUMNA_PRODUCTO_GENERICO[ds])
        monto_col = a_snake_case(COLUMNA_MONTO_OFERTA[ds])
        sel_col = a_snake_case(COLUMNA_SELECCIONADO[ds])
        criterio_col = a_snake_case(COLUMNA_CRITERIO[ds])
        patron = _patron(data_dir, ds)

        query = f"""
            SELECT "{rut_col}", "{nombre_col}", "{producto_col}", "{monto_col}",
                   "{sel_col}", "{criterio_col}"
            FROM read_parquet('{patron}', union_by_name=true)
            WHERE "{proceso_col}" = ?
        """
        filas = con.execute(query, [codigo_proceso]).fetchall()
        if not filas:
            continue

        ofertas: list[OfertaEnProceso] = []
        ganador_rut: str | None = None
        for rut, nombre, producto, monto, sel, criterio in filas:
            rut_norm = (rut or "").strip().upper()
            gano = (sel or "").strip().lower() == VALOR_GANADOR[ds]
            if gano:
                ganador_rut = rut_norm
            # float() explícito: el monto viene directo de la columna (no
            # pasa por _expr_precio_unitario), podría llegar como Decimal.
            ofertas.append(
                OfertaEnProceso(
                    rut=rut_norm, nombre=nombre, producto=producto,
                    precio=(float(monto) if monto is not None else None),
                    seleccionado=gano, criterio=criterio,
                )
            )

        nuestra_posicion = None
        if rut_propio:
            rut_propio_norm = rut_propio.strip().upper()
            nuestra = next((o for o in ofertas if o.rut == rut_propio_norm), None)
            if nuestra is None:
                nuestra_posicion = {"participamos": False}
            else:
                ganador = next((o for o in ofertas if o.seleccionado), None)
                diferencia_pct = None
                if ganador and nuestra.precio and ganador.precio:
                    diferencia_pct = round((nuestra.precio - ganador.precio) / ganador.precio, 4)
                nuestra_posicion = {
                    "participamos": True,
                    "seleccionado": nuestra.seleccionado,
                    "precio": nuestra.precio,
                    "diferencia_vs_ganador_pct": diferencia_pct,
                }

        return Postmortem(
            codigo_proceso=codigo_proceso, canal=ds, ofertas=ofertas,
            ganador_rut=ganador_rut, nuestra_posicion=nuestra_posicion,
        )

    return Postmortem(codigo_proceso=codigo_proceso, canal=None)


# --------------------------------------------------------------------------
# HU-5.4 — Perfil de comprador
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PerfilComprador:
    organismo: str
    n_lineas: int
    mix_canal: list[dict] = field(default_factory=list)
    top_rubros: list[dict] = field(default_factory=list)
    top_productos: list[dict] = field(default_factory=list)
    top_proveedores: list[dict] = field(default_factory=list)
    estacionalidad: list[dict] = field(default_factory=list)


def perfil_comprador(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    organismo: str,
    *,
    top_n: int = 5,
) -> PerfilComprador:
    """Qué compra un organismo, a quién, por qué canal (compra ágil vs.
    licitación) y con qué estacionalidad mensual — desde OC (dinero
    efectivamente transado)."""
    if not _hay_particiones(data_dir, "oc"):
        return PerfilComprador(organismo=organismo, n_lineas=0)

    organismo_col = a_snake_case(COLUMNA_ORGANISMO["oc"])
    rubro_col = a_snake_case(COLUMNA_RUBRO_N2["oc"])
    producto_col = a_snake_case(COLUMNA_PRODUCTO_GENERICO["oc"])
    proveedor_col = a_snake_case(COLUMNA_NOMBRE_PROVEEDOR["oc"])
    procedencia_col = a_snake_case(COLUMNA_PROCEDENCIA["oc"])
    patron = _patron(data_dir, "oc")
    condicion = f'UPPER("{organismo_col}") = UPPER(?)'
    params = [organismo]

    (n_lineas,) = con.execute(
        f'SELECT COUNT(*) FROM read_parquet(\'{patron}\', union_by_name=true) WHERE {condicion}',
        params,
    ).fetchone()
    if not n_lineas:
        return PerfilComprador(organismo=organismo, n_lineas=0)

    mix_canal = [
        {"canal": (c if c and c != "NA" else "Compra ágil / trato directo"), "monto": m or 0.0, "n": n}
        for c, m, n in con.execute(
            f"""SELECT "{procedencia_col}", SUM(total_linea_neto) FILTER (WHERE es_clp), COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true) WHERE {condicion}
                GROUP BY 1 ORDER BY 3 DESC""",
            params,
        ).fetchall()
    ]

    top_rubros = [
        {"rubro": r, "monto": m or 0.0, "n": n}
        for r, m, n in con.execute(
            f"""SELECT "{rubro_col}", SUM(total_linea_neto) FILTER (WHERE es_clp), COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true) WHERE {condicion}
                GROUP BY 1 ORDER BY 3 DESC LIMIT {int(top_n)}""",
            params,
        ).fetchall()
    ]

    top_productos = [
        {"producto": p, "n": n}
        for p, n in con.execute(
            f"""SELECT "{producto_col}", COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true) WHERE {condicion}
                GROUP BY 1 ORDER BY 2 DESC LIMIT {int(top_n)}""",
            params,
        ).fetchall()
    ]

    top_proveedores = [
        {"proveedor": p, "monto": m or 0.0, "n": n}
        for p, m, n in con.execute(
            f"""SELECT "{proveedor_col}", SUM(total_linea_neto) FILTER (WHERE es_clp), COUNT(*)
                FROM read_parquet('{patron}', union_by_name=true) WHERE {condicion}
                GROUP BY 1 ORDER BY 3 DESC LIMIT {int(top_n)}""",
            params,
        ).fetchall()
    ]

    estacionalidad = [
        {"mes": mes, "n": n, "monto": m or 0.0}
        for mes, n, m in con.execute(
            f"""SELECT mes, COUNT(*), SUM(total_linea_neto) FILTER (WHERE es_clp)
                FROM read_parquet('{patron}', union_by_name=true) WHERE {condicion}
                GROUP BY mes ORDER BY mes""",
            params,
        ).fetchall()
    ]

    return PerfilComprador(
        organismo=organismo,
        n_lineas=n_lineas,
        mix_canal=mix_canal,
        top_rubros=top_rubros,
        top_productos=top_productos,
        top_proveedores=top_proveedores,
        estacionalidad=estacionalidad,
    )
