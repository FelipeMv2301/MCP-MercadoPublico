# 📌 Backlog de Producto — MCP Mercado Público (Bioquimica.cl)

**Versión:** 2.0 · **Actualizado:** 2026-08-05
**Reemplaza** la v1.0 de este archivo. Los cambios respecto de la v1 están justificados con
mediciones, no con supuestos — ver §0.3.

## Documentos de referencia (leer antes de tomar cualquier historia)

| Documento | Contenido |
| :-- | :-- |
| [`REFERENCIA-MCP-MercadoPublico.md`](REFERENCIA-MCP-MercadoPublico.md) | Referencia técnica única: APIs, trampas, arquitectura, decisiones |
| [`../docs/esquema-datos-abiertos.md`](../docs/esquema-datos-abiertos.md) | Esquema real de los 3 datasets (222 columnas), 15 trampas de parsing verificadas |
| [`../config/identidad.toml`](../config/identidad.toml) | Identidad, watchlist perfilada, rubros de ingesta, brechas |

---

## 0. Marco del proyecto

### 0.1 Objetivo (declarado por el usuario)

Entender el movimiento de los principales competidores mediante conversación natural en
**claude.ai**, para armar mejores ofertas a licitaciones y compras ágiles.

### 0.2 Decisiones cerradas

| # | Decisión | Valor | Estado |
| :-- | :-- | :-- | :-- |
| D1 | Consumo | **Remoto por HTTP para claude.ai** (no Claude Desktop / stdio) | ✅ cerrada |
| D2 | Historia a ingerir | **2025-1 → 2026-8** (~20 meses) | ✅ cerrada |
| D3 | Alcance de rubros | **Derivado del catálogo BQ** → 7 `RubroN1` | ✅ cerrada |
| D4 | Filtro de ingesta | **Por rubro**, conservando TODOS los proveedores | ✅ cerrada (§0.4) |
| D5 | Watchlist de 33 RUT | Lista de **prioridad**, no filtro de datos | ✅ cerrada (§0.4) |
| D6 | Framework MCP | SDK oficial (`pip install mcp`), **no** el paquete de terceros `fastmcp` v2 | ✅ cerrada |
| D7 | Cliente HTTP | `httpx` (async, timeouts sanos) en vez de `requests` | ✅ cerrada |
| D8 | Motor analítico | Parquet particionado + DuckDB | ✅ cerrada |
| D9 | Fuente primaria | **`COT` (compra ágil)** por delante de `lic-da` | ✅ cerrada (§0.3) |
| D10 | Fuera de alcance | OCR/adjuntos · búsqueda de oportunidades en tiempo real | ✅ cerrada |

### 0.3 Hechos medidos que reordenaron el backlog

Todos verificados sobre `oc-da/2026-6`, `lic-da/2026-6` y `COT_2026-06`:

| Hallazgo | Medición | Consecuencia en el backlog |
| :-- | :-- | :-- |
| **El negocio entra por compra ágil** | 76,4 % del monto de OC tiene `ProcedenciaOC = NA`; sólo 19,5 % viene de licitación pública | `COT` pasa a fuente primaria (D9). ÉP-05 prioriza compra ágil |
| **Win rate bajo y medible** | 40 líneas ganadas / 96 perdidas = **29,4 %** en 26 cotizaciones/mes | Las 96 líneas perdidas son la métrica de éxito del proyecto |
| **La watchlist no son los rivales reales** | 0/10 coincidencias en licitaciones · 2/12 en compra ágil | ÉP-04 se construye sobre **descubrimiento por co-participación**, no sobre la lista |
| **Historial propio demasiado delgado** | 174 líneas en 81 códigos ONU; **67 % con una sola línea** | Todas las tools son *market-centric*. Prohibido derivar estadísticas del historial propio |
| **Mercado abundante en los mismos productos** | 13.308 líneas/mes en esos 81 códigos → ~266.000 en 20 meses; mediana 9 proveedores/código | El benchmark es viable. Devolver siempre el `n` |
| **Material didáctico en rubro contraintuitivo** | Está bajo `RubroN1 = "Instrumentos musicales, juegos, juguetes, artesanía"` | El filtro de rubro se deriva del catálogo, nunca de la intuición |
| **Escala real vs. watchlist** | Bioquimica $44,9 M/mes vs. Arquimed $4.218 M/mes (**94x**) | Segmentar la watchlist en ligas; no comparar precios entre ligas |
| **Esquema de los CSV cambia** | LIC 105→110 columnas; OC renombró una; **el índice absoluto se desplaza** con cada inserción | ÉP-08 (mantención) deja de ser opcional |
| **Periodos cerrados se reescriben** | `oc-da/2026-6` regenerado 2 meses tras el cierre | Reingesta por `ETag`, no por "periodo abierto" |

### 0.4 Desviación registrada respecto de una instrucción del usuario

El usuario pidió ingerir *"2025-2026, de los siguientes RUT"* (33 RUT). **Se implementa el
filtro por rubro y no por RUT**, con la watchlist como lista de prioridad.

**Motivo medido:** la watchlist captura sólo el **16,3 %** del monto de los rubros de
laboratorio ($4.504 M de $27.691 M en 2026-06). Filtrar la ingesta por esos RUT haría
imposible:

- calcular distribuciones de precio (faltarían los demás oferentes de cada licitación);
- detectar entrantes nuevos (por definición no están en una lista previa);
- saber quién ganó cuando el ganador está fuera de la lista — que es el caso mayoritario.

Además, el filtro por rubro **ya** reduce el lake al 10-12 % del volumen, así que agregar el
filtro por RUT no ahorra espacio relevante y sí destruye capacidad analítica.

