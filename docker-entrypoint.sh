#!/bin/sh
# Entrypoint: corrige la propiedad del Volume y baja privilegios — HU-7.3.
#
# Motivo (bug real, encontrado en producción 2026-08-06): el Dockerfile hace
# `chown mcp:mcp /data` en BUILD time, pero Railway monta el Volume persistente
# en RUNTIME, reemplazando ese directorio por uno propiedad de root. El proceso
# corre como `mcp` (uid 1000) y no puede escribir ahí, así que
# `Path.mkdir(exist_ok=True)` no falla (el directorio ya existe) y el error
# aparece recién al abrir SQLite: "unable to open database file".
#
# Docker local NO reproduce esto: con bind mounts en Docker Desktop/Windows y
# con volúmenes nombrados, Docker deriva la propiedad de la imagen — por eso el
# despliegue pasó las pruebas locales y falló en Railway.
#
# Este script corre como root sólo para el chown y después ejecuta el servidor
# como `mcp` vía gosu. Es idempotente: si la propiedad ya es correcta, el chown
# no hace daño.
set -e

DATA_DIR="${DATA_DIR:-/data}"
LOG_DIR="${LOG_DIR:-/app/logs}"

for dir in "$DATA_DIR" "$LOG_DIR"; do
    mkdir -p "$dir" 2>/dev/null || true
    # `|| true`: si el mount es de sólo lectura o el chown no está permitido, no
    # abortamos acá — el servidor va a fallar más adelante con un error más
    # descriptivo (y verificar_estado reporta el espacio/estado real del lake).
    chown -R mcp:mcp "$dir" 2>/dev/null || true
done

exec gosu mcp "$@"
