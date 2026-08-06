# MCP Mercado Público — Bioquimica.cl
# Servidor MCP remoto (HTTP) para Railway. Ver Backlog/backlog-mcp-mercadopublico.md
# ÉPICA 07 para el contrato completo (Volume, auth, límites de recursos).

FROM python:3.11-slim

# curl: lo usa el HEALTHCHECK de esta imagen. Se limpia el cache de apt en la
# misma capa para no dejarlo pesando en la imagen final.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
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

# Usuario sin privilegios — nunca correr el proceso como root.
RUN useradd --create-home --uid 1000 mcp \
    && mkdir -p /data /app/logs \
    && chown -R mcp:mcp /app /data
USER mcp

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

CMD ["python", "-m", "mcp_mercadopublico.server"]
