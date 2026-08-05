# Resumen API Mercado Público V1 (Licitaciones y Órdenes de Compra)

Esta documentación resume los endpoints principales de la V1 de la API de Mercado Público para Licitaciones y Órdenes de Compra (OC). Ideal para ser consumida por LLMs y agentes de desarrollo.

## Autenticación (V1)
Para las APIs V1, el ticket de autorización se envía como **parámetro GET** en la URL.
- Ejemplo: `?ticket=TU_TICKET_AQUI`

## 1. API de Licitaciones

**URL Base:** `https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.{formato}`
**Formatos soportados:** `json`, `jsonp`, `xml`.

### Parámetros de Búsqueda GET
| Parámetro | Ejemplo | Descripción |
| :--- | :--- | :--- |
| `codigo` | `1509-5-L114` | Búsqueda directa por código de licitación. Omite la fecha. |
| `fecha` | `02022014` | Formato `DDMMAAAA`. Licitaciones de un día específico. |
| `estado` | `activas` o `5` | Filtra por estado de la licitación. |
| `CodigoProveedor` | `17793` | Búsqueda por proveedor. |
| `CodigoOrganismo` | `694` | Búsqueda por organismo público. |

### Estados de Licitaciones (Códigos)
- `5` = Publicada
- `6` = Cerrada
- `7` = Desierta
- `8` = Adjudicada
- `18` = Revocada
- `19` = Suspendida
- Opciones de texto: `activas`, `todos`.

---

## 2. API de Órdenes de Compra (OC)

**URL Base:** `https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.{formato}`

### Parámetros de Búsqueda GET
Mismos parámetros base que licitaciones (`codigo`, `fecha`, `CodigoProveedor`, `CodigoOrganismo`, `estado`, `ticket`).

### Estados de Órdenes de Compra
Se pueden buscar por texto o código:
- `enviadaproveedor` (Código: 4)
- `aceptada` (Código: 6)
- `cancelada` (Código: 9)
- `recepcionconforme` (Código: 12)
- `pendienterecepcion` (Código: 13)
- `recepcionaceptadacialmente` (Código: 14)
- `recepecionconformeincompleta` (Código: 15)
- `todos` (Muestra todos)
*(Nota: En proceso = 5).*

---

## 3. Descargas Masivas (Archivos .zip)

Para reportes históricos e información masiva sin usar la API por consulta individual.
- **Reportes Transacciones:** `https://transparenciachc.blob.core.windows.net/oc-da/{año}-{mes}.zip`
- **Cotizaciones Compra Ágil (2020 en adelante):** `https://transparenciachc.blob.core.windows.net/trnspchc/COT_{año}-{mes}.zip`
*(Ejemplo mes: `2022-01`)*
