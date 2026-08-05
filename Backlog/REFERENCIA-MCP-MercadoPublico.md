# Referencia Técnica Única — MCP Mercado Público (Bioquimica.cl)

> Documento maestro de referencia para el desarrollo del servidor MCP.
> Consolida: `API_Compra_Agil_V2.md`, `API_Licitaciones_OrdenesCompra_V1.md`,
> `prompt-desarrollo-mcp-mercadopublico.md`, `backlog-mcp-mercadopublico.md`.
>
> **Convención de confianza** — cada dato lleva una marca:
> - ✅ **VERIFICADO**: documentado y confirmado en la práctica.
> - ⚠️ **A VERIFICAR**: supuesto razonable, requiere prueba empírica antes de codificar contra él.
> - ❌ **TRAMPA**: documentado por ChileCompra pero que NO funciona como dice.

---

## 0. Índice

1. [Objetivo del sistema](#1-objetivo-del-sistema)
2. [Arquitectura: dos planos de datos](#2-arquitectura-dos-planos-de-datos)
3. [Autenticación y cuotas](#3-autenticación-y-cuotas)
4. [Plano A — API en línea](#4-plano-a--api-en-línea)
5. [Plano B — Datos Abiertos (descargas masivas)](#5-plano-b--datos-abiertos-descargas-masivas)
6. [Capa de persistencia y caché](#6-capa-de-persistencia-y-caché)
7. [Catálogo de herramientas MCP](#7-catálogo-de-herramientas-mcp)
8. [Optimización de tokens](#8-optimización-de-tokens)
9. [Procesamiento de adjuntos](#9-procesamiento-de-adjuntos)
10. [Errores, resiliencia y contratos](#10-errores-resiliencia-y-contratos)
11. [Datos de identidad pendientes](#11-datos-de-identidad-pendientes-bloqueantes)
12. [Servidores MCP ya conectados: evitar duplicar](#12-servidores-mcp-ya-conectados-evitar-duplicar)
13. [Stack, layout y decisiones cerradas](#13-stack-layout-y-decisiones-cerradas)
14. [Roadmap revisado](#14-roadmap-revisado)
15. [Preguntas abiertas](#15-preguntas-abiertas)

---

## 1. Objetivo del sistema

**Definido por el usuario (2026-08-05):** entender el movimiento de los principales
competidores mediante conversación natural en **claude.ai**, para armar mejores ofertas
a licitaciones y compras ágiles.

Esto ordena las prioridades así:

| Prioridad | Uso | Pregunta que responde | Plano |
| :-- | :-- | :-- | :-- |
| 🔴 **1** | **Inteligencia competitiva** | ¿Qué está haciendo la competencia, dónde y a qué precio? | B (histórico masivo) |
| 🔴 **2** | **Calibración de ofertas** | ¿A qué precio y con qué argumento ganamos esto? | B |
| 🟡 3 | Desempeño propio | ¿Qué ganamos/perdimos y por qué? | B |
| 🟢 4 | Detección de oportunidades | ¿Qué se publicó hoy? | **Lo cubre LicitaLab** — no reimplementar |
| ⚪ 5 | Lectura de bases | ¿Qué exige esta licitación? | Fuera del objetivo declarado; postergado |

Dos consecuencias inmediatas:

- **ÉPICA 05 (OCR/adjuntos) sale de la ruta crítica.** Servía para leer bases; entender a
  la competencia no la necesita. Si vuelve, será delegada a `optimizador-documentos` (§12).
- **La búsqueda de oportunidades en tiempo real deja de ser un entregable.** LicitaLab ya
  la cubre; construirla de nuevo es gastar en paridad en vez de en ventaja. La API en línea
  (Plano A) queda como complemento puntual, no como columna vertebral.

El diferenciador es el lake histórico: **los tres datasets traen a los oferentes
perdedores con su precio**. Eso no lo entrega la API ni LicitaLab.

### 1.1 Alcance cerrado (decisiones del usuario)

| Decisión | Valor | Consecuencia |
| :-- | :-- | :-- |
| **Consumo** | **Remoto para claude.ai** | Servidor HTTP hosteado + conector. Ver §13.0 — cambia el despliegue por completo |
| **Historia** | **2025-2026** (~20 meses) | ~37 M filas antes de filtrar; ver §13.0 para el dimensionamiento |
| **Rubros** | **Derivados del catálogo BQ** | Resuelto: 6 `RubroN1`. Ver `config/identidad.toml` |
| **Watchlist** | 33 RUT entregados, validados y perfilados | Es lista de **prioridad**, no filtro de ingesta — ver §7.0 |

---

## 2. Arquitectura: dos planos de datos

Esta es la corrección arquitectónica más importante respecto del backlog original,
que trata todo como "llamadas a la API".

```
                     ┌──────────────────────────────┐
   Claude  ◄────────►│      Servidor MCP (Python)   │
                     └───────┬──────────────┬───────┘
                             │              │
       PLANO A: tiempo real  │              │  PLANO B: histórico masivo
       (cuota diaria escasa) │              │  (sin cuota, offline)
                             ▼              ▼
              ┌──────────────────┐   ┌────────────────────────┐
              │ api2 / api       │   │ transparenciachc.blob  │
              │ mercadopublico   │   │ ...  *.zip (mensual)   │
              └────────┬─────────┘   └───────────┬────────────┘
                       │                         │
                       ▼                         ▼
              ┌──────────────────┐   ┌────────────────────────┐
              │ Caché SQLite TTL │   │ Data lake local        │
              │ (respuestas API) │   │ Parquet + DuckDB       │
              └──────────────────┘   └────────────────────────┘
```

**Regla de enrutamiento** que el MCP debe aplicar (y documentar en docstrings para
que Claude la respete):

| Si la pregunta es sobre… | Usar | Motivo |
| :-- | :-- | :-- |
| Últimos 30 días, estado actual, "¿está abierta?" | Plano A | Único con dato fresco |
| Precios históricos, series, rankings, market share | Plano B | La API no agrega; y la cuota diaria muere en 3 consultas amplias |
| Un código específico (`1509-5-L114`, `507428-142-COT25`) | Plano A | Lookup directo, 1 request |
| "¿Cuánto compró el Hospital X de reactivos en 2024?" | Plano B | Barrido imposible por API |

> **Punto crítico**: las HU-3.1 y HU-3.2 del backlog (espionaje de competencia por
> `CodigoProveedor` / `CodigoOrganismo` vía API V1) están mal asignadas al Plano A.
> La API V1 pagina por **día**, así que un año de historia = 365 requests = cuota
> agotada. Esas historias se implementan sobre el Plano B.

---

## 3. Autenticación y cuotas

✅ **VERIFICADO** — El mismo ticket, dos mecanismos de transporte distintos:

| API | Transporte del ticket | Ejemplo |
| :-- | :-- | :-- |
| **V1** (Licitaciones, Órdenes de Compra) | Query parameter | `...licitaciones.json?ticket=TICKET&fecha=02022014` |
| **V2** (Compra Ágil) | Header HTTP | `headers={"ticket": TICKET}` |
| **Datos Abiertos** (ZIP) | Ninguno — público | descarga anónima |

- Origen del ticket: variable de entorno `MERCADO_PUBLICO_TICKET`. Nunca en código.
- ✅ Cuota: **límite por ticket por día calendario**. Excedido ⇒ `HTTP 429`.
- ✅ Reset: 00:00 del día siguiente (⚠️ **A VERIFICAR**: zona horaria — asumir
  `America/Santiago`, confirmar contra reloj real).
- ⚠️ **A VERIFICAR**: el número exacto de requests/día del ticket. ChileCompra no lo
  publica de forma estable. **Implicación de diseño**: no se puede planificar contra
  un número, hay que **contar localmente** cada request y degradar con gracia.

### 3.1 Contador de cuota local (requisito no presente en el backlog)

El MCP debe llevar su propio contador persistente:

```
tabla quota_log(fecha_local DATE, api TEXT, requests INT, http_429 INT)
```

Y exponerlo vía `verificar_estado_cuota`. Sin esto, Claude no puede decidir si le
conviene gastar requests en un barrido o ir al Plano B.

---

## 4. Plano A — API en línea

### 4.1 API V2 — Compra Ágil

**Base:** `https://api2.mercadopublico.cl`

#### `GET /v2/compra-agil` — listado y búsqueda

| Grupo | Parámetro | Tipo / valores | Notas |
| :-- | :-- | :-- | :-- |
| Sincronización | `ttl_cambio_ms` | int (ms) | Cambios en los últimos X ms. Ej: `300000` = 5 min |
| Sincronización | `cambio_desde` / `cambio_hasta` | ISO-8601 | Rango de última modificación |
| Publicación | `publicado_desde` / `publicado_hasta` | ISO-8601 | |
| Estado | `estado` | `publicada`, `cerrada`, `desierta`, `cancelada`, `proveedor_seleccionado` | ver ❌ abajo |
| Geografía | `region` | código 1–16, coma-separado | Metropolitana = `13` |
| Búsqueda | `id` | ej. `507428-142-COT25` | **excluyente** con `q` |
| Búsqueda | `q` | texto url-encoded | **excluyente** con `id` |
| Paginación | `tamano_pagina` | max **50**, default 15 | |
| Paginación | `numero_pagina` | **empieza en 1** | |
| Orden | `ordenar_por` | `FechaUltimaModificacion`, `FechaPublicacion` | |

❌ **TRAMPA 1** — `estado=oc_emitida` está documentado pero **NO funciona**.
Patrón correcto: consultar `estado=proveedor_seleccionado` y luego inspeccionar el
detalle de cada resultado.

❌ **TRAMPA 2** — **no existe** `codigo_organismo` en la V2. Para responder "¿qué
publicó el Hospital X?", hay que filtrar por `region` y luego filtrar por RUT /
nombre de organismo **en el cliente**. El docstring de la tool debe decirlo
explícitamente para que Claude no lo invente.

#### `GET /v2/compra-agil/{codigo}` — detalle

Retorna productos solicitados, presupuesto, plazos, y cotizaciones de proveedores.

Reglas del modelo de datos:

- ✅ El estado (`publicada`/`cerrada`) interactúa con `convocatoria.estado_convocatoria`
  (`1` o `2` = primer/segundo llamado). Una compra ágil puede reabrirse.
- ❌ **TRAMPA 3** — `orden_compra.codigo_orden_compra` y
  `orden_compra.estado_orden_compra` retornan `null` **incluso cuando existe la OC**.
  **Patrón correcto**: si `orden_compra.id_orden_compra != null` ⇒ la OC fue emitida.
  Usar ese `id` para resolver la OC real contra la **API V1 de Órdenes de Compra**.
  Esto obliga a un *join cross-API* dentro del MCP — no dejárselo a Claude.
- ✅ Los proveedores cotizando corresponden a la convocatoria actual. Precios y
  justificaciones sólo son visibles desde estado `cerrada`, **segundo llamado en
  adelante**.

#### Envoltura de respuesta V2

```json
{
  "success": "OK",        // "NOK" en error
  "trace": null,
  "payload": { },         // datos
  "errors": null          // o [{ codigo, mensaje }]
}
```

⚠️ **A VERIFICAR**: `success: "NOK"` puede venir con `HTTP 200`. El cliente debe
validar **ambos**: status code *y* campo `success`. No confiar sólo en `raise_for_status()`.

---

### 4.2 API V1 — Licitaciones

**Base:** `https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.{formato}`
**Formatos:** `json` · `jsonp` · `xml` → usar siempre `json`.

| Parámetro | Ejemplo | Descripción |
| :-- | :-- | :-- |
| `codigo` | `1509-5-L114` | Lookup directo. **Ignora `fecha`** |
| `fecha` | `02022014` | Formato `DDMMAAAA` (sin separadores) |
| `estado` | `activas` o `5` | Texto o código |
| `CodigoProveedor` | `17793` | ⚠️ ID interno de MP, **no el RUT** |
| `CodigoOrganismo` | `694` | ID interno del organismo |

**Estados de licitación** ✅:

| Código | Estado | | Texto | Significado |
| :-- | :-- | :-- | :-- | :-- |
| `5` | Publicada | | `activas` | abiertas |
| `6` | Cerrada | | `todos` | sin filtro |
| `7` | Desierta | | | |
| `8` | Adjudicada | | | |
| `18` | Revocada | | | |
| `19` | Suspendida | | | |

⚠️ **A VERIFICAR / advertencia de volumen**: `licitaciones.json?fecha=DDMMAAAA`
devuelve **todas** las licitaciones del día (cientos). La respuesta sin filtrar puede
superar el presupuesto de contexto de Claude. **Requisito**: el MCP debe **proyectar
campos** (whitelist) y paginar en el lado servidor antes de devolver. Nunca hacer
passthrough del JSON crudo.

⚠️ **A VERIFICAR**: el llamado por `codigo` devuelve la ficha completa (ítems,
oferentes, adjudicación) mientras que el llamado por `fecha` devuelve una versión
resumida. Confirmar y documentar los dos esquemas — HU-4.2 (post-mortem) depende del
detalle por `codigo`.

---

### 4.3 API V1 — Órdenes de Compra

**Base:** `https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.{formato}`

Mismos parámetros base que licitaciones: `codigo`, `fecha`, `CodigoProveedor`,
`CodigoOrganismo`, `estado`, `ticket`.

**Estados de OC** ✅:

| Texto | Código |
| :-- | :-- |
| — (En proceso) | `5` |
| `enviadaproveedor` | `4` |
| `aceptada` | `6` |
| `cancelada` | `9` |
| `recepcionconforme` | `12` |
| `pendienterecepcion` | `13` |
| `recepcionaceptadacialmente` | `14` |
| `recepecionconformeincompleta` | `15` |
| `todos` | — |

> Nota: `recepcionaceptadacialmente` y `recepecionconformeincompleta` están así,
> con errores tipográficos, en la API real. **Copiarlos literalmente** — no
> "corregirlos". Definirlos como constantes/`Enum` para que nadie los normalice.

---

## 5. Plano B — Datos Abiertos (descargas masivas)

> ✅ **SPIKE COMPLETADO (2026-08-05).** La caracterización completa está en
> **[`docs/esquema-datos-abiertos.md`](../docs/esquema-datos-abiertos.md)** — esquemas de
> las 222 columnas, 15 trampas de parsing verificadas, tamaños, frescura y estabilidad
> del esquema. Esta sección queda como resumen; ese documento es la fuente de verdad.

### 5.1 Endpoints de descarga ✅ VERIFICADO empíricamente

| Dataset | Patrón de URL | ⚠️ Mes | Cobertura | Lag |
| :-- | :-- | :-- | :-- | :-- |
| **Órdenes de compra** | `…/oc-da/{AAAA}-{M}.zip` | **sin** padding | `2007-1` → hoy | ~1 día |
| **Licitaciones** ⭐ | `…/lic-da/{AAAA}-{M}.zip` | **sin** padding | ≥ `2015-6` → hoy | ~1 día |
| **Cotizaciones Compra Ágil** | `…/trnspchc/COT_{AAAA}-{MM}.zip` | **con** padding | 75 meses | ~1 mes |

Host: `https://transparenciachc.blob.core.windows.net`

❌ **TRAMPA 4 (corrección a la documentación original)** — el mes de `oc-da`/`lic-da` va
**sin cero-padding**. `oc-da/2026-06.zip` → **404**; `oc-da/2026-6.zip` → **200**. `COT_`,
en cambio, **sí** usa padding. Regla por dataset, no global.

⭐ **`lic-da` no estaba documentado** y es el dataset más valioso del proyecto: contiene el
detalle de **todas las ofertas, incluidas las perdedoras**, con `MontoUnitarioOferta` y
`Oferta seleccionada`.

### 5.2 Hechos duros del spike

| Dato | Valor |
| :-- | :-- |
| Encoding | `latin-1`/`cp1252`, sin BOM — **no UTF-8** |
| Separador / quoting | `;` · todo entre `"` |
| Decimales | **coma** (`19977,72`) |
| Fechas | ISO `AAAA-MM-DD` |
| Volumen | **~1,84 M filas y 2,4 GB descomprimidos por mes** (los 3 datasets) |
| Compresión | ~17:1 — `COT` de 78 MB → 1,34 GB |
| Columnas | OC 78 · LIC 110 · COT 34 |
| `ETag`/`Last-Modified` | presentes ⇒ descarga condicional viable |
| Precio unitario | ✅ **existe**: `precioNeto` (OC), `MontoUnitarioOferta` (LIC), `MontoTotal` (COT) |
| Estabilidad del esquema | ❌ **cambia** — LIC 105→110 cols; OC renombró una columna; **el índice absoluto se desplaza** (orden relativo estable, pero inserciones corren todo lo posterior) |
| Inmutabilidad de periodos | ❌ **no son inmutables** — `oc-da/2026-6` se regeneró 2 meses tras el cierre |

**Tres reglas de ETL no negociables** (derivadas de lo anterior):

1. Mapear columnas **por nombre, nunca por posición** — las columnas agregadas desplazan
   el índice absoluto de todo lo posterior; leer por índice corre los datos en silencio.
2. Parser CSV real. **Prohibido** `split("\n")` o contar líneas: hay newlines embebidos en
   campos entrecomillados (`Descripcion/Obervaciones`, `DetalleCotizacion`).
3. Guardar `ETag` por periodo y **reingerir cuando cambie**, aunque el periodo esté cerrado.

⚠️ **TRAMPA 5 — la más peligrosa para el análisis.** `precioNeto` está en `monedaItem`, que
**no siempre es CLP**: la muestra trae `CLF` (UF). `precioNeto = 279,8` son 279,8 UF
≈ $10,6 M, no $280. Sólo `MontoTotalOC_PesosChilenos` viene convertido, y existe a nivel de
OC, **no de línea**. Un `AVG(precioNeto)` sin filtrar moneda da cifras sin sentido. Toda
tool de precios debe filtrar `monedaItem = 'CLP'` o convertir explícitamente, y declararlo
en su docstring.

### 5.3 Diseño del ingestor (recomendado)

```
descargar ZIP (con ETag) ──► extraer a temp ──► leer CSV en chunks
   └─ normalizar: encoding, decimales, fechas, RUT
        └─ escribir Parquet particionado: data/oc/anio=2024/mes=03/part.parquet
             └─ registrar en manifest.sqlite (dataset, periodo, etag, filas, sha256)
```

Consulta vía **DuckDB** sobre los Parquet: SQL analítico sin cargar todo a RAM, y
`read_parquet('data/oc/**/*.parquet')` con *predicate pushdown* por partición.

**Regla de oro**: el MCP **nunca** devuelve un archivo masivo a Claude. Devuelve el
**resultado de una agregación** — top-N, promedios, series. Un ZIP mensual puede ser
de decenas o cientos de MB; el contexto de Claude no es un data warehouse.

---

## 6. Capa de persistencia y caché

Tres almacenes locales, con propósitos distintos:

| Almacén | Contenido | Motor | TTL |
| :-- | :-- | :-- | :-- |
| `cache.sqlite` | Respuestas crudas de API V1/V2, indexadas por hash de (url + params) | SQLite | Compra ágil abierta: 15 min · Licitación cerrada/adjudicada: **infinito** · Listados por fecha pasada: infinito |
| `data/*.parquet` | Datos Abiertos normalizados | Parquet + DuckDB | por periodo, inmutable |
| `manifest.sqlite` | Cuota diaria, ETags, log de ingesta, errores | SQLite | — |

**Justificación**: la cuota diaria es el recurso más escaso del sistema. Un dato
histórico (licitación adjudicada de 2023) **jamás cambia** — volver a pedirlo a la
API es quemar cuota gratis. El backlog original no contempla caché en absoluto; es la
omisión de mayor impacto operativo.

---

## 7. Catálogo de herramientas MCP

Reorganizado por plano de datos. `[BL]` = ya estaba en el backlog; `[NUEVA]` = agregada aquí.

### Módulo 1 — Oportunidades (Plano A)

| Tool | Firma | Notas |
| :-- | :-- | :-- |
| `buscar_compras_agiles` `[BL HU-2.1]` | `(q?, region?, estado="publicada", publicado_desde?, publicado_hasta?, numero_pagina=1, tamano_pagina=50)` | Docstring **debe** advertir: no existe `codigo_organismo`; `q` e `id` son excluyentes |
| `obtener_detalle_compra_agil` `[BL HU-2.2]` | `(codigo)` | Resuelve TRAMPA 3 internamente: si `id_orden_compra != null`, hace el join a OC V1 y devuelve la OC real |
| `buscar_licitaciones` `[NUEVA]` | `(codigo? \| fecha?, estado?, codigo_organismo?, codigo_proveedor?)` | Faltaba en el backlog pese a ser la mitad del negocio. Proyección de campos obligatoria |
| `obtener_detalle_licitacion` `[BL HU-4.2]` | `(codigo)` | Ficha + oferentes + adjudicado |

### Módulo 2 — Inteligencia de mercado (Plano B)

| Tool | Firma | Reemplaza a |
| :-- | :-- | :-- |
| `analizar_precios_producto` `[NUEVA]` | `(texto_producto, desde?, hasta?, top_n=20)` | El caso de uso real detrás de HU-3.1 |
| `perfil_competidor` `[NUEVA]` | `(rut_o_nombre, desde?, hasta?)` | HU-3.1 — volumen, organismos, ticket promedio, líneas |
| `historial_compras_organismo` `[NUEVA]` | `(rut_o_nombre_organismo, desde?, hasta?, filtro_producto?)` | HU-3.2 |
| `desempeno_bioquimica` `[BL HU-4.1]` | `(desde?, hasta?, agrupar_por="mes"\|"organismo"\|"producto")` | Sobre datos propios ya ingeridos |
| `ingerir_datos_abiertos` `[NUEVA]` | `(dataset, periodo_desde, periodo_hasta)` | Admin: dispara descarga+ETL. Idempotente |

### Módulo 3 — Adjuntos

| Tool | Firma | Estado |
| :-- | :-- | :-- |
| `procesar_adjunto` `[BL HU-5.1/5.2]` | `(url_documento \| codigo_licitacion)` | **Evaluar delegar** — ver §12 |

### Módulo 4 — Infraestructura

| Tool | Firma |
| :-- | :-- |
| `verificar_estado_cuota` `[BL]` | `()` → requests hoy, 429 acumulados, salud de V1/V2, periodos ingeridos en el lake |

### Contrato de diseño para toda tool

1. Parámetros y retornos con modelos **Pydantic**. Sin `dict` sueltos.
2. Docstring que declare: cuándo usarla, cuándo **no**, y las trampas del endpoint.
   El docstring es el prompt que lee Claude — es código de producto, no comentario.
3. Toda tool acota su salida: `limit` por defecto + indicador de truncamiento
   (`"...N resultados más; use numero_pagina=2"`).
4. Nada de passthrough de JSON crudo. Proyección explícita de campos.

---

## 8. Optimización de tokens

✅ Decisión ya tomada en el prompt original, se mantiene: **TSV envuelto en XML**, no
Markdown.

```xml
<cuadro_evaluacion formato="TSV" filas="42" truncado="false">
oferente	precio_unitario	total	puntaje
BIOQUIMICA SPA	12500	1500000	98,5
COMPETIDOR LTDA	13900	1668000	91,0
</cuadro_evaluacion>
```

Reglas:

- Tabulaciones reales como separador; primera línea = header.
- Atributos `filas` y `truncado` siempre presentes → Claude sabe si le falta data.
- Sin pipes ni guiones de alineación de Markdown (ahorro ~40 % en tablas grandes).
- Aplica a: cuadros de evaluación, planillas Excel, listas de productos, resultados
  de consultas DuckDB.
- **No** aplica a respuestas de 1–3 campos; ahí el overhead de las etiquetas no se
  paga solo.
- Nulos: emitir celda vacía, no `None` ni `null` (menos tokens, menos ruido).

---

## 9. Procesamiento de adjuntos

Pipeline ✅ (heredado del prompt, con precisiones):

1. **Extracción nativa** — `pymupdf` (fitz) para texto, `pdfplumber` para tablas.
2. **Clasificación** — si un PDF de varias páginas rinde **< 100 caracteres**
   legibles ⇒ `DOCUMENTO_ESCANEADO`.
   ⚠️ Refinar: el umbral debe ser **por página** (`< 100 chars/página`), no total.
   Un PDF de 80 páginas con una carátula de texto pasa el filtro global y luego
   devuelve basura.
3. **OCR** — `pytesseract` o `easyocr`.
   ⚠️ **Dependencia de sistema, no de pip**: `pytesseract` es un *wrapper*; requiere
   el binario **Tesseract-OCR instalado en Windows** más el paquete de idioma `spa`.
   `easyocr` evita el binario pero arrastra PyTorch (~2 GB). **Decidir y documentar
   en el README** — un `pip install -r requirements.txt` no deja esto funcionando.
4. **Salida OK**:
   `<documento_adjunto tipo="OCR_PROCESADO"> … </documento_adjunto>`
5. **Salida fallida** — cadena literal:
   `⚠️ DOCUMENTO_ESCANEADO_ILEGIBLE: El archivo [nombre] es una imagen sin capa de texto seleccionable y el OCR no pudo procesarlo con suficiente precisión. Notifica al usuario de esta limitación y NO inventes el contenido.`

El punto 5 es una **defensa anti-alucinación** y no es negociable: sin ese mensaje,
Claude tiende a rellenar el contenido de bases que no pudo leer.

⚠️ **A VERIFICAR**: cómo se obtienen las URLs de los adjuntos. Ninguna de las APIs
documentadas expone las bases administrativas. Probablemente exijan *scraping* de
`mercadopublico.cl` o el endpoint no público de adjuntos. **Esto es un supuesto no
validado del backlog** y podría invalidar la ÉPICA 05 completa.

---

## 10. Errores, resiliencia y contratos

### 10.1 HTTP 429 — cuota diaria ✅

Mensaje literal de retorno (no lanzar excepción):

```
⚠️ Límite de cuota diaria alcanzado en la API de Mercado Público. El ticket se reiniciará a la medianoche.
```

**Ampliación necesaria**: el mensaje debe además **redirigir al Plano B**, porque casi
siempre hay una alternativa offline:

```
… Alternativa disponible: consulta histórica sobre Datos Abiertos (sin cuota) mediante
las herramientas del módulo de inteligencia de mercado.
```

### 10.2 Tabla de manejo de errores

| Condición | Acción del MCP |
| :-- | :-- |
| `429` | Mensaje de cuota + redirección a Plano B. Marcar el ticket agotado en `manifest` para no reintentar el resto del día |
| `401` | "Ticket ausente o inválido" — revisar `MERCADO_PUBLICO_TICKET`. **No** reintentar |
| `400` | Devolver el `errors[].mensaje` de la API tal cual + los params enviados, para que Claude corrija |
| `5xx` | Reintento con backoff exponencial + jitter, máx. 3 intentos |
| Timeout / red caída | Reintento (2), luego servir desde caché si existe, indicando `"dato en caché del {fecha}"` |
| `HTTP 200` con `success:"NOK"` | Tratar como error. Nunca devolver `payload` en ese caso |
| ZIP de Datos Abiertos 404 | "Periodo no publicado aún" — no es un error del sistema |

### 10.3 Requisitos transversales ausentes en el backlog

- **Rate limiting propio**: un semáforo de concurrencia (máx. 2–3 requests en vuelo).
  Martillar la API con 20 requests paralelos invita a bloqueo del ticket.
- **Timeouts explícitos** en cada request. `requests` sin `timeout` cuelga indefinidamente
  y congela el servidor MCP entero.
- **Logging estructurado** a archivo (no a `stdout`): en MCP sobre stdio, cualquier
  `print()` **corrompe el protocolo JSON-RPC**. Esta es una causa clásica de "el
  servidor no arranca en Claude Desktop".
- **Tests con fixtures grabadas** (`responses` / `vcr.py`): no se puede depender de la
  API en CI, la cuota se agota.

---

## 11. Datos de identidad pendientes (bloqueantes)

No se puede implementar la ÉPICA 04 sin esto:

✅ **Desbloqueado parcialmente por el spike.** El CSV de `oc-da` trae `CodigoProveedor`,
`RutSucursal`, `NombreProveedor` y `ActividadProveedor` **en la misma fila**. Basta filtrar
un mes cualquiera por el RUT de Bioquimica.cl para obtener su `CodigoProveedor` de la API V1
— **sin gastar cuota**. Lo mismo sirve para resolver los RUT/códigos de cada competidor.

| Dato | Estado | Cómo obtenerlo |
| :-- | :-- | :-- |
| RUT de Bioquimica.cl | ❌ **FALTA** — único bloqueante real | Dato de negocio; hay que preguntarlo |
| `CodigoProveedor` de Bioquimica.cl en MP | ✅ derivable | `grep` del RUT en `oc-da` ⇒ columna `CodigoProveedor` |
| Razón social exacta como aparece en MP | ✅ derivable | columna `NombreProveedor` de la misma fila |
| Lista de competidores objetivo | ✅ derivable | ranking por `codigoProductoONU`/`RubroN2` de nuestro rubro en `oc-da` — se descubren solos |
| Rubros / palabras clave del catálogo | ⚠️ parcial | Ya existe el MCP de catálogo — ver §12 |

Estos cinco datos deben ir a un `config/identidad.toml`, versionado, **sin secretos**.

---

## 12. Servidores MCP ya conectados: evitar duplicar

El entorno de trabajo ya tiene MCPs activos que se solapan con este backlog:

| MCP existente | Solapa con | Recomendación |
| :-- | :-- | :-- |
| `MCP-Catalogo-BQ` (catálogo de productos, precios base, stock) | El cruce "necesidad del organismo ↔ catálogo propio" de HU-3.2 | **No reimplementar.** Este MCP devuelve el requerimiento; Claude cruza contra el MCP de catálogo. Mantener la separación de responsabilidades |
| `optimizador-documentos` (`procesar_documento`, `leer_documento_procesado`) | **ÉPICA 05 completa** (OCR, TSV, adjuntos) | **Evaluar seriamente delegar.** Si ya resuelve PDF escaneado → texto, la ÉPICA 05 se reduce a "descargar el adjunto y pasarle la ruta". Ahorra el infierno de Tesseract-en-Windows y ~1 sprint |
| `LicitaLab` (`findOpportunityTool`, documentos de oportunidad) | Módulo 1 (búsqueda de oportunidades) | Fuente comercial paralela. Útil como **verificación cruzada** de que la implementación propia no pierde oportunidades. No es reemplazo: no da precios históricos masivos |

**Acción concreta**: antes de abrir el Sprint 3, probar `optimizador-documentos`
contra 3 PDFs reales de bases (uno digital, uno escaneado legible, uno escaneado
malo). Si pasa, la ÉPICA 05 se recorta a una sola historia.

---

## 13. Stack, layout y decisiones cerradas

### 13.0 ⚠️ Despliegue remoto — el cambio de mayor impacto

**El usuario consume por claude.ai, no por Claude Desktop.** La HU-6.2 del backlog original
(`claude_desktop_config.json`, transporte stdio) **no aplica**: claude.ai monta los MCP
como **conectores remotos por HTTP**, con autenticación.

Lo que esto cambia:

| Aspecto | Backlog original (stdio local) | **Realidad (claude.ai remoto)** |
| :-- | :-- | :-- |
| Transporte | stdio | **HTTP** (streamable / SSE) |
| Configuración | `claude_desktop_config.json` | **Conector** registrado en claude.ai |
| Autenticación | ninguna (proceso local) | **obligatoria** — el endpoint queda expuesto |
| Dónde vive el lake | disco del notebook | **en el servidor** — el notebook no participa |
| Infraestructura | ninguna | **Railway** (decidido 2026-08-05), con disco persistente |
| Entregable HU-6.2 | archivo JSON | Dockerfile + servicio + Volume + auth |

**Consecuencia crítica**: el data lake no puede vivir en el notebook. Un MCP remoto sólo
puede consultar lo que está junto a él.

**Railway específicamente — dos restricciones verificadas que cambian el diseño:**

1. El filesystem del contenedor es **efímero**: cualquier archivo escrito en runtime (el
   lake, `manifest.sqlite`, `cache.sqlite`) **se borra en cada redeploy** salvo que se monte
   un **Volume** persistente.
2. **Un Volume es 1:1 con un servicio** — Railway no soporta volúmenes compartidos entre
   dos servicios. La ingesta **no puede ser un servicio Railway separado** del servidor MCP
   (verían lagos distintos); debe ser una tarea en background dentro del **mismo proceso**.
   Ver HU-7.3 en el backlog para los criterios completos.

**Dimensionamiento** con las decisiones ya tomadas (20 meses, filtro por rubro):

- Sin filtrar: ~1,84 M filas/mes × 20 ≈ **37 M filas**, ~48 GB en CSV.
- Los rubros del catálogo son una fracción del total. En la muestra de `oc-da/2026-6`,
  `Equipamiento para laboratorios` son 21.531 de 437.538 líneas ≈ **5 %**; sumando los
  otros 5 rubros, del orden de **10-12 %**.
- Estimación del lake en Parquet+zstd: **1,5–4 GB**. Un Volume de Railway de **5 GB** cubre
  lake + SQLite con margen, a ~US$0,15/GB/mes ⇒ **< US$1/mes**.
- ⚠️ La **ingesta** sí necesita espacio transitorio: hay que descargar y descomprimir ZIP
  de hasta 1,34 GB antes de filtrar. Ese scratch va al `/tmp` **efímero** del contenedor,
  no al Volume — se borra solo, procesando por streaming y descartando el ZIP en cuanto se
  escribe el Parquet (HU-2.2). El Volume pagado se mantiene chico.

**Seguridad** (endpoint público): autenticación obligatoria; el servidor no debe exponer
SQL arbitrario a Claude — sólo las tools tipadas de §7, con límites de filas y de tiempo
por consulta. Los datos son públicos, así que la exposición no es de confidencialidad sino
de **abuso de recursos**: una consulta sin `LIMIT` sobre 37 M de filas tumba el servicio.

**Recomendación de secuencia**: construir con las capas separadas (`lake/` y `clientes/`
sin dependencia del transporte) y montar el servidor HTTP desde el inicio, corriéndolo en
local durante el desarrollo. Así el paso a producción es despliegue, no reescritura.

### 13.1 Decisión pendiente: qué `FastMCP`

⚠️ **Ambigüedad en el prompt original.** Dice
`from mcp.server.fastmcp import FastMCP` (el SDK **oficial** de Anthropic) pero lo
llama "framework `FastMCP`", que también es el nombre de un **paquete de terceros**
(`pip install fastmcp`, v2.x) con API distinta y más features.

**Recomendación**: SDK oficial (`pip install mcp`) — menos dependencias, alineado con
la especificación, suficiente para tools sencillas. Fijar la decisión en el README y
no mezclar imports.

### 13.2 Dependencias

```
mcp                # SDK oficial MCP
httpx              # cliente HTTP async, timeouts sanos (mejor que requests aquí)
pydantic>=2        # validación de I/O de tools
duckdb             # motor analítico sobre Parquet
pyarrow            # escritura Parquet
pandas             # ETL de los CSV de Datos Abiertos
openpyxl           # Excel adjuntos
pymupdf            # extracción de texto PDF
pdfplumber         # extracción de tablas PDF
pytesseract        # OCR (⚠️ requiere binario Tesseract + idioma spa)
tenacity           # retry/backoff
```

> `httpx` en lugar de `requests`: soporta async (FastMCP es async), timeouts por
> defecto más seguros, y misma ergonomía.

### 13.3 Layout propuesto

```
MCP-MercadoPublico/
├─ src/mcp_mercadopublico/
│  ├─ server.py              # registro de tools, único punto de entrada
│  ├─ config.py              # env vars, identidad.toml
│  ├─ clientes/
│  │  ├─ base.py             # httpx, retry, timeouts, contador de cuota, caché
│  │  ├─ api_v1.py           # licitaciones + OC (ticket en query)
│  │  └─ api_v2.py           # compra ágil (ticket en header)
│  ├─ lake/
│  │  ├─ descarga.py         # ZIP + ETag
│  │  ├─ etl.py              # CSV → normalización → Parquet
│  │  └─ consultas.py        # SQL DuckDB para las tools analíticas
│  ├─ documentos/            # PDF/Excel/OCR (o adaptador a optimizador-documentos)
│  ├─ formato/
│  │  └─ tsv_xml.py          # serializador TSV+XML, con truncado
│  └─ modelos/               # esquemas Pydantic
├─ data/                     # Parquet particionado — .gitignore
├─ config/identidad.toml
├─ docs/esquema-datos-abiertos.md   # salida del spike §5.2
├─ tests/fixtures/           # respuestas grabadas de API y CSV de muestra
├─ requirements.txt
└─ claude_desktop_config.json.example
```

### 13.4 Estándares

PEP 8 · tipado estricto (`typing`, `from __future__ import annotations`) ·
sin `print()` en el proceso del servidor · secretos sólo por variable de entorno.

---

## 14. Roadmap revisado

Cambios respecto de la hoja de ruta original y por qué:

| Sprint | Original | **Revisado tras el spike y el objetivo declarado** | Motivo del cambio |
| :-- | :-- | :-- | :-- |
| **0** | *(no existía)* | ✅ **HECHO** — Datos Abiertos caracterizado (`docs/esquema-datos-abiertos.md`), watchlist validada y perfilada, rubros derivados del catálogo (`config/identidad.toml`) | Los bloqueantes de datos están resueltos, salvo el RUT propio |
| **1** | ÉP-01 + ÉP-02 | **Ingestor + lake**: descarga condicional por `ETag`, ETL con las 15 trampas de §3, filtro por los 6 `RubroN1`, Parquet particionado, manifest | Es la base de todo el valor. Sin lake no hay ninguna tool útil |
| **2** | ÉP-03 + ÉP-04 | **Tools de inteligencia competitiva**: `perfil_competidor`, `radar_competencia`, `benchmark_precio`, `head_to_head` | Objetivo declarado #1. Requiere el RUT propio para `head_to_head` |
| **3** | ÉP-05 | **Tools de calibración de oferta**: `precio_para_ganar`, `criterios_que_deciden`, `postmortem`, `perfil_comprador` | Objetivo declarado #2. Es lo que convierte el análisis en más adjudicaciones |
| **4** | ÉP-06 | **Servidor HTTP + despliegue + auth + conector claude.ai** + system prompt | Reemplaza a HU-6.2 (`claude_desktop_config.json`), que no aplica — ver §13.0 |
| — | — | ~~ÉP-05 (OCR/adjuntos)~~ **fuera de alcance** | No sirve al objetivo declarado. Si vuelve, delegada a `optimizador-documentos` |
| — | — | ~~Búsqueda de oportunidades en tiempo real~~ **fuera de alcance** | Ya la cubre LicitaLab (§12) |

> El Sprint 4 puede adelantarse parcialmente: conviene levantar el esqueleto HTTP desde el
> Sprint 1 y correrlo en local, para que el despliegue final sea configuración y no
> reescritura.

**Nota sobre la ÉPICA 01 original**: las HU-1.1 y HU-1.2 son correctas pero
insuficientes. Un servidor MCP productivo necesita, además: caché, contador de cuota,
timeouts, rate limiting, logging a archivo y tests con fixtures. Sugerido subir esas
seis a criterios de aceptación explícitos.

---

## 15. Preguntas abiertas

1. **¿Cuál es el `CodigoProveedor` y el RUT de Bioquimica.cl en MP?** — bloquea ÉP-04.
2. **¿De dónde salen las URLs de los adjuntos de bases?** — ninguna API documentada las
   expone. Si exige scraping, la ÉP-05 cambia de naturaleza (fragilidad, ToS).
3. **¿Cuánta historia se necesita?** 2 años (~24 ZIP) vs. todo (~6 años, ~72 ZIP).
   Define el tamaño del lake y la duración de la ingesta inicial.
4. **¿Reingesta programada?** El mes en curso se actualiza; hace falta un job que
   re-ingiera el periodo abierto. ¿Manual vía tool, o `cron`?
5. **¿Multiusuario?** Si más de una persona usa el MCP, un solo ticket comparte cuota.
   ¿Un ticket por usuario, o un servidor central?
6. **¿Qué se hace con `LicitaLab`?** ¿Fuente redundante de verificación, o se descarta
   una vez que este MCP esté maduro?

---

*Última consolidación: 2026-08-05. Documentos fuente conservados en `Backlog/` para trazabilidad.*
