"""Servidor MCP — Mercado Público / Bioquimica.cl (HU-1.3).

Transporte HTTP desde el día 1 (D1): claude.ai monta conectores MCP remotos
por HTTP, no stdio local. Correrlo en local durante el desarrollo hace que el
despliegue final (ÉP-07) sea configuración, no reescritura.

Esta tool (`verificar_estado`) es el circuito mínimo de extremo a extremo:
valida que la configuración carga, el logging escribe a archivo y el
protocolo MCP responde. Las tools de negocio (ÉP-03..06) se agregan aquí a
medida que se implementan, sin tocar esta base.
"""

from __future__ import annotations

import logging
import shutil

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_mercadopublico import catalogo, inteligencia, precios
from mcp_mercadopublico.auth import AutenticacionBearerMiddleware
from mcp_mercadopublico.config import get_settings
from mcp_mercadopublico.formato.tsv_xml import filas_a_tsv_xml
from mcp_mercadopublico.lake.etl import ingerir_periodo
from mcp_mercadopublico import limites
from mcp_mercadopublico.scheduler import lifespan_con_ingesta_periodica
from mcp_mercadopublico.lake.manifest import listar_periodos
from mcp_mercadopublico.lake.periodos import generar_periodos
from mcp_mercadopublico.logging_setup import configurar_logging

logger = logging.getLogger(__name__)

INSTRUCCIONES = """\
Servidor de inteligencia competitiva sobre Mercado Público de Chile para
Bioquimica.cl (RUT 76.563.320-6). Data lake histórico de licitaciones,
órdenes de compra y cotizaciones de compra ágil (~20 meses), filtrado a
nuestros rubros y con TODOS los proveedores del mercado, no sólo uno.

Fuerte en: mercado agregado por producto (distribución de precios de
ganadores vs. perdedores), historia profunda de un competidor,
descubrimiento de rivales por co-participación, y la vista desde el
comprador (qué compra un organismo, a quién, por qué canal).

NO hace: leer documentos ni bases de licitación (usar getOpportunityDocument
del conector LicitaLab, que sí las indexa con RAG), ni descubrir
oportunidades nuevas abiertas hoy — ningún conector hace descubrimiento;
decírselo al usuario en vez de responder con datos históricos como si
fueran actuales.

Enfoque: entender a la competencia y calibrar precio/argumento de oferta.
El 76 % del negocio entra por compra ágil, no licitación — priorizar ese
canal salvo que la pregunta sea explícitamente sobre licitaciones. El lake
es histórico: compra ágil con ~1 mes de rezago, licitaciones y órdenes de
compra ~1 día.

Toda agregación de precios reporta su tamaño de muestra (n) y la confianza
de la resolución del producto. Con n bajo o confianza distinta de 'alta',
adviértelo antes de concluir. El precio no es el único criterio de
adjudicación: cruzar con criterios_que_deciden antes de recomendar bajarlo.\
"""

