"""Carga y validación de config/identidad.toml + variables de entorno.

HU-1.1: ninguna ruta, RUT o rubro debe quedar hardcodeado en el resto del
código. Toda tool que necesite el RUT propio, la watchlist o el alcance de
rubros lo lee de aquí.
"""

from __future__ import annotations

import logging
import os
import tempfile
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from mcp_mercadopublico.rut import dv_esperado, rut_valido

logger = logging.getLogger(__name__)

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


def _resolver_ruta_identidad_default() -> Path:
    """Ubica identidad.toml sin asumir instalación editable.

    En desarrollo (pip install -e .), __file__ vive en <repo>/src/mcp_mercadopublico/
    y RAIZ_PROYECTO cae correctamente en la raíz del repo. Con una instalación
    NO editable (pip install . plano — el caso normal en un Dockerfile),
    __file__ termina dentro de site-packages y RAIZ_PROYECTO/"config" apunta a
    un lugar que no existe (verificado: cae en .../Lib/config/identidad.toml).
    En ese caso, usar IDENTIDAD_TOML_PATH (override explícito) o el cwd del
    proceso — en el contenedor, WORKDIR + `config/` copiado ahí lo resuelve.
    """
    candidato_editable = RAIZ_PROYECTO / "config" / "identidad.toml"
    if candidato_editable.exists():
        return candidato_editable

    override = os.environ.get("IDENTIDAD_TOML_PATH")
    if override:
        return Path(override)

    return Path.cwd() / "config" / "identidad.toml"


RUTA_IDENTIDAD_DEFAULT = _resolver_ruta_identidad_default()


# --------------------------------------------------------------------------
# [nosotros]
# --------------------------------------------------------------------------


class CanalMensual(BaseModel):
    compra_agil_o_trato_directo: float
    licitacion_publica: float
    licitacion_privada: float


class WinRateMensual(BaseModel):
    lineas_ganadas: int
    lineas_perdidas: int
    tasa: float
    cotizaciones_distintas: int


class Nosotros(BaseModel):
    rut: str
    codigo_proveedor: str = ""
    razon_social_mp: str = ""
    giro_mp: str = ""
    canal_2026_06: CanalMensual | None = None
    win_rate_compra_agil_2026_06: WinRateMensual | None = None

    @field_validator("rut")
    @classmethod
    def _rut_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "config/identidad.toml: [nosotros].rut está vacío. Sin el RUT "
                "propio no funcionan head_to_head, postmortem ni el cálculo "
                "de win rate (HU-1.1)."
            )
        return v


# --------------------------------------------------------------------------
# [ingesta]
# --------------------------------------------------------------------------


class RubroIngesta(BaseModel):
    nombre: str
    motivo: str = ""
    subrubros_clave: list[str] = Field(default_factory=list)
    estado: str = "confirmado"


class Ingesta(BaseModel):
    periodo_desde: str
    periodo_hasta: str
    datasets: list[str]
    filtro: str
    rubros_n1: list[RubroIngesta]


# --------------------------------------------------------------------------
# [competencia]
# --------------------------------------------------------------------------


class CompetidorLiga(BaseModel):
    rut: str
    nombre: str
    clp_2026_06: float = 0.0
    lineas: int = 0
    nota: str = ""


class RutDudoso(BaseModel):
    rut_entregado: str
    rut_corregido: str
    problema: str = ""


class Competencia(BaseModel):
    liga_a: list[CompetidorLiga] = Field(default_factory=list)
    liga_b: list[CompetidorLiga] = Field(default_factory=list)
    sin_actividad_2026_06: list[str] = Field(default_factory=list)
    dudosos: list[RutDudoso] = Field(default_factory=list)

    def todos_los_rut(self) -> list[str]:
        return (
            [c.rut for c in self.liga_a]
            + [c.rut for c in self.liga_b]
            + list(self.sin_actividad_2026_06)
        )


# --------------------------------------------------------------------------
# [brechas]
# --------------------------------------------------------------------------


class RivalDetectado(BaseModel):
    rut: str
    nombre: str
    coincidencias: int
    en_watchlist: bool = False
    nota: str = ""


class UniversoRivales(BaseModel):
    universo: str
    en_watchlist: int
    detectados: list[RivalDetectado] = Field(default_factory=list)


class Brechas(BaseModel):
    lideres_fuera_de_watchlist: str = ""
    rivales_no_listados: list[UniversoRivales] = Field(default_factory=list)
    metodo_correcto: str = ""
    rubro_n1_faltante: str = ""


# --------------------------------------------------------------------------
# Identidad completa + carga
# --------------------------------------------------------------------------


class Identidad(BaseModel):
    nosotros: Nosotros
    ingesta: Ingesta
    competencia: Competencia = Field(default_factory=Competencia)
    brechas: Brechas = Field(default_factory=Brechas)


def _advertir_ruts_invalidos(identidad: Identidad) -> None:
    """Registra un warning por cada RUT con DV mod-11 inválido.

    No descarta ni falla (HU-1.1): un RUT dudoso en la watchlist no debe
    tumbar el servidor, sólo quedar visible en el log. El caso ya conocido
    (rut_entregado de un RutDudoso) no se re-reporta.
    """
    ya_reportados = {d.rut_entregado.upper() for d in identidad.competencia.dudosos}

    candidatos: list[str] = [identidad.nosotros.rut]
    candidatos += identidad.competencia.todos_los_rut()
    candidatos += [d.rut_corregido for d in identidad.competencia.dudosos]
    for universo in identidad.brechas.rivales_no_listados:
        candidatos += [r.rut for r in universo.detectados]

    for rut in candidatos:
        if not rut or rut.upper() in ya_reportados:
            continue
        if not rut_valido(rut):
            logger.warning(
                "rut_dv_invalido",
                extra={
                    "extra_fields": {
                        "rut": rut,
                        "dv_esperado": dv_esperado(rut),
                    }
                },
            )