> **Reversible en una línea**: `config/identidad.toml → [ingesta] filtro`. Si el usuario
> prefiere el filtro estricto por RUT, se pierden HU-4.2, HU-5.1 y HU-5.2.

### 0.5 Identidad resuelta

| Dato | Valor | Origen |
| :-- | :-- | :-- |
| RUT | `76.563.320-6` | usuario; DV validado mod-11 |
| `CodigoProveedor` | `1202804` | derivado de `oc-da/2026-6` (sin gastar cuota) |
| Razón social en MP | `BIOQUIMICA.CL.S.A.` | ídem |

---

## 1. Resumen ejecutivo del backlog

| Épica | Nombre | HU | Prioridad | Bloquea a |
| :--- | :--- | :-: | :-: | :-- |
| **ÉP-01** | Fundaciones del servicio | 4 | 🔴 Alta | todas |
| **ÉP-02** | Ingesta y Data Lake | 5 | 🔴 Alta | ÉP-03…05 |
| **ÉP-03** | Puente catálogo ↔ Mercado Público | 2 | 🔴 Alta | ÉP-05 |
| **ÉP-04** | Inteligencia competitiva | 4 | 🔴 Alta | — |
| **ÉP-05** | Calibración de ofertas | 4 | 🔴 Alta | — |
| **ÉP-06** | Plano A — API en línea (complemento) | 3 | 🟡 Media | — |
| **ÉP-07** | Despliegue remoto y conector claude.ai | 4 | 🔴 Alta | uso real |
| **ÉP-08** | Mantención y observabilidad | 3 | 🟡 Media | continuidad |
| ~~ÉP-09~~ | ~~OCR y adjuntos~~ | — | ⚪ Congelada | — |

**Total: 29 historias.**

---

## 🔴 ÉPICA 01 — Fundaciones del servicio

### HU-1.1 · Configuración tipada y carga de identidad
**Como** desarrollador, **quiero** un módulo de configuración que lea `config/identidad.toml`
y las variables de entorno con validación Pydantic, **para** que ninguna ruta, RUT o rubro
quede hardcodeado.

**Criterios de aceptación**
- [ ] `config.py` expone un objeto `Settings` validado con Pydantic v2.
- [ ] Lee `MERCADO_PUBLICO_TICKET` de entorno. **Nunca** desde el TOML.
- [ ] Parsea `config/identidad.toml`: `[nosotros]`, `[ingesta]`, `[competencia]`, `[brechas]`.
- [ ] Valida los RUT con **dígito verificador mod-11** al cargar; los inválidos se registran
      como *warning* con el DV esperado, no se descartan en silencio.
      *(Caso conocido: `77.814.808-2` → DV correcto `0`.)*
- [ ] Falla al arrancar si `[nosotros].rut` está vacío, con mensaje explícito.
- [ ] Normalizador de RUT reusable: `76.563.320-6` → `76563320-6` (para joins).

### HU-1.2 · Logging a archivo (nunca a stdout)
**Como** operador, **quiero** logging estructurado a archivo, **para** que el protocolo MCP
no se corrompa y los fallos de ETL queden auditables.

**Criterios de aceptación**
- [ ] Logging estructurado (JSON por línea) a archivo con rotación.
- [ ] **Cero `print()` en el proceso del servidor.** Un test de CI hace *grep* del código
      fuente y falla si encuentra `print(` fuera de `tests/` y `scripts/`.
      *(Razón: en transporte stdio cualquier `print` rompe el JSON-RPC. Aunque D1 sea HTTP,
      la regla se mantiene por si se agrega stdio y porque contamina los logs.)*
- [ ] Cada evento de ETL registra: dataset, periodo, filas leídas, filas escritas, filas
      descartadas y motivo.

### HU-1.3 · Esqueleto del servidor HTTP desde el día 1
**Como** desarrollador, **quiero** el servidor MCP sobre HTTP funcionando en local desde el
inicio, **para** que el paso a producción sea despliegue y no reescritura.

**Criterios de aceptación**
- [ ] Servidor MCP con SDK oficial (D6), transporte **HTTP streamable**.
- [ ] Corre en local (`localhost`) y responde el *handshake* MCP.
- [ ] Capas desacopladas del transporte: `lake/` y `clientes/` no importan nada de MCP.
- [ ] Una tool trivial (`verificar_estado`) responde, para validar el circuito completo.

### HU-1.4 · Arnés de pruebas con fixtures grabadas
**Como** desarrollador, **quiero** tests que no toquen la red, **para** que CI no dependa de
ChileCompra ni consuma cuota.

**Criterios de aceptación**
- [ ] `tests/fixtures/` con los headers y muestras del spike ya obtenidas:
      `cot1_head.bin`, `oc_head.bin`, `lic_head.bin`, `lic2015.bin`, `lic2019.bin`,
      `oc2010.bin`, `oc2019.bin` (mover desde el scratchpad de la sesión).
- [ ] Un test por cada una de las **15 trampas de parsing** de `docs/esquema-datos-abiertos.md §3`.
- [ ] Test de regresión de esquema: compara el header ingerido contra el esperado y falla
      ante columnas desconocidas (ver HU-8.1).
- [ ] Ningún test hace peticiones de red.

---

## 🔴 ÉPICA 02 — Ingesta y Data Lake

> Fundamento completo en `docs/esquema-datos-abiertos.md`. **Nada en esta épica debe
> reinventarse por intuición: el esquema ya está caracterizado.**

### HU-2.1 · Descarga condicional por `ETag`
**Como** ingestor, **quiero** descargar los ZIP solo cuando cambiaron, **para** no re-bajar
GB inútilmente y detectar las reescrituras retroactivas.

