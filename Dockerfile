# MCP Mercado Público — Bioquimica.cl
# Servidor MCP remoto (HTTP) para Railway. Ver Backlog/backlog-mcp-mercadopublico.md
# ÉPICA 07 para el contrato completo (Volume, auth, límites de recursos).

FROM python:3.11-slim

# curl: lo usa el HEALTHCHECK de esta imagen.
# gosu: lo usa docker-entrypoint.sh para bajar privilegios a `mcp` después de
#       corregir la propiedad del Volume montado en runtime.
# Se limpia el cache de apt en la misma capa para no dejarlo pesando en la
# imagen final.
RUN apt-get update && apt-get install -y --no-install-recommends curl gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Capa de dependencias primero: cambia poco entre builds, se cachea aparte
# del código fuente (que cambia en casi cada commit).
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente + config. config/identidad.toml se resuelve relativo al cwd
# del proceso cuando el paquete queda instalado no-editable (ver
# config.py:_resolver_ruta_identidad_default — verificado que sin ese
# fallback, __file__ cae dentro de site-packages y la ruta se pierde).
COPY src/ src/
COPY config/ config/
RUN pip install --no-cache-dir --no-deps .

# Usuario sin privilegios — el proceso del servidor NUNCA corre como root.
# Ojo: este chown es de build time y NO sobrevive al montaje de un Volume en
# runtime (Railway monta /data propiedad de root, tapando esto). Por eso el
# entrypoint lo vuelve a hacer al arrancar — ver docker-entrypoint.sh.
RUN useradd --create-home --uid 1000 mcp \
    && mkdir -p /data /app/logs \
    && chown -R mcp:mcp /app /data

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# NO se declara `USER mcp`: el entrypoint arranca como root sólo para corregir
# la propiedad del Volume y baja a `mcp` con gosu antes de ejecutar el CMD.
ENV PYTHONUNBUFFERED=1 \
    MCP_HOST=0.0.0.0 \
    DATA_DIR=/data \
    LOG_DIR=/app/logs

# Documenta el puerto por defecto para `docker run` local. En Railway el
# puerto real llega por la variable PORT (ver config.py) — EXPOSE es sólo
# metadata, no fuerza el valor en runtime.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "mcp_mercadopublico.server"]