def cargar_identidad(ruta: Path = RUTA_IDENTIDAD_DEFAULT) -> Identidad:
    """Parsea identidad.toml y valida sus RUT. Sin caché — usar en tests."""
    with ruta.open("rb") as f:
        datos = tomllib.load(f)
    identidad = Identidad.model_validate(datos)
    _advertir_ruts_invalidos(identidad)
    return identidad


# --------------------------------------------------------------------------
# Settings (identidad + entorno)
# --------------------------------------------------------------------------


class Settings(BaseModel):
    identidad: Identidad
    mercado_publico_tickets: list[str] = Field(default_factory=list)
    log_dir: Path = RAIZ_PROYECTO / "logs"
    data_dir: Path = RAIZ_PROYECTO / "data"
    manifest_path: Path = RAIZ_PROYECTO / "data" / "manifest.sqlite"
    cache_path: Path = RAIZ_PROYECTO / "data" / "cache.sqlite"
    mapeos_path: Path = RAIZ_PROYECTO / "data" / "mapeos.sqlite"
    # Deliberadamente FUERA de data_dir: el scratch de ingesta (ZIP + CSV
    # intermedios, hasta ~1,34 GB por periodo) no debe vivir en el Volume
    # persistente de Railway — se descarta al terminar cada periodo (HU-2.2,
    # HU-2.5) y no aporta nada quedarse pagando por ese espacio.
    scratch_dir: Path = Path(tempfile.gettempdir()) / "mcp_mercadopublico_scratch"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def tiene_ticket(self) -> bool:
        return bool(self.mercado_publico_tickets)

    def requerir_ticket(self) -> str:
        """Un ticket cualquiera del pool, para código que aún no rota (ÉP-06
        no construido todavía). Cuando se implemente el cliente de la API en
        línea, reemplazar por una selección por menor uso diario contra
        quota_log en manifest.sqlite — nunca round-robin ciego, porque cada
        ticket tiene su propia cuota diaria independiente.

        Falla explícito en vez de mandar 'None' como header/query param — el
        data lake (Plano B) no necesita ticket, sólo el Plano A lo requiere.
        """
        if not self.mercado_publico_tickets:
            raise RuntimeError(
                "Ningún MERCADO_PUBLICO_TICKET configurado. Requerido sólo "
                "para consultar la API en línea de Mercado Público (Plano A)."
            )
        return self.mercado_publico_tickets[0]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de configuración para el proceso del servidor.

    En tests, usar cargar_identidad() directamente en vez de esta función —
    lru_cache fija la primera carga para todo el proceso. Si un test necesita
    forzar una recarga, llamar get_settings.cache_clear() antes.

    DATA_DIR es la variable que importa en producción (Railway): sin ella,
    data_dir/manifest_path/cache_path caen dentro del código fuente — que en
    Railway es el filesystem efímero del contenedor y se borra en cada
    redeploy. En Railway, DATA_DIR debe apuntar al mount path de un Volume
    persistente (ej. /data). Sin DATA_DIR (desarrollo local), usa
    RAIZ_PROYECTO/data como hasta ahora.

    Tickets: acepta MERCADO_PUBLICO_TICKETS (varios, separados por coma) o
    MERCADO_PUBLICO_TICKET (uno solo, retrocompatible). Rotar entre ellos por
    menor uso diario es trabajo de ÉP-06, no de esta función.
    """
    identidad = cargar_identidad(RUTA_IDENTIDAD_DEFAULT)
    tickets_env = os.environ.get("MERCADO_PUBLICO_TICKETS")
    if tickets_env:
        tickets = [t.strip() for t in tickets_env.split(",") if t.strip()]
    else:
        ticket_unico = os.environ.get("MERCADO_PUBLICO_TICKET")
        tickets = [ticket_unico] if ticket_unico else []

    data_dir_env = os.environ.get("DATA_DIR")
    data_dir = Path(data_dir_env) if data_dir_env else (RAIZ_PROYECTO / "data")

    log_dir_env = os.environ.get("LOG_DIR")
    log_dir = Path(log_dir_env) if log_dir_env else (RAIZ_PROYECTO / "logs")

    scratch_dir_env = os.environ.get("SCRATCH_DIR")
    scratch_dir = (
        Path(scratch_dir_env) if scratch_dir_env
        else Path(tempfile.gettempdir()) / "mcp_mercadopublico_scratch"
    )

    # Railway inyecta PORT (no MCP_PORT) y espera que el proceso escuche ahí
    # — tiene prioridad. MCP_PORT queda como override explícito para local/
    # otros hosts; 8000 es el default sin ninguno de los dos.
    puerto = os.environ.get("PORT") or os.environ.get("MCP_PORT", "8000")

    settings = Settings(
        identidad=identidad,
        mercado_publico_tickets=tickets,
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(puerto),
        log_dir=log_dir,
        data_dir=data_dir,
        manifest_path=data_dir / "manifest.sqlite",
        cache_path=data_dir / "cache.sqlite",
        mapeos_path=data_dir / "mapeos.sqlite",
        scratch_dir=scratch_dir,
    )
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    if not settings.tiene_ticket:
        logger.warning(
            "ticket_no_configurado",
            extra={
                "extra_fields": {
                    "detalle": (
                        "MERCADO_PUBLICO_TICKET no está definido. El Plano A "
                        "(API en línea) no funcionará hasta configurarlo. El "
                        "data lake (Plano B) no requiere ticket."
                    )
                }
            },
        )

    return settings