**Criterios de aceptación**
- [ ] Builder de URL con **regla por dataset** (trampa verificada):
      ```python
      oc  → …/oc-da/{anio}-{mes}.zip        # SIN cero-padding
      lic → …/lic-da/{anio}-{mes}.zip       # SIN cero-padding
      cot → …/trnspchc/COT_{anio}-{mes:02d}.zip  # CON cero-padding
      ```
      Un test verifica que `oc-da/2026-06` (con padding) **no** se genere jamás.
- [ ] `HEAD` con `If-None-Match` usando el `ETag` guardado; `304` ⇒ no hacer nada.
- [ ] `ETag` y `Last-Modified` persistidos por `(dataset, periodo)` en el manifest.
- [ ] **Reingesta de periodos cerrados** cuando el `ETag` cambie. No asumir inmutabilidad.
- [ ] `404` se registra como "periodo no publicado", no como error del sistema.
- [ ] Timeout explícito y reintentos con backoff exponencial + jitter (`tenacity`).

### HU-2.2 · Extracción robusta del ZIP
**Como** ingestor, **quiero** extraer los CSV sin asumir nombres ni cantidades, **para** que
`COT` y sus múltiples archivos no rompan el pipeline.

**Criterios de aceptación**
- [ ] Iterar `zipfile.namelist()`. **Prohibido** derivar el nombre interno del externo
      (verificado: `oc-da/2026-6.zip` contiene `2026-6.csv`; `COT_2026-06.zip` contiene
      `COT1_2026-06.csv` y `COT2_2026-06.csv`).
- [ ] Soportar **N** archivos por ZIP, no exactamente 2: `COT1_` tiene 620.893 filas y
      ChileCompra corta bajo ~1 M por compatibilidad con Excel, así que en meses de mayor
      volumen puede aparecer `COT3_`.
- [ ] Los múltiples CSV de un mismo periodo se **concatenan** (son continuación, no cortes
      semánticos distintos).
- [ ] Procesar por streaming y liberar el ZIP/temporales al escribir el Parquet.
      *(Presupuesto: `COT_2026-06` son 78 MB comprimidos → 1,34 GB descomprimidos, ratio 17:1.)*

### HU-2.3 · Normalización — las 15 trampas
**Como** ingestor, **quiero** normalizar los CSV correctamente, **para** que ningún análisis
posterior se construya sobre datos corridos o mal tipados.

**Criterios de aceptación** (cada ítem tiene test propio en HU-1.4)
- [ ] Encoding `latin-1` explícito, sin BOM. *(UTF-8 lanza `UnicodeDecodeError`.)*
- [ ] `csv.reader`/`DictReader` con `delimiter=';'`, `quotechar='"'`,
      `field_size_limit` elevado.
- [ ] **Mapeo de columnas por NOMBRE, jamás por posición.** *(Verificado con test: en OC,
      `idPlanDeCompra` [idx 12, 2019] fue reemplazada por `Codigo_ConvenioMarco` [idx 58,
      2026] — mismo conteo de columnas, significado distinto en la misma posición. En LIC,
      las 6 columnas nuevas desplazan el índice absoluto de todo lo posterior aunque el
      orden relativo se mantenga. Leer por índice corre los datos en silencio.)*
- [ ] **Parser CSV real.** Prohibido `split("\n")` o contar líneas: hay newlines embebidos
      en `Descripcion/Obervaciones` (OC) y `DetalleCotizacion` (COT).
- [ ] Decimales con **coma** → punto: `MontoTotalOC`, `MontoTotalOC_PesosChilenos`,
      `TotalNetoOC`, `Impuestos`, `precioNeto`, `totalLineaNeto`.
- [ ] Nulos: `"NA"`, `""` y `1900-01-01` → `NULL`.
- [ ] **Sentinela en campos de texto**: si `DireccionVisita`/`DireccionEntrega` traen
      `1900-01-01`, forzar `NULL` (bug del dataset).
- [ ] Renombre a `snake_case` conservando los typos del origen documentados:
      `MontoTotalDisponble`, `NombreroductoGenerico`, `Descripcion/Obervaciones`,
      `Nombre producto genrico`. **No "corregirlos"** en la lectura.
- [ ] `FormaPago` (código) y `Forma de Pago` (texto) son **columnas distintas**: no deduplicar.
- [ ] Conservar o descartar deliberadamente `DescripcionCriteriosRequisitosSociales.1`
      (el sufijo `.1` viene literal en el archivo); decisión documentada en código.
- [ ] RUT normalizado sin puntos para joins; se conserva el original para mostrar.
- [ ] Región: mapa texto ↔ código 1-16 con `strip()`
      *(el CSV trae `"Región de Tarapacá  "`, la API V2 usa `13`)*.
- [ ] **Marcar `monedaItem`/`TipoMonedaOC` ≠ CLP** en una columna booleana `es_clp`.

### HU-2.4 · Filtro por rubro y escritura en Parquet
**Como** ingestor, **quiero** conservar sólo los rubros del catálogo BQ, **para** que el lake
quepa en un VPS chico sin perder contexto de mercado.

**Criterios de aceptación**
- [ ] Filtro por los **7 `RubroN1`** de `config/identidad.toml`:
      Equipamiento para laboratorios · Productos químicos industriales ·
      Instrumentos musicales/juegos/juguetes/artesanía *(material didáctico)* ·
      Muebles y mobiliario · **Artículos para estructuras** ·
      Educación/formación *(a verificar)* · Servicios de producción industrial *(a verificar)*.
