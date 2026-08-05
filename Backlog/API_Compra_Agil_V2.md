# Resumen API Compra Ágil V2

Documentación optimizada de la API v2 de Compra Ágil.
**URL Base:** `https://api2.mercadopublico.cl`

## Autenticación y Cuotas
- **Autenticación:** El ticket de acceso se debe enviar en el **Header HTTP**, NO en la URL.
  - Header: `ticket: TU_TICKET_AQUI`
- **Límites (Control de cuota):** 
  - Limite por ticket por día calendario.
  - Si se supera, la API retorna **HTTP 429 (Too Many Requests)**.
  - Reset de cuota: Al inicio del siguiente día calendario (00:00).

## 1. Endpoint: Listado y Búsqueda
`GET /v2/compra-agil`

Retorna resultados paginados y permite filtrar compras ágiles.

### Parámetros de Consulta (Query Params)
- **Sincronización:** 
  - `ttl_cambio_ms`: (int) Cambios en los últimos X milisegundos (ej: 300000 para 5 min).
  - `cambio_desde` / `cambio_hasta`: (ISO-8601) Rango temporal de actualización.
- **Fechas publicación:** `publicado_desde` / `publicado_hasta` (ISO-8601).
- **Estado (`estado`):** 
  - Valores: `publicada`, `cerrada`, `desierta`, `cancelada`, `proveedor_seleccionado`.
  - *IMPORTANTE:* El estado `oc_emitida` está documentado pero NO funciona en la práctica. Para buscar emitidas, buscar `proveedor_seleccionado` y revisar el detalle.
- **Región (`region`):** Código del 1 al 16 (ej. Metropolitana = 13). Admite múltiples separados por coma.
  - *IMPORTANTE:* No existe el parámetro `codigo_organismo` en esta API. Se debe filtrar por región y luego buscar por RUT/organismo a nivel de aplicación (local).
- **Búsqueda por ID / Palabras:** `id` (ej. '507428-142-COT25') o `q` (texto url-encoded). Son mutuamente excluyentes.
- **Paginación:** `tamano_pagina` (max 50, default 15), `numero_pagina` (comienza en 1).
- **Orden:** `ordenar_por` (Valores: `FechaUltimaModificacion`, `FechaPublicacion`).

## 2. Endpoint: Detalle de Compra Ágil
`GET /v2/compra-agil/{codigo}`

Entrega el detalle completo, incluyendo productos y cotizaciones de proveedores.

### Reglas Críticas del Modelo de Datos
- **Estados y Convocatoria:** El estado (`publicada`/`cerrada`) interactúa con la etapa del llamado (`convocatoria.estado_convocatoria` = 1 o 2).
- **Relación con Órdenes de Compra:**
  - El campo `orden_compra.codigo_orden_compra` y `orden_compra.estado_orden_compra` retornan `null` incluso si hay OC.
  - **Patrón para confirmar OC emitida:** Revisar el campo `orden_compra.id_orden_compra`. Si es **distinto de null**, significa que la OC fue emitida. Utilizar este ID para buscar la OC real en la API V1 de Órdenes de Compra.
- **Proveedores cotizando:**
  - Muestra proveedores de la convocatoria actual.
  - El detalle completo (precios, justificaciones) es visible desde el estado `cerrada` en el segundo llamado en adelante.

## Respuestas y Manejo de Errores (Formato General JSON)
```json
{
  "success": "OK", // o "NOK" en error
  "trace": null,
  "payload": { ... }, // data de la respuesta
  "errors": null // o array de errores con codigo, mensaje
}
```
- Errores comunes: `400` (Bad Request), `401` (Unauthorized - Falta header ticket), `429` (Too Many Requests - Cuota diaria).