mcp = MCPServer(
    name="mercado-publico-bioquimica",
    instructions=INSTRUCCIONES,
    lifespan=lambda _server: lifespan_con_ingesta_periodica(get_settings),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Healthcheck de Railway (HU-7.3) — sin autenticación por diseño, como
    todo lo registrado vía custom_route(). No expone datos de negocio, sólo
    si el servidor y el lake están en condiciones de responder."""
    settings = get_settings()
    lake_accesible = any(
        (settings.data_dir / ds).exists() and any((settings.data_dir / ds).glob("**/*.parquet"))
        for ds in ("oc", "lic", "cot")
    )
    ultimo_periodo = None
    try:
        registros = listar_periodos(settings.manifest_path)
        if registros:
            ultimo_periodo = max(r.ingerido_en for r in registros)
    except Exception:
        pass  # manifest inexistente todavía (antes de la primera ingesta) no es una falla de salud

    return JSONResponse(
        {
            "servidor": "ok",
            "lake_accesible": lake_accesible,
            "ultima_ingesta": ultimo_periodo,
        }
    )


@mcp.tool()
def verificar_estado() -> dict:
    """Estado de salud y diagnóstico del servidor: configuración, identidad,
    estado real del data lake, del scheduler y del espacio en disco.

    Úsala PRIMERO cuando una tool de análisis devuelva resultados vacíos —
    distingue las tres causas posibles, que se ven iguales desde afuera:
    (a) el lake todavía no tiene datos ingeridos, (b) el scheduler está
    apagado o falló, (c) sí hay datos pero el filtro de la consulta no
    encontró nada. Un resultado vacío NO significa que haya un problema de
    conexión a base de datos: el lake son archivos Parquet locales, no hay
    ninguna base remota a la que conectarse.
    """
    settings = get_settings()
    identidad = settings.identidad

    # Estado real del lake, dataset por dataset — un lake vacío es la causa
    # más común de resultados vacíos y hasta ahora no era visible desde acá.
    lake: dict[str, object] = {}
    for ds in ("oc", "lic", "cot"):
        directorio = settings.data_dir / ds
        particiones = sorted(directorio.glob("**/*.parquet")) if directorio.exists() else []
        lake[ds] = {
            "particiones": len(particiones),
            "periodos": [p.parent.parent.name + "/" + p.parent.name for p in particiones[:5]],
        }

    periodos_manifest: list[dict] = []
    try:
        for r in listar_periodos(settings.manifest_path):
            periodos_manifest.append(
                {
                    "dataset": r.dataset, "periodo": r.periodo, "estado": r.estado,
                    "filas_escritas": r.filas_escritas, "ingerido_en": r.ingerido_en,
                }
            )
    except Exception as exc:  # manifest inexistente antes de la 1ª ingesta
        periodos_manifest = [{"error": f"manifest no legible: {exc}"}]

    espacio: dict[str, object] = {}
    for nombre, ruta in (("data_dir", settings.data_dir), ("scratch_dir", settings.scratch_dir)):
        try:
            ruta.mkdir(parents=True, exist_ok=True)
            uso = shutil.disk_usage(ruta)
            espacio[nombre] = {
                "ruta": str(ruta),
                "total_gb": round(uso.total / 1e9, 2),
                "libre_gb": round(uso.free / 1e9, 2),
            }
        except Exception as exc:
            espacio[nombre] = {"ruta": str(ruta), "error": str(exc)}

    return {
        "servidor": "ok",
        "nosotros": {
            "rut": identidad.nosotros.rut,
            "codigo_proveedor": identidad.nosotros.codigo_proveedor,
            "razon_social_mp": identidad.nosotros.razon_social_mp,
        },
        "ingesta_configurada": {
            "periodo_desde": identidad.ingesta.periodo_desde,
            "periodo_hasta": identidad.ingesta.periodo_hasta,
            "datasets": identidad.ingesta.datasets,
            "rubros_n1": len(identidad.ingesta.rubros_n1),
        },
        "watchlist": {
            "liga_a": len(identidad.competencia.liga_a),
            "liga_b": len(identidad.competencia.liga_b),
        },
        "ticket_api_configurado": settings.tiene_ticket,
        "scheduler": {
            "habilitado": settings.scheduler_habilitado,
            "intervalo_segundos": settings.scheduler_intervalo_segundos,
            "nota": (
                "Si habilitado=false, la ingesta automática NO corre — definir "
                "SCHEDULER_ENABLED=true, o llamar ingerir_datos_abiertos a mano."
            ),
        },
        "lake": lake,
        "periodos_en_manifest": periodos_manifest,
        "espacio_en_disco": espacio,
    }


@mcp.tool()
def ingerir_datos_abiertos(
    dataset: str,
    periodo_desde: str | None = None,
    periodo_hasta: str | None = None,
) -> dict:
    """Descarga e ingiere al data lake los periodos de Datos Abiertos de
    ChileCompra para un dataset ('oc', 'lic' o 'cot').

    Es la única forma de poblar o actualizar el lake — sin llamarla antes,
    las tools de inteligencia competitiva no tienen sobre qué consultar.
    Idempotente: reingerir un periodo ya cargado reemplaza su partición, no
    la duplica. Sólo descarga lo que cambió (por ETag) — reingerir un rango
    completo cuando la mayoría ya está al día es rápido, no vuelve a bajar
    todo.

    IMPORTANTE — orden de ingesta: 'cot' (compra ágil) no tiene columna de
    rubro propia y se filtra por los códigos de producto (ONU/UNSPSC) ya
    vistos en 'oc'/'lic'. Ingerir al menos un periodo de 'oc' o 'lic' ANTES
    de ingerir 'cot', o 'cot' no retendrá ninguna fila.

    Por defecto usa el rango de config/identidad.toml — pasar fechas
    explícitas sólo para reingestas puntuales. Un rango largo puede tardar
    varios minutos: cada periodo implica descargar y procesar hasta ~1,3 GB
    descomprimidos.

    Args:
        dataset: 'oc' (órdenes de compra), 'lic' (licitaciones) o 'cot'
                 (cotizaciones de compra ágil).
        periodo_desde: 'AAAA-M' sin cero-padding (ej. '2025-1'). Por defecto,
                       el configurado en identidad.toml.
        periodo_hasta: 'AAAA-M' sin cero-padding (ej. '2026-8'). Por defecto,
                       el configurado en identidad.toml.
    """
    if dataset not in ("oc", "lic", "cot"):
        return {"error": f"dataset {dataset!r} inválido — usar 'oc', 'lic' o 'cot'"}

    settings = get_settings()
    identidad = settings.identidad

    desde = periodo_desde or identidad.ingesta.periodo_desde
    hasta = periodo_hasta or identidad.ingesta.periodo_hasta

    try:
        periodos = generar_periodos(desde, hasta)
    except ValueError as exc:
        return {"error": str(exc)}

    if len(periodos) > limites.MAX_PERIODOS_POR_INGESTA:
        return {
            "error": (
                f"Rango de {len(periodos)} periodos excede el máximo de "
                f"{limites.MAX_PERIODOS_POR_INGESTA} por llamada (~3 años). "
                "Pedirlo en tandas más chicas — cada periodo descarga y "
                "procesa hasta ~1,3 GB descomprimidos."
            )
        }

    rubros_permitidos = (
        [r.nombre for r in identidad.ingesta.rubros_n1] if dataset in ("oc", "lic") else None
    )

    resultados = []
    for anio, mes in periodos:
        try:
            r = ingerir_periodo(
                dataset,
                anio,
                mes,
                data_dir=settings.data_dir,
                manifest_path=settings.manifest_path,
                scratch_dir=settings.scratch_dir,
                rubros_permitidos=rubros_permitidos,
            )
            resultados.append(
                {
                    "periodo": r.periodo,
                    "estado": r.estado,
                    "filas_leidas": r.filas_leidas,
                    "filas_escritas": r.filas_escritas,
                    "filas_descartadas": r.filas_descartadas,
                }
            )
        except Exception as exc:  # un periodo con error no debe tumbar el resto del rango
            logger.exception(
                "fallo_ingesta_periodo",
                extra={"extra_fields": {"dataset": dataset, "periodo": f"{anio}-{mes}"}},
            )
            resultados.append({"periodo": f"{anio}-{mes}", "estado": "error", "detalle": str(exc)})

    ingeridos = [r for r in resultados if r["estado"] == "ingerido"]
    return {
        "dataset": dataset,
        "rango": f"{desde} a {hasta}",
        "periodos_procesados": len(resultados),
        "periodos_ingeridos": len(ingeridos),
        "filas_totales_escritas": sum(r.get("filas_escritas", 0) for r in ingeridos),
        "detalle": resultados,
    }


@mcp.tool()
def buscar_producto_en_historial(
    texto: str | None = None,
    codigo_onu: str | None = None,
    solo_propio: bool = True,
    limite: int = 20,
) -> dict:
    """Busca en el data lake qué código ONU/UNSPSC quedó asociado a un texto
    de producto, o qué se vendió bajo un código ONU conocido.

    Úsala junto con el conector del catálogo de Bioquímica.cl (otro MCP,
    disponible en la misma conversación) para resolver a qué código ONU
    corresponde un SKU: consulta el catálogo por su nombre/especificación,
    y llama esta tool con ese mismo texto para ver con qué código ONU lo
    clasificaron los compradores del Estado en compras reales. Si confirmas
    el match, persístelo con registrar_mapeo_sku_onu para no repetir el
    cruce la próxima vez.

    Con solo_propio=True (default) busca sólo en lo que Bioquimica.cl mismo
    vendió — alta confianza, sin ambigüedad de a qué producto correspondía.
    Con solo_propio=False amplía a todo el mercado (útil si Bioquímica no ha
    vendido ese producto todavía, pero el mercado sí lo clasifica).

    No hace fuzzy matching automático de SKU a código ONU — esa decisión la
    tomas tú, con el contexto de la conversación y ambos conectores.

    Args:
        texto: fragmento a buscar en el nombre del producto (case-insensitive).
        codigo_onu: código ONU/UNSPSC exacto (8 dígitos) a buscar.
        solo_propio: si True, acota a las ventas de Bioquimica.cl.
        limite: máximo de resultados a devolver.
    """
    settings = get_settings()

    if not catalogo.lake_tiene_datos(settings.data_dir):
        return {
            "resultados": [],
            "nota": (
                "El data lake todavía no tiene datos ingeridos — llamar primero a "
                "ingerir_datos_abiertos. Esto no es un error, es esperado antes de "
                "la primera ingesta."
            ),
        }

    try:
        coincidencias = limites.consultar(
            catalogo.buscar_producto_en_historial,
            settings.data_dir,
            texto=texto,
            codigo_onu=codigo_onu,
            solo_propio=solo_propio,
            rut_propio=settings.identidad.nosotros.rut if solo_propio else None,
            limite=limite,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"error": str(exc)}

    return {
        "resultados": [
            {
                "codigo_onu": c.codigo_onu,
                "texto_producto": c.texto_producto,
                "dataset": c.dataset,
                "n_apariciones": c.n_apariciones,
                "n_vendedores_distintos": c.n_vendedores_distintos,
            }
            for c in coincidencias
        ],
    }


@mcp.tool()
def registrar_mapeo_sku_onu(sku: str, codigo_onu: str, confianza: str, nota: str = "") -> dict:
    """Persiste que un SKU del catálogo de Bioquímica.cl corresponde a un
    código ONU/UNSPSC de Mercado Público.

    Llámala DESPUÉS de confirmar el match cruzando el catálogo (otro
    conector) con buscar_producto_en_historial en la misma conversación —
    no antes. Una vez registrado, resolver_producto() y todas las tools de
    precio (benchmark_precio, precio_para_ganar, etc.) usan este mapeo con
    confianza 'alta' automáticamente, sin que tengas que repetir el cruce.

    Args:
        sku: código del producto en el catálogo de Bioquímica.cl.
        codigo_onu: código ONU/UNSPSC de 8 dígitos confirmado.
        confianza: 'alta' (match exacto de especificación), 'media' (calza
                   pero con alguna diferencia de presentación/formato) o
                   'baja' (mejor candidato disponible, con dudas).
        nota: por qué se confirmó este match — queda en el registro para
              auditoría futura.
    """
    if confianza not in ("alta", "media", "baja"):
        return {"error": f"confianza {confianza!r} inválida — usar 'alta', 'media' o 'baja'"}

    settings = get_settings()
    catalogo.registrar_mapeo_sku_onu(settings.mapeos_path, sku, codigo_onu, confianza, nota)
    return {"registrado": True, "sku": sku, "codigo_onu": codigo_onu, "confianza": confianza}


@mcp.tool()
def resolver_producto(sku_o_texto: str) -> dict:
    """Resuelve un SKU o texto a un código ONU/UNSPSC, con el método y la
    confianza de la resolución explícitos.

    Toda tool que calcule precios de mercado debe resolver el producto con
    esta función primero y reportar su 'metodo'/'confianza' en la
    respuesta — nunca presentar un precio de mercado sin decir qué tan
    segura es la identificación del producto detrás de ese precio.

    Si devuelve confianza 'ninguna' (metodo='sin_resolucion'), significa que
    no hay un mapeo confirmado ni el texto es un código ONU literal — usa
    buscar_producto_en_historial junto con el catálogo para resolverlo y
    registrar_mapeo_sku_onu para que la próxima vez sea inmediato.
    """
    settings = get_settings()
    r = catalogo.resolver_producto(sku_o_texto, settings.mapeos_path)
    return {"codigo_onu": r.codigo_onu, "metodo": r.metodo, "confianza": r.confianza}


@mcp.tool()
def descubrir_rivales(canal: str | None = None, limite: int = 30) -> dict:
    """Encuentra los competidores REALES de Bioquimica.cl por co-participación
    en el mismo proceso (licitación o cotización de compra ágil) — no por una
    lista armada de memoria.

    Es la fuente de verdad sobre quién compite: una watchlist manual falló al
    83-100% contra los rivales reales medidos (ver Backlog §0.3). Úsala en
    vez de asumir que 'la competencia' es la que alguien anotó una vez.

    No incluye órdenes de compra ('oc'): una OC ya adjudicada muestra sólo al
    ganador, no expone contra quién se compitió.

    Args:
        canal: 'lic' (licitaciones), 'cot' (compra ágil) o None (ambos).
        limite: máximo de rivales a devolver, ordenados por nº de cruces.
    """
    settings = get_settings()
    identidad = settings.identidad
    watchlist = set(identidad.competencia.todos_los_rut())

    try:
        rivales = limites.consultar(
            inteligencia.descubrir_rivales,
            settings.data_dir,
            identidad.nosotros.rut,
            canal=canal,
            ruts_watchlist=watchlist,
            limite=limite,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"error": str(exc)}

    return {
        "rivales": [
            {
                "rut": r.rut,
                "nombre": r.nombre,
                "canal": r.canal,
                "n_cruces": r.n_cruces,
                "en_watchlist": r.en_watchlist,
            }
            for r in rivales
        ],
    }


@mcp.tool()
def perfil_competidor(rut: str, top_n: int = 5) -> dict:
    """Perfil de un competidor: monto real transado en CLP (de órdenes de
    compra adjudicadas), evolución mensual, organismos/rubros/productos más
    frecuentes, tasa de éxito en ofertas y tamaño de empresa.

    Reporta 'liga' (A: instrumental de alto ticket a hospitales — NO
    comparable con el catálogo de Bioquímica; B: suministros a
    universidades — la competencia real) cuando el RUT está en la
    watchlist. Compararse en precio contra la liga A produce conclusiones
    falsas: son negocios de escala distinta (94x de diferencia medido).

    Todo número viene con su `n` (n_lineas, ofertadas). Con `n` bajo, la
    cifra es orientativa, no concluyente — adviértelo al usuario.
    """
    settings = get_settings()
    identidad = settings.identidad
    liga_a = {c.rut for c in identidad.competencia.liga_a}
    liga_b = {c.rut for c in identidad.competencia.liga_b}

    try:
        perfil = limites.consultar(
            inteligencia.perfil_competidor,
            settings.data_dir, rut, liga_a=liga_a, liga_b=liga_b, top_n=top_n,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"error": str(exc)}

    return {
        "rut": perfil.rut,
        "nombre": perfil.nombre,
        "liga": perfil.liga,
        "monto_total_clp": perfil.monto_total_clp,
        "n_lineas": perfil.n_lineas,
        "ticket_promedio": perfil.ticket_promedio,
        "evolucion_mensual": perfil.evolucion_mensual,
        "top_organismos": perfil.top_organismos,
        "top_rubros": perfil.top_rubros,
        "top_productos": perfil.top_productos,
        "win_rate": perfil.win_rate,
        "tamano_empresa": perfil.tamano_empresa,
    }


@mcp.tool()
def radar_competencia(
    anio: int,
    mes: int,
    anio_comparar: int,
    mes_comparar: int,
    rubro_n1: str | None = None,
    limite: int = 20,
) -> dict:
    """Qué cambió entre dos periodos: quién entró, quién salió, quién subió
    o bajó su monto de órdenes de compra adjudicadas (dinero real, CLP).

    Ordenado por magnitud ABSOLUTA del cambio, no relativa ni por tamaño —
    un entrante chico que triplica pesa más que un grande estable. Usa esto
    para detectar competidores que están acelerando, no sólo a los grandes
    de siempre.

    Args:
        anio, mes: periodo a evaluar.
        anio_comparar, mes_comparar: periodo contra el que se compara.
        rubro_n1: si se pasa, acota a ese RubroN1 (ver config/identidad.toml
                  para los nombres exactos verificados contra ChileCompra).
        limite: máximo de proveedores a devolver.
    """
    settings = get_settings()
    try:
        movimientos = limites.consultar(
            inteligencia.radar_competencia,
            settings.data_dir,
            anio=anio,
            mes=mes,
            anio_comparar=anio_comparar,
            mes_comparar=mes_comparar,
            rubro_n1=rubro_n1,
            limite=limite,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"error": str(exc)}

    return {
        "periodo_actual": f"{anio}-{mes}",
        "periodo_comparado": f"{anio_comparar}-{mes_comparar}",
        "movimientos": [
            {
                "rut": m.rut,
                "nombre": m.nombre,
                "monto_periodo_actual": m.monto_periodo_actual,
                "monto_periodo_anterior": m.monto_periodo_anterior,
                "delta_monto": m.delta_monto,
                "delta_pct": m.delta_pct,
                "n_periodo_actual": m.n_periodo_actual,
                "n_periodo_anterior": m.n_periodo_anterior,
                "es_entrante": m.es_entrante,
                "es_saliente": m.es_saliente,
            }
            for m in movimientos
        ],
    }


@mcp.tool()
def head_to_head(rut_rival: str, canal: str | None = None) -> dict:
    """Compara a Bioquimica.cl contra un competidor específico, proceso por
    proceso (licitación o cotización) donde AMBOS participaron: producto,
    precio de cada uno, diferencia %, quién ganó y el criterio declarado.

    El resumen incluye cuántos cruces hubo y cuántos ganamos — con pocos
    cruces (n bajo) la comparación es anecdótica, no un patrón. Esta tool lo
    advierte explícitamente para que no se presente como conclusión firme.

    Args:
        rut_rival: RUT del competidor a comparar (formato con puntos y guion).
        canal: 'lic', 'cot' o None (ambos).
    """
    settings = get_settings()
    try:
        cruces = limites.consultar(
            inteligencia.head_to_head,
            settings.data_dir, settings.identidad.nosotros.rut, rut_rival, canal=canal,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"error": str(exc)}

    # Resumen sobre TODOS los cruces (no se pierde precisión); el detalle
    # que se devuelve sí se acota — head_to_head() no traía límite propio.
    n_cruces = len(cruces)
    ganados = sum(1 for c in cruces if c.ganador == "nosotros")
    diferencias = sorted(c.diferencia_pct for c in cruces if c.diferencia_pct is not None)
    diferencia_mediana = diferencias[len(diferencias) // 2] if diferencias else None

    advertencia = None
    if n_cruces == 0:
        advertencia = "Sin procesos donde ambos hayan participado — no se puede comparar."
    elif n_cruces < 5:
        advertencia = (
            f"Sólo {n_cruces} cruce(s) encontrados: tratar como anécdota, no como patrón."
        )

    truncado = n_cruces > limites.MAX_CRUCES_HEAD_TO_HEAD
    cruces_mostrados = cruces[: limites.MAX_CRUCES_HEAD_TO_HEAD] if truncado else cruces

    return {
        "rut_rival": rut_rival,
        "resumen": {
            "n_cruces": n_cruces,
            "ganados_por_nosotros": ganados,
            "diferencia_pct_mediana": diferencia_mediana,
            "advertencia": advertencia,
        },
        "cruces_truncados": truncado,
        "cruces": [
            {
                "canal": c.canal,
                "codigo_proceso": c.codigo_proceso,
                "producto": c.producto,
                "nuestro_monto": c.nuestro_monto,
                "su_monto": c.su_monto,
                "diferencia_pct": c.diferencia_pct,
                "ganador": c.ganador,
                "criterio": c.criterio,
            }
            for c in cruces_mostrados
        ],
    }


def _resolver_para_precio(producto: str, settings) -> dict:
    """Resuelve texto/SKU a código ONU y arma el bloque de metadata que
    toda tool de precio debe incluir (HU-3.2)."""
    resolucion = catalogo.resolver_producto(producto, settings.mapeos_path)
    return {
        "codigo_onu": resolucion.codigo_onu,
        "metodo_resolucion": resolucion.metodo,
        "confianza": resolucion.confianza,
    }


@mcp.tool()
def benchmark_precio(producto: str, canal: str | None = None) -> dict:
    """Distribución de precio unitario de mercado (min/p25/mediana/p75/max)
    para un producto, en CLP, separando ofertas ganadoras de perdedoras.

    `producto` puede ser un SKU del catálogo, texto libre o un código ONU
    literal — se resuelve con la misma lógica de resolver_producto (ÉP-03).
    Si no se puede resolver, no inventa un número: usa
    buscar_producto_en_historial junto con el catálogo primero.

    Con `muestra_insuficiente=true` (n < 10), la cifra es orientativa —
    adviértelo al usuario antes de recomendar un precio basado en esto.

    Args:
        producto: SKU, texto o código ONU (8 dígitos).
        canal: 'oc', 'lic', 'cot' o None (los tres, por defecto).
    """
    settings = get_settings()
    meta = _resolver_para_precio(producto, settings)
    if meta["codigo_onu"] is None:
        return {
            "producto_consultado": producto,
            **meta,
            "error": (
                "No se pudo resolver a un código ONU. Usa "
                "buscar_producto_en_historial junto con el catálogo, y "
                "registrar_mapeo_sku_onu para persistir el match."
            ),
        }

    try:
        r = limites.consultar(
            precios.benchmark_precio, settings.data_dir, meta["codigo_onu"], canal=canal
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"producto_consultado": producto, **meta, "error": str(exc)}

    return {
        "producto_consultado": producto,
        **meta,
        "n": r.n,
        "n_proveedores_distintos": r.n_proveedores_distintos,
        "muestra_insuficiente": r.muestra_insuficiente,
        "minimo": r.minimo,
        "p25": r.p25,
        "mediana": r.mediana,
        "p75": r.p75,
        "maximo": r.maximo,
        "ganadores": r.ganadores,
        "perdedores": r.perdedores,
    }


@mcp.tool()
def precio_para_ganar(producto: str, organismo: str | None = None, canal: str | None = None) -> dict:
    """Umbral de precio observado para ganar, a partir de casos históricos.

    Sólo usa LIC/COT (nunca 'oc': no expone ofertas perdedoras contra qué
    comparar). El precio NO es el único criterio de adjudicación — cruza
    con criterios_que_deciden antes de recomendar bajar precio. Cuando
    veces_gano_sin_ser_el_mas_barato > 0, algo más que el precio decidió en
    esos casos.

    Args:
        producto: SKU, texto o código ONU (8 dígitos).
        organismo: acota el umbral a un comprador específico si hay
                   suficientes datos (≥3 casos ganados con ese organismo).
        canal: 'lic', 'cot' o None (ambos).
    """
    settings = get_settings()
    meta = _resolver_para_precio(producto, settings)
    if meta["codigo_onu"] is None:
        return {
            "producto_consultado": producto,
            **meta,
            "error": (
                "No se pudo resolver a un código ONU. Usa "
                "buscar_producto_en_historial junto con el catálogo, y "
                "registrar_mapeo_sku_onu para persistir el match."
            ),
        }

    try:
        r = limites.consultar(
            precios.precio_para_ganar,
            settings.data_dir, meta["codigo_onu"], organismo=organismo, canal=canal,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"producto_consultado": producto, **meta, "error": str(exc)}

    return {
        "producto_consultado": producto,
        **meta,
        "n": r.n,
        "umbral_observado": r.umbral_observado,
        "precio_ganador_mas_caro": r.precio_ganador_mas_caro,
        "precio_perdedor_mas_barato": r.precio_perdedor_mas_barato,
        "procesos_con_ganador": r.procesos_con_ganador,
        "veces_gano_sin_ser_el_mas_barato": r.veces_gano_sin_ser_el_mas_barato,
        "por_organismo": r.por_organismo,
        "advertencia": (
            "El precio no es el único criterio de adjudicación — ver "
            "criterios_que_deciden antes de asumir que bajar precio garantiza ganar."
        ),
    }


@mcp.tool()
def criterios_que_deciden(
    producto: str | None = None, rubro_n1: str | None = None, canal: str | None = None
) -> dict:
    """Por qué se gana: clasifica el criterio declarado de las ofertas
    GANADORAS (precio, plazo de entrega, experiencia, canje/garantía,
    cumplimiento formal, integridad, otro) y, por categoría, cuánto más
    caro pudo ser el ganador respecto al oferente más barato del mismo
    proceso (`prima_precio_mediana_pct`).

    Sin producto ni rubro_n1, agrega sobre todo lo disponible. `rubro_n1`
    sólo filtra LIC — COT no tiene columna de rubro, se incluye igual sin
    filtrar por ese criterio.

    Args:
        producto: SKU, texto o código ONU — si se pasa y no se resuelve,
                  se ignora el filtro de producto (no bloquea la consulta).
        rubro_n1: nombre exacto de RubroN1 (ver config/identidad.toml).
        canal: 'lic', 'cot' o None (ambos).
    """
    settings = get_settings()
    codigo_onu = None
    metodo_resolucion = None
    confianza = None
    if producto:
        meta = _resolver_para_precio(producto, settings)
        codigo_onu, metodo_resolucion, confianza = (
            meta["codigo_onu"], meta["metodo_resolucion"], meta["confianza"],
        )

    try:
        r = limites.consultar(
            precios.criterios_que_deciden,
            settings.data_dir, codigo_onu=codigo_onu, rubro_n1=rubro_n1, canal=canal,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"producto_consultado": producto, "error": str(exc)}

    return {
        "producto_consultado": producto,
        "codigo_onu": codigo_onu,
        "metodo_resolucion": metodo_resolucion,
        "confianza": confianza,
        "n_procesos_ganadores": r.n_procesos_ganadores,
        "frecuencias": r.frecuencias,
    }


@mcp.tool()
def postmortem(codigo_proceso: str) -> dict:
    """Reconstruye una licitación o cotización específica: todas las
    ofertas, quién ganó, el criterio declarado, y la posición de
    Bioquimica.cl si participó (precio propio vs. el del ganador).

    Busca el código tanto en licitaciones como en compra ágil — no hace
    falta saber de antemano de qué canal es.

    Args:
        codigo_proceso: código externo de licitación (ej. '1057439-20-LP25')
                        o código de cotización (ej. '1079967-350-COT26').
    """
    settings = get_settings()
    try:
        pm = limites.consultar(
            precios.postmortem,
            settings.data_dir, codigo_proceso, rut_propio=settings.identidad.nosotros.rut,
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"codigo_proceso": codigo_proceso, "error": str(exc)}

    if pm.canal is None:
        return {
            "codigo_proceso": codigo_proceso,
            "error": "No se encontró ese código en LIC ni en COT.",
        }

    return {
        "codigo_proceso": pm.codigo_proceso,
        "canal": pm.canal,
        "ganador_rut": pm.ganador_rut,
        "nuestra_posicion": pm.nuestra_posicion,
        "ofertas": [
            {
                "rut": o.rut,
                "nombre": o.nombre,
                "producto": o.producto,
                "precio": o.precio,
                "seleccionado": o.seleccionado,
                "criterio": o.criterio,
            }
            for o in pm.ofertas
        ],
    }


@mcp.tool()
def perfil_comprador(organismo: str, top_n: int = 5) -> dict:
    """Qué compra un organismo, a quién, por qué canal (compra ágil vs.
    licitación pública/privada) y con qué estacionalidad mensual — desde
    órdenes de compra (dinero efectivamente transado, no ofertas).

    Cubre los compradores reales de Bioquimica.cl (Corp. Municipal de
    Lampa, SLEP del Elqui, U. de Talca, Muni. de Quillón, U. de Antofagasta,
    U. de Chile, entre otros vistos en el historial).

    Args:
        organismo: nombre del organismo comprador (case-insensitive).
        top_n: cuántos rubros/productos/proveedores top devolver.
    """
    settings = get_settings()
    try:
        perfil = limites.consultar(
            precios.perfil_comprador, settings.data_dir, organismo, top_n=top_n
        )
    except limites.ConsultaExcedioTiempoLimite as exc:
        return {"organismo": organismo, "error": str(exc)}

    if perfil.n_lineas == 0:
        return {
            "organismo": organismo,
            "n_lineas": 0,
            "nota": "Sin compras registradas en el lake para este organismo.",
        }

    return {
        "organismo": perfil.organismo,
        "n_lineas": perfil.n_lineas,
        "mix_canal": filas_a_tsv_xml(
            "mix_canal", ["canal", "monto", "n"],
            [[c["canal"], c["monto"], c["n"]] for c in perfil.mix_canal],
        ),
        "top_rubros": filas_a_tsv_xml(
            "top_rubros", ["rubro", "monto", "n"],
            [[r["rubro"], r["monto"], r["n"]] for r in perfil.top_rubros],
        ),
        "top_productos": filas_a_tsv_xml(
            "top_productos", ["producto", "n"],
            [[p["producto"], p["n"]] for p in perfil.top_productos],
        ),
        "top_proveedores": filas_a_tsv_xml(
            "top_proveedores", ["proveedor", "monto", "n"],
            [[p["proveedor"], p["monto"], p["n"]] for p in perfil.top_proveedores],
        ),
        "estacionalidad": filas_a_tsv_xml(
            "estacionalidad", ["mes", "n", "monto"],
            [[e["mes"], e["n"], e["monto"]] for e in perfil.estacionalidad],
        ),
    }


def main() -> None:
    settings = get_settings()
    configurar_logging(settings.log_dir)
    logger.info(
        "arrancando_servidor",
        extra={
            "extra_fields": {
                "host": settings.host,
                "port": settings.port,
                "ticket_configurado": settings.tiene_ticket,
                "auth_configurado": bool(settings.mcp_auth_token),
            }
        },
    )

    if settings.expuesto_a_internet and not settings.mcp_auth_token:
        # HU-7.1: el endpoint no puede quedar accesible sin autenticación.
        # 127.0.0.1 (default local) no es alcanzable desde fuera de la
        # máquina, así que sólo se exige cuando el bind es a 0.0.0.0/etc.
        raise RuntimeError(
            "MCP_HOST no es loopback pero MCP_AUTH_TOKEN no está configurado. "
            "El servidor quedaría expuesto sin autenticación — no arranca así. "
            "Definir MCP_AUTH_TOKEN antes de desplegar."
        )

    app = mcp.streamable_http_app(host=settings.host)
    if settings.mcp_auth_token:
        app = AutenticacionBearerMiddleware(app, settings.mcp_auth_token)
    else:
        logger.warning(
            "servidor_sin_autenticacion",
            extra={"extra_fields": {"detalle": "MCP_AUTH_TOKEN no configurado — sólo aceptable en loopback"}},
        )

    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