- [ ] **Se conservan TODOS los proveedores** dentro de esos rubros (D4/§0.4).
- [ ] Parquet particionado `data/{dataset}/anio=YYYY/mes=M/`, compresión `zstd`.
- [ ] Chunks de 100–250 k filas para acotar RAM con archivos de 736 MB.
- [ ] **Esquema unión versionado**: el destino usa el superconjunto de columnas; los periodos
      que no traen una columna la escriben `NULL`.
- [ ] Log explícito de cuántas filas se descartaron por el filtro de rubro.
      *(Nunca truncar en silencio.)*
- [ ] Presupuesto esperado: **1,5–4 GB** para 20 meses. Medir tras el primer periodo y
      recalibrar el alcance si se desvía.

### HU-2.5 · Manifest de ingesta
**Como** operador, **quiero** un registro de qué se ingirió y en qué estado, **para** poder
reingerir de forma idempotente y auditar.

**Criterios de aceptación**
- [ ] `manifest.sqlite` con: `dataset`, `periodo`, `etag`, `last_modified`, `filas_leidas`,
      `filas_escritas`, `schema_version`, `sha256`, `ingerido_en`, `estado`.
- [ ] Reingerir un periodo ya cargado es **idempotente** (reemplaza su partición, no duplica).
- [ ] Tool `ingerir_datos_abiertos(dataset, periodo_desde, periodo_hasta)` expuesta para
      disparar la carga; reporta progreso y resumen.

---

## 🔴 ÉPICA 03 — Puente catálogo ↔ Mercado Público

> **Riesgo técnico #1 del proyecto.** El MCP de catálogo devuelve `sku`,
> `nombre_comercial`, `especificaciones_tecnicas`, `precio_lista_neto`,
> `disponible_para_venta` — **sin código ONU**. Sin este puente, todas las tools de precio
> comparan mal en silencio.

> ⚠️ **Corrección de diseño (2026-08-05).** La v1 de estas dos historias asumía que
> *nuestro servidor* debía llamar al MCP de catálogo para cruzar SKU↔ONU. Un MCP no invoca
> tools de otro MCP en runtime — cada uno expone tools a Claude, y es **Claude** quien tiene
> ambos conectores en la misma conversación y puede cruzar la información él mismo. El
> bootstrap manual ("yo corro un script que llama al catálogo una vez") tampoco es
> necesario: el mapeo se construye **progresivamente, en conversaciones reales**, con
> Claude confirmando y persistiendo cada match.

### HU-3.1 · Consulta del historial propio por texto o código ONU
**Como** Claude, **quiero** consultar qué vendió Bioquimica.cl y con qué código ONU quedó
clasificado, **para** cruzarlo yo mismo contra lo que ya sé del catálogo (otro conector) sin
que el servidor dependa de él.

**Criterios de aceptación**
- [ ] Tool `buscar_producto_en_historial(texto?, codigo_onu?, solo_propio=true, limite=20)`.
- [ ] Busca sobre `NombreroductoGenerico`/`codigoProductoONU` en el lake de `oc` (y
      `ProductoCotizado`/`CodigoProducto` en `cot`), filtrando por
      `CodigoProveedor = nosotros.codigo_proveedor` cuando `solo_propio=true`.
      *(Los compradores del Estado ya clasificaron estos productos al comprarlos — es
      etiquetado gratis, sin fuzzy matching de por medio.)*
- [ ] Devuelve, por candidato: `codigo_onu`, texto asociado, `n_apariciones`,
      `n_vendedores_distintos` — para que Claude juzgue qué tan bien calza.
- [ ] `solo_propio=false` amplía la búsqueda a todo el mercado (útil para un producto que
      Bioquímica no ha vendido todavía, pero el mercado sí clasifica).
- [ ] Si el lake está vacío (antes de la primera ingesta en Railway), devuelve lista vacía
      con una nota explícita — no un error.

### HU-3.2 · Mapeo SKU↔ONU persistido, confirmado por Claude en conversación
**Como** Claude, **quiero** guardar un mapeo SKU↔ONU una vez que lo confirmo cruzando el
catálogo y el historial, **para** no tener que re-derivarlo cada conversación.

**Criterios de aceptación**
- [ ] Tool `registrar_mapeo_sku_onu(sku, codigo_onu, confianza, nota?)` — Claude la llama
      **después** de cruzar el catálogo (otro conector) con `buscar_producto_en_historial`
      (HU-3.1) en la misma conversación.
- [ ] Persistido en `data/mapeos.sqlite` (WAL, mismo patrón que `manifest.sqlite`), no en
      código ni en `identidad.toml` — crece con el uso real, no con un bootstrap de una vez.
- [ ] Tool `resolver_producto(sku_o_texto)` → `{codigo_onu, metodo, confianza}`. Orden de
      resolución: mapeo persistido exacto → código ONU literal si el input ya es uno →
      `sin_resolucion` (no inventa un ONU por fuzzy matching automático — ese trabajo es de
      Claude vía HU-3.1, no de una heurística de texto en el servidor).
- [ ] Toda tool de precios (ÉP-05) incluye `metodo_resolucion` y `confianza` en su salida.
- [ ] Si `confianza != "alta"`, la salida lo dice en texto para que Claude lo advierta al
      usuario. **No** devolver un número sin ese contexto.

---

## 🔴 ÉPICA 04 — Inteligencia competitiva

> Regla transversal de la épica: **market-centric**. Prohibido derivar estadísticas del
> historial propio (67 % de nuestros productos tiene 1 sola línea/mes).

### HU-4.1 · Descubrimiento de rivales por co-participación
**Como** estratega, **quiero** que el sistema me diga contra quién competimos realmente,
**para** no depender de una lista hecha de memoria.

**Criterios de aceptación**
- [ ] Tool `descubrir_rivales(desde?, hasta?, canal?)`.
- [ ] Método: identificar los `CodigoCotizacion` (COT) y `CodigoExterno` (LIC) donde
      participó `76.563.320-6`, y listar los demás `RUTProveedor` presentes.
- [ ] Devuelve: RUT, razón social, nº de cruces, canal, y **si está o no en la watchlist**.
- [ ] Segmenta por canal — los universos son distintos:
      compra ágil (rival #1 real: `76.502.658-K`, 61 cruces) vs.
      licitaciones de material didáctico (Tepullin, Vercon, PETIWI…).
- [ ] Marca explícitamente a los rivales **no listados** en la watchlist como hallazgos nuevos.
- [ ] Docstring que advierta a Claude: la watchlist es complementaria, esta tool es la fuente
      de verdad sobre quién compite.

### HU-4.2 · Perfil de competidor
**Como** estratega, **quiero** el perfil completo de un competidor, **para** entender su
volumen, su territorio y su tasa de éxito.

**Criterios de aceptación**
- [ ] Tool `perfil_competidor(rut|nombre, desde?, hasta?)`.
- [ ] Devuelve: monto total (**solo CLP**, ver §Riesgo R1), nº de líneas, evolución mensual,
      top organismos compradores, top `RubroN2`, top productos, ticket promedio,
      **win rate** (líneas seleccionadas / ofertadas), tamaño de empresa (`Tamano`).
- [ ] Declara la **liga** (A: instrumental de alto ticket a hospitales / B: suministros a
      universidades) y advierte si no es comparable con el catálogo BQ.
      *(Arquimed es 94x Bioquimica: comparar precios entre ligas produce conclusiones falsas.)*
- [ ] Incluye `n` de cada agregación.

### HU-4.3 · Radar de movimiento
**Como** estratega, **quiero** ver qué cambió en el rubro respecto del periodo anterior,
**para** detectar entrantes y competidores que aceleran.

**Criterios de aceptación**
- [ ] Tool `radar_competencia(rubro?, periodo, comparar_con?)`.
- [ ] Devuelve deltas de monto y de líneas por proveedor entre dos periodos.
- [ ] Identifica **entrantes** (sin actividad en el periodo previo) y **salientes**.
- [ ] Ordena por magnitud del cambio, no por tamaño absoluto — un entrante chico que crece
      3x importa más que un grande estable.

### HU-4.4 · Head-to-head contra un competidor
**Como** estratega, **quiero** ver dónde nos cruzamos con un rival y quién ganó, **para**
entender la diferencia concreta.

**Criterios de aceptación**
- [ ] Tool `head_to_head(rut_competidor, desde?, hasta?)`.
- [ ] Usa `CodigoProveedor = 1202804` / RUT `76.563.320-6` para el lado propio.
- [ ] Devuelve, por cada cruce: código de licitación/cotización, producto, nuestro precio,
      el suyo, **diferencia %**, quién fue seleccionado y el criterio declarado.
- [ ] Resumen: nº de cruces, cuántos ganamos, diferencia mediana de precio.
- [ ] Advierte cuando el `n` es demasiado bajo para concluir.

---

## 🔴 ÉPICA 05 — Calibración de ofertas

> Prioriza **compra ágil** (76,4 % del negocio, D9). Objetivo cuantificado: las 96 líneas
> perdidas al mes.

### HU-5.1 · Benchmark de precios por producto
**Como** analista de precios, **quiero** la distribución de precios de un producto en el
mercado, **para** saber dónde pararme antes de cotizar.

**Criterios de aceptación**
- [ ] Tool `benchmark_precio(producto|sku|codigo_onu, desde?, hasta?, canal?)`.
- [ ] Devuelve min · p25 · mediana · p75 · max · `n` · nº de proveedores distintos.
- [ ] **Separa ganadores de perdedores** (`Oferta seleccionada` / `ProveedorSeleccionado`).
      Ese contraste es el corazón de la tool.
- [ ] Normaliza a precio unitario usando `precioNeto`/`cantidad` (OC),
      `MontoUnitarioOferta` (LIC), `MontoTotal`/`CantidadSolicitada` (COT).
- [ ] **Filtra `es_clp = true`** o convierte explícitamente (Riesgo R1).
- [ ] Si `n < 10`, lo declara como muestra insuficiente en la salida.
      *(38 % de los códigos ONU del catálogo tienen <10 líneas/mes, ~80 en 20 meses.)*

### HU-5.2 · Precio para ganar
**Como** analista de precios, **quiero** saber qué precio habría bastado para ganar, **para**
calibrar la próxima oferta sin regalar margen.

**Criterios de aceptación**
- [ ] Tool `precio_para_ganar(producto|sku, organismo?, canal?, desde?, hasta?)`.
- [ ] Método: sobre los casos históricos del producto, extraer el precio de la oferta
      **seleccionada** y compararlo con el resto; reportar el umbral observado.
- [ ] Distingue por organismo comprador cuando hay datos suficientes: el umbral no es el
      mismo en un municipio que en una universidad.
- [ ] **Advertencia obligatoria en el docstring**: el precio no es el único criterio (ver
      HU-5.3). La tool entrega un umbral observado, no una recomendación de precio.
- [ ] Cuando la oferta ganadora fue **más cara** que otras, lo destaca — es la señal de que
      el precio no decidió.

### HU-5.3 · Criterios que deciden
**Como** estratega, **quiero** saber por qué se gana en nuestro rubro, **para** no bajar
precios cuando el problema es otro.

**Criterios de aceptación**
- [ ] Tool `criterios_que_deciden(rubro|producto, desde?, hasta?)`.
- [ ] Fuentes: `NombreCriterio` (COT, texto libre del motivo de adjudicación) y
      `CriteriosEvaluacion` (LIC, lista `;`-separada dentro del campo).
- [ ] Clasifica y cuantifica los motivos: precio · plazo de entrega · experiencia ·
      canje · otros. Devuelve frecuencia y `n`.
- [ ] Cruza con el resultado: cuando decide el plazo, ¿cuánto más caro pudo ser el ganador?
- [ ] ⚠️ `CriteriosEvaluacion` usa `;` **dentro** del campo entrecomillado — parsear el CSV
      correctamente antes de separar (trampa P12).

### HU-5.4 · Post-mortem y perfil de comprador
**Como** estratega, **quiero** reconstruir una licitación perdida y entender a un comprador,
**para** preparar la próxima con contexto.

**Criterios de aceptación**
- [ ] Tool `postmortem(codigo_licitacion|codigo_cotizacion)`: todas las ofertas de ese
      proceso, ganador, criterio, nuestra posición relativa.
- [ ] Tool `perfil_comprador(organismo|rut_unidad, desde?, hasta?)`: qué compra, a quién,
      con qué criterios, estacionalidad mensual, canal preferido (licitación vs. compra ágil).
- [ ] `perfil_comprador` debe cubrir los compradores reales de Bioquimica:
      Corp. Municipal de Lampa, SLEP del Elqui, U. de Talca, Muni. de Quillón,
      U. de Antofagasta, U. de Chile.
- [ ] Salida en **TSV envuelto en XML** con atributos `filas` y `truncado` (§8 de la
      referencia).

---

## 🟡 ÉPICA 06 — Plano A: API en línea (complemento)

> Deja de ser columna vertebral. Sirve para lo que el lake no puede: el estado **de hoy**.
> `COT` tiene ~1 mes de lag; `oc-da`/`lic-da` ~1 día.

### HU-6.1 · Cliente dual con autenticación diferenciada
**Criterios de aceptación**
- [ ] V1 (licitaciones, OC): ticket como **query param** `?ticket=…`.
- [ ] V2 (compra ágil): ticket en **header** `{"ticket": …}`.
- [ ] Timeouts explícitos; semáforo de concurrencia (máx. 2-3 en vuelo).
- [ ] Valida **status code Y** el campo `success` del cuerpo:
      `success: "NOK"` puede venir con `HTTP 200`.
- [ ] Proyección de campos (whitelist) antes de devolver. Prohibido passthrough del JSON
      crudo: `licitaciones.json?fecha=` devuelve todas las del día.

### HU-6.2 · Caché y contador de cuota
**Criterios de aceptación**
- [ ] `cache.sqlite` indexado por hash de `(url + params)`.
- [ ] TTL por tipo: compra ágil abierta 15 min · licitación cerrada/adjudicada **infinito** ·
      listados de fecha pasada infinito.
- [ ] Contador persistente `quota_log(fecha_local, api, requests, http_429)`, zona
      `America/Santiago`.
- [ ] Tool `verificar_estado_cuota()`: requests de hoy, 429 acumulados, salud de V1/V2,
      periodos presentes en el lake.
- [ ] Al recibir un `429`, marcar el ticket agotado para el resto del día y dejar de
      reintentar.

### HU-6.3 · Manejo de errores con redirección al lake
**Criterios de aceptación**
- [ ] `429` devuelve el mensaje literal:
      `⚠️ Límite de cuota diaria alcanzado en la API de Mercado Público. El ticket se reiniciará a la medianoche.`
      **más** la redirección: `Alternativa disponible: consulta histórica sobre el data lake (sin cuota).`
- [ ] `401` → "ticket ausente o inválido", sin reintentar.
- [ ] `400` → devolver `errors[].mensaje` de la API y los params enviados.
- [ ] `5xx` / timeout → backoff con reintentos; luego servir de caché indicando
      `"dato en caché del {fecha}"`.
- [ ] Resolver la **trampa de la OC en V2** dentro del MCP: si
      `orden_compra.id_orden_compra != null`, la OC existe (aunque
      `codigo_orden_compra` venga `null`); hacer el join a la API V1 y devolver la OC real.
      No delegar este join a Claude.

---

## 🔴 ÉPICA 07 — Despliegue remoto y conector claude.ai

> Reemplaza por completo a la HU-6.2 de la v1 (`claude_desktop_config.json`), que **no
> aplica**: claude.ai monta MCP como conectores HTTP autenticados.

### HU-7.1 · Autenticación del endpoint
**Criterios de aceptación**
- [ ] El endpoint HTTP **no** queda accesible sin autenticación.
- [ ] Secretos por variable de entorno; nada en el repositorio.
- [ ] Rechazo de peticiones no autenticadas registrado en el log.

### HU-7.2 · Límites de recursos (protección real del servicio)
**Como** operador, **quiero** que ninguna consulta pueda tumbar el servicio, **para** que un
endpoint público sobre ~37 M de filas sea seguro.

**Criterios de aceptación**
- [ ] **Ninguna tool expone SQL arbitrario a Claude.** Sólo las funciones tipadas de
      ÉP-04/05, con parámetros validados.
- [ ] `LIMIT` por defecto en toda consulta + timeout por consulta en DuckDB.
- [ ] Límite de tamaño de respuesta; al truncar, indicarlo con cursor/paginación.
- [ ] *(El riesgo no es confidencialidad — los datos son públicos — sino abuso de recursos.)*

### HU-7.3 · Empaquetado y despliegue en Railway

> **Decisión de infraestructura (2026-08-05):** el hosting es **Railway**. Verificado en
> vivo (no de memoria) antes de fijar los criterios de esta historia, porque Railway tiene
> dos restricciones concretas que cambian el diseño respecto de un VPS genérico:
>
> 1. El filesystem del contenedor es **efímero**: se borra en cada redeploy. Persistir el
>    lake y los SQLite **requiere un Volume** de Railway adjunto al servicio.
> 2. **Un Volume es 1:1 con un servicio — Railway no soporta volúmenes compartidos entre
>    dos servicios.** Si la ingesta corriera como un *servicio Railway separado* del
>    servidor MCP, cada uno vería su propio lake, desincronizados. La ingesta debe ser una
>    **tarea en background dentro del mismo proceso/servicio**, no un deploy aparte.

**Criterios de aceptación**
- [ ] `Dockerfile` con el servicio MCP. **Un único servicio Railway** (servidor + tarea de
      ingesta en background, mismo proceso) — no dos servicios.
- [ ] **Volume de Railway** adjunto, montado en un path (ej. `/data`), apuntado por la
      variable de entorno `DATA_DIR` (ya soportada por `config.get_settings()`).
      Dimensionar **5 GB** (lake 1,5–4 GB + `manifest.sqlite`/`cache.sqlite`, con margen).
      Costo estimado a la tarifa de Railway (~US$0,15/GB/mes): **< US$1/mes**.
- [ ] El scratch de descompresión de ZIP (hasta ~1,34 GB por periodo) usa el filesystem
      **efímero** del contenedor (`/tmp`), no el Volume — se descarta antes de escribir el
      Parquet (HU-2.2), así que no necesita persistir y el Volume se mantiene chico.
- [ ] Ingesta programada como **tarea async dentro del mismo servicio** (scheduler propio o
      `apscheduler`), o disparable manualmente vía la tool `ingerir_datos_abiertos` — nunca
      como servicio Railway independiente.
- [ ] `manifest.sqlite`/`cache.sqlite` en **modo WAL**: el servidor MCP y la tarea de
      ingesta comparten proceso y pueden escribir cerca en el tiempo.
- [ ] Healthcheck que reporte: servidor arriba, lake accesible, último periodo ingerido.
- [ ] Documentar el downtime breve esperado en cada redeploy con Volume adjunto (propio de
      Railway); aceptable para este caso de uso, sin SLA de alta disponibilidad.

### HU-7.4 · Conector en claude.ai y system prompt
**Criterios de aceptación**
- [ ] Instrucciones paso a paso para registrar el conector en claude.ai.
- [ ] System prompt / instrucciones personalizadas que le enseñen a Claude:
      - el **enfoque market-centric** (no concluir desde el historial propio);
      - que **compra ágil es el 76 %** del negocio;
      - la **frontera de frescura**: lake = histórico (`COT` ~1 mes de lag), API/LicitaLab = hoy;
      - que **LicitaLab detecta** oportunidades y **este MCP calibra** precio y rival;
      - que debe reportar el `n` y la confianza de resolución de producto al usuario;
      - que el precio no es el único criterio de adjudicación.
- [ ] Prueba de aceptación conversacional: 5 preguntas reales del usuario respondidas de
      punta a punta desde claude.ai.

---

## 🟡 ÉPICA 08 — Mantención y observabilidad

> No es opcional: se verificó que el esquema de los CSV **cambia** (LIC 105→110 columnas,
> OC renombró una, el índice absoluto se desplaza). Sin esta épica el sistema se degrada en silencio,
> que es peor que caerse.

### HU-8.1 · Detección de deriva de esquema
**Criterios de aceptación**
- [ ] Al ingerir, comparar el header contra el esquema registrado.
- [ ] Columna **nueva** ⇒ log de warning + se agrega al esquema unión.
- [ ] Columna **ausente** que el ETL usa ⇒ **fallar ruidosamente**, no continuar con `NULL`.
- [ ] Cambio de **orden** ⇒ irrelevante por diseño (mapeo por nombre, HU-2.3), pero se
      registra.
- [ ] `schema_version` por periodo en el manifest.

### HU-8.2 · Reingesta programada
**Criterios de aceptación**
- [ ] Job que revisa `ETag` de los últimos N periodos y reingiere los que cambiaron.
- [ ] Cadencia acorde a lo medido: `oc-da`/`lic-da` se regeneran a diario;
      `COT` publica con ~1 mes de lag.
- [ ] Resultado de cada corrida registrado en el manifest.

### HU-8.3 · Métricas de salud del lake
**Criterios de aceptación**
- [ ] Tool/endpoint que reporte: periodos presentes y faltantes, filas por dataset,
      fecha de la última ingesta, periodos con deriva de esquema detectada.
- [ ] Alerta cuando un periodo esperado no está publicado tras N días.

---

## ⚪ ÉPICA 09 — CONGELADA: OCR y adjuntos

**Motivo:** no sirve al objetivo declarado (entender competencia + calibrar ofertas).

Si se reactiva:
- Evaluar **delegar** al MCP `optimizador-documentos` ya conectado, antes de implementar nada.
  Ahorra el problema de Tesseract en Windows (`pytesseract` requiere binario + idioma `spa`
  instalados a mano; `easyocr` lo evita pero arrastra ~2 GB de PyTorch).
- ⚠️ **Supuesto no validado**: ninguna API documentada expone las URL de las bases. Si exige
  scraping de `mercadopublico.cl`, la épica cambia de naturaleza (fragilidad, términos de uso).
- Conservar de la v1: umbral de detección de escaneado **por página** (`<100 chars/página`,
  no total) y el mensaje literal anti-alucinación `⚠️ DOCUMENTO_ESCANEADO_ILEGIBLE: …`.

---

## 2. Registro de riesgos

| # | Riesgo | Severidad | Estado | Mitigación |
| :-- | :-- | :-: | :-- | :-- |
| **R1** | `precioNeto` está en `monedaItem`, que no siempre es CLP. `279,8` en CLF son ~$10,6 M, no $280. Sólo `MontoTotalOC_PesosChilenos` viene convertido, y a nivel de OC, no de línea | 🔴 Alta | mitigable | Columna `es_clp` (HU-2.3); todas las tools de precio filtran o convierten y lo declaran. En el segmento de Bioquimica el CLP domina (1 caso USD en la muestra) |
| **R2** | El catálogo BQ no expone códigos ONU ⇒ el cruce producto↔mercado es difuso | 🔴 Alta | mitigable | ÉP-03: Claude cruza catálogo (otro conector) + historial propio (HU-3.1) en conversación, y el mapeo confirmado se persiste (HU-3.2) — no un bootstrap de una vez |
| **R3** | El esquema de los CSV cambia y la ingesta se degrada en silencio | 🟡 Media | mitigable | HU-2.3 (mapeo por nombre) + HU-8.1 (fallar ruidosamente) |
| **R4** | Muestra insuficiente por producto: 38 % de los códigos ONU tienen <10 líneas/mes | 🟡 Media | aceptado | Devolver siempre `n`; declarar muestra insuficiente bajo umbral |
| **R5** | Lag de `COT` (~1 mes) ⇒ no sirve para la compra ágil que cierra mañana | 🟡 Media | aceptado | Frontera declarada en el system prompt (HU-7.4); API V2 / LicitaLab para el presente |
| **R6** | Endpoint público + 37 M filas ⇒ una consulta sin `LIMIT` tumba el servicio | 🟡 Media | mitigable | HU-7.2: sin SQL libre, `LIMIT` y timeout obligatorios |
| **R7** | Nadie mantiene el ETL cuando ChileCompra cambie el formato | 🟡 Media | **abierto** | Requiere dueño asignado. ÉP-08 lo hace detectable, no lo resuelve solo |
| **R8** | El 76 % del negocio (compra ágil) podría decidirse por relación con el comprador y no por cotización — en ese caso el análisis de precios vale mucho menos | 🟡 Media | **abierto** | ⚠️ No es verificable en los datos. **Pregunta pendiente al usuario** antes de invertir ÉP-05 completa |
| **R9** | El MCP entrega diagnóstico, no adjudicaciones: si el diagnóstico dice "pierden por plazo" y el plazo no se puede mejorar, no habrá más ventas | 🟢 Baja | aceptado | Expectativa a alinear explícitamente con el usuario |

---

## 3. Preguntas abiertas al usuario

| # | Pregunta | Bloquea |
| :-- | :-- | :-- |
| Q1 | ¿El RUT `77.814.808-2` es correcto? Su DV mod-11 debería ser `0` | nada (se ingiere la variante corregida) |
| Q2 | ¿El diagnóstico clínico in-vitro está fuera del negocio? Los líderes del rubro (Roche $4.730 M/mes, Valtek, Tecnigen, BioMérieux, Grifols, Abbott) no están en la watchlist | alcance de ÉP-04 |
| Q3 | **¿Las compras ágiles llegan por cotización competitiva o por relación previa con el comprador?** | prioridad de ÉP-05 (ver R8) |
| Q4 | ¿Se agregan a la watchlist los rivales descubiertos (Tepullin, Vercon, Dist. de Productos de Laboratorio, Liliana López Prieto…)? | nada (HU-4.1 los detecta igual) |
| Q5 | ¿Quién será el dueño de la mantención del ETL? | R7 |

---

## 4. Hoja de ruta

```
[Sprint 0] ✅ HECHO ── Spike de Datos Abiertos · identidad resuelta · watchlist
                       perfilada · rubros derivados del catálogo

[Sprint 1] ───► ÉP-01 (fundaciones) + ÉP-02 (ingesta y lake)
                 └─ hito: 20 meses ingeridos, lake consultable por DuckDB

[Sprint 2] ───► ÉP-03 (puente catálogo↔ONU) + ÉP-04 (inteligencia competitiva)
                 └─ hito: "¿contra quién compito y qué está haciendo?" respondida

[Sprint 3] ───► ÉP-05 (calibración de ofertas)
                 └─ hito: "¿a qué precio y con qué argumento gano esto?" respondida

[Sprint 4] ───► ÉP-07 (despliegue remoto + conector claude.ai) + ÉP-08 (mantención)
                 └─ hito: uso real desde claude.ai

[Continuo] ───► ÉP-06 (API en línea) se intercala donde haga falta el dato de hoy
```

> El esqueleto HTTP de HU-1.3 se levanta en el **Sprint 1** y corre en local durante todo el
> desarrollo, para que el Sprint 4 sea despliegue y no reescritura.

---

## 5. Definition of Done transversal

Aplica a **toda** historia:

- [ ] Tipado estricto (`typing`, `from __future__ import annotations`), PEP 8.
- [ ] Modelos Pydantic para entradas y salidas de tools. Sin `dict` sueltos.
- [ ] **Docstring como producto**: dice cuándo usar la tool, cuándo **no**, y qué trampa del
      endpoint resuelve. Es el prompt que lee Claude, no un comentario.
- [ ] Toda salida acotada: `limit` por defecto + indicador de truncamiento.
- [ ] Tests con fixtures locales; ninguno toca la red.
- [ ] Sin `print()` en el proceso del servidor.
- [ ] Secretos sólo por variable de entorno.
- [ ] Tablas grandes en **TSV envuelto en XML** con atributos `filas` y `truncado`.
- [ ] Toda agregación reporta `n`. Ningún número se entrega sin su tamaño de muestra.
