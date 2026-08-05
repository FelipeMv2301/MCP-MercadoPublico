# Esquema real de Datos Abiertos ChileCompra — verificado empíricamente

**Fecha del spike:** 2026-08-05
**Método:** listado del Azure Blob container + descarga de muestras + parseo con `csv.reader`.
**Muestras usadas:** `oc-da/2026-6`, `lic-da/2026-6`, `COT_2026-06`, más headers históricos
(`lic-da/2015-6`, `lic-da/2019-3`, `oc-da/2010-1`, `oc-da/2019-3`).

Este documento **reemplaza** lo que decía `Backlog/API_Licitaciones_OrdenesCompra_V1.md`
sobre descargas masivas, que estaba incompleto y con un error de formato de URL.

---

## 1. Endpoints reales

Cuenta de almacenamiento: `https://transparenciachc.blob.core.windows.net`

| Dataset | Patrón de URL | ⚠️ Formato del mes | Cobertura verificada |
| :-- | :-- | :-- | :-- |
| **Órdenes de compra** | `/oc-da/{AAAA}-{M}.zip` | **SIN** cero-padding | `2007-1` → `2026-7` |
| **Licitaciones** | `/lic-da/{AAAA}-{M}.zip` | **SIN** cero-padding | ≥ `2015-6` → `2026-6` |
| **Cotizaciones Compra Ágil** | `/trnspchc/COT_{AAAA}-{MM}.zip` | **CON** cero-padding | 75 meses, hasta `2026-06` |

### 1.1 Dos correcciones críticas respecto de la documentación previa

**(a) El padding del mes es inconsistente entre datasets.** Es la causa de que la URL
documentada fallara:

```
❌ https://.../oc-da/2026-06.zip   → HTTP 404
✅ https://.../oc-da/2026-6.zip    → HTTP 200
✅ https://.../trnspchc/COT_2026-06.zip → HTTP 200   (aquí SÍ va padding)
```

Implicación: el builder de URLs necesita una regla **por dataset**, no una global.

```python
def url_dataset(dataset: str, anio: int, mes: int) -> str:
    base = "https://transparenciachc.blob.core.windows.net"
    if dataset in ("oc", "lic"):
        return f"{base}/{dataset}-da/{anio}-{mes}.zip"        # sin padding
    if dataset == "cot":
        return f"{base}/trnspchc/COT_{anio}-{mes:02d}.zip"    # con padding
    raise ValueError(dataset)
```

**(b) El dataset de licitaciones (`lic-da`) no estaba documentado.** Es el que contiene
el detalle de ofertas (incluidas las perdedoras) — el más valioso para análisis
competitivo. Se descubrió por analogía con `oc-da`.

### 1.2 Container `trnspchc`: advertencia

`trnspchc` **no es un container de datos abiertos estructurados**. Tiene 2.204 blobs y es
un repositorio mixto de respuestas a solicitudes de transparencia ad-hoc (`AE011T0002855.zip`
= folio de solicitud, hasta **4,2 GB**), informes PAC, planillas sueltas y datasets one-off.

Sólo `COT_{AAAA}-{MM}.zip` (75 blobs) es una serie periódica sistemática. **No** iterar el
container a ciegas.

Blobs one-off potencialmente relevantes al rubro salud, detectados de paso:

| Blob | Tamaño | Nota |
| :-- | :-- | :-- |
| `OC_Salud_2019-2025.zip` | 1,13 GB | OC del sector salud, 7 años preagregado |
| `OC_canceladas_{AAAA}.zip` | 7–34 MB | 2018→2025, un archivo por año |
| `AE011T0003700_data_medicamentos_2010_2015.zip` | 1,05 GB | medicamentos histórico |

Estos son *convenientes pero no reproducibles* — nombres arbitrarios, sin garantía de
actualización. Usar `oc-da`/`lic-da` como fuente canónica.

### 1.3 Frescura y cadencia — mejor de lo supuesto

`ETag` y `Last-Modified` presentes en los tres datasets ⇒ **descarga incremental
condicional viable** (`If-None-Match`).

Medición del 2026-08-05:

| Blob | `Last-Modified` | Lectura |
| :-- | :-- | :-- |
| `oc-da/2026-7.zip` | 2026-08-05 10:05 GMT | mes en curso, **regenerado el mismo día** |
| `oc-da/2026-6.zip` | 2026-08-05 10:08 GMT | mes cerrado, **igual se regenera a diario** |
| `lic-da/2026-6.zip` | 2026-08-04 11:47 GMT | ~1 día |
| `COT_2026-06.zip` | 2026-08-04 23:11 GMT | ~1 mes de lag |

Conclusiones operativas:

1. El lag real de `oc-da`/`lic-da` es de **~1 día**, no de un mes. Concuerda con lo que
   declara ChileCompra ("un día de rezago, actualización diaria entre 12:00 y 14:00").
2. `oc-da` **reescribe también los meses pasados**. Un periodo cerrado **no es inmutable**:
   se corrige retroactivamente. El diseño "Parquet inmutable por periodo" del documento de
   referencia debe ajustarse — ver §5.
3. `COT` sí tiene lag mensual grande. Para compra ágil reciente hay que usar la API V2.

---

## 2. Formato físico de los CSV

Idéntico en los tres datasets:

| Propiedad | Valor verificado |
| :-- | :-- |
| **Encoding** | `latin-1` / `cp1252` — **NO UTF-8**, y **sin BOM**. Decodificar como UTF-8 lanza `UnicodeDecodeError` |
| **Separador de campos** | `;` (punto y coma) |
| **Quoting** | `"` en **todos** los campos, incluidos los numéricos |
| **Separador decimal** | **coma** — `19977,72`, `279,8`, `618646465,493438` |
| **Separador de miles** | ninguno |
| **Formato de fecha** | ISO `AAAA-MM-DD` ✅ (a diferencia de la API V1, que usa `DDMMAAAA`) |
| **Terminador de línea** | CRLF |
| **Newlines embebidos** | **SÍ**, dentro de campos entrecomillados |

### 2.1 Ratio de compresión: 17:1

| ZIP | Comprimido | Descomprimido | Archivos internos | Filas de datos | Cols |
| :-- | --: | --: | :-- | --: | --: |
| `COT_2026-06.zip` | 78 MB | **1,34 GB** | `COT1_2026-06.csv` (666 MB) + `COT2_2026-06.csv` (670 MB) | 620.893 (+ ~620 k) | 34 |
| `oc-da/2026-6.zip` | 99 MB | **736 MB** | `2026-6.csv` | 437.538 | 78 |
| `lic-da/2026-6.zip` | 17 MB | **311 MB** | `lic_2026-6.csv` | 157.886 | 110 |

Conteo hecho con parser CSV real (no por líneas, por P3). **`filas_con_arity_distinta = 0`
en los tres archivos** ⇒ el CSV está bien formado y el esquema es consistente dentro de
cada periodo. Buena noticia para el ETL: no hace falta lógica de recuperación de filas
corruptas.

**≈ 1,84 M filas y 2,4 GB descomprimidos por UN mes.** Con 24 meses: ~44 M filas, ~57 GB
en CSV. Esto zanja la discusión de arquitectura: streaming + Parquet columnar obligatorio,
jamás cargar a memoria, jamás acercar un archivo a Claude.

⚠️ **`COT` viene partido en 2 archivos** (`COT1_`, `COT2_`) con el mismo esquema. El nombre
interno **no** coincide con el del ZIP. El extractor debe iterar `namelist()`, no asumir
un archivo único ni derivar el nombre interno del externo.

> **Por qué está partido (resuelve B14):** `COT1_` tiene 620.893 filas. ChileCompra declara
> que los archivos publicados quedan bajo **1 millón de registros** para que se puedan abrir
> en Excel / LibreOffice. El corte es un límite de tamaño, no un criterio semántico ⇒
> `COT2_` es **continuación** de `COT1_`, y ambos deben concatenarse. Consecuencia: el
> número de archivos por ZIP **puede crecer** en meses de mayor volumen (`COT3_`…). El
> extractor debe iterar `namelist()` con glob, nunca asumir exactamente dos.

---

## 3. Trampas de parsing (todas verificadas)

| # | Trampa | Evidencia | Mitigación |
| :-- | :-- | :-- | :-- |
| P1 | Encoding latin-1 sin BOM | header falla al decodificar UTF-8 | `encoding="latin-1"` explícito |
| P2 | Decimal con coma en montos | `MontoTotalOC = "19977,72"` | `decimal=","` en pandas; conversión explícita en DuckDB |
| P3 | **Newlines embebidos en campos** | `Descripcion/Obervaciones` en OC; `DetalleCotizacion` en COT | Parser CSV real. **Prohibido** `split("\n")` o contar líneas para estimar filas |
| P4 | `"NA"` como nulo literal | `FechaCancelacion="NA"`, `PaisProveedor="NA"`, `MotivoCancelacion="NA"` | `na_values=["NA",""]` |
| P5 | `1900-01-01` como fecha sentinela | `FechaSoporteFisico`, `FechaEstimadaFirma`, `FechaVisitaTerreno` | tratar como `NULL` |
| P6 | **Sentinela contamina campos de texto** | `DireccionVisita = "1900-01-01"`, `DireccionEntrega = "1900-01-01"` en LIC | bug del dataset: si un campo de dirección trae fecha ⇒ `NULL` |
| P7 | Typos en nombres de columna | `MontoTotalDisponble` (COT), `NombreroductoGenerico` y `Descripcion/Obervaciones` (OC), `Nombre producto genrico` (LIC) | mapa de renombre explícito. **No corregirlos en el origen** |
| P8 | Nombres con espacios, `/` y `.` | `Forma de Pago`, `Tipo de Adquisicion`, `Descripcion/Obervaciones`, `Valor Total Ofertado` | quoting obligatorio en SQL; renombrar a `snake_case` al escribir Parquet |
| P9 | Casing inconsistente | `codigoEstado` vs `Estado` vs `NOMBRECONTACTO` vs `moneda` vs `sector` | normalizar todo a `snake_case` |
| P10 | Columna duplicada con sufijo | `DescripcionCriteriosRequisitosSociales` **y** `DescripcionCriteriosRequisitosSociales.1` en LIC | el `.1` viene literal en el archivo; conservar ambas o descartar la `.1` deliberadamente |
| P11 | Dos columnas casi homónimas | LIC/OC: `FormaPago` (código `2`) **y** `Forma de Pago` (texto libre) | son distintas. No deduplicar |
| P12 | `;` dentro de un campo | `CriteriosEvaluacion = "Plazo de Entrega ; POLITICA DE CANJE ; Experiencia"` | está entrecomillado, el parser lo maneja; pero **no** hacer `split(";")` a nivel de línea |
| P13 | Región como texto, no código | `"Región de Tarapacá  "` con espacios finales — la API V2 usa código `1`–`16` | tabla de mapeo texto↔código + `strip()` |
| P14 | RUT con puntos y guion | `78.167.575-K`, dígito verificador `K` | normalizar a `78167575-K` para joins |
| P15 | Multi-moneda en el mismo archivo | `TipoMonedaOC = "CLF"` (UF), `monedaItem="CLF"` | ver §4.1 — riesgo analítico grave |

---

## 4. Esquemas por dataset

### 4.1 `oc-da` — Órdenes de compra · 78 columnas

**Grano:** una fila por **línea de ítem** de orden de compra (`IDItem`).

Columnas de mayor valor:

| Grupo | Columnas |
| :-- | :-- |
| Identidad OC | `ID`, `Codigo` (`2667-1061-SE21`), `Link`, `Nombre`, `Estado`, `codigoEstado` |
| **Canal** | `ProcedenciaOC`, `EsTratoDirecto`, `EsCompraAgil`, `Tipo`, `DescripcionTipoOC` |
| **Proveedor** | `CodigoProveedor` (`1353385`), `NombreProveedor`, `RutSucursal`, `CodigoSucursal`, `ActividadProveedor`, `ComunaProveedor`, `RegionProveedor` |
| Comprador | `CodigoOrganismoPublico`, `OrganismoPublico`, `RutUnidadCompra`, `CodigoUnidadCompra`, `sector`, `RegionUnidadCompra` |
| **Montos** | `MontoTotalOC`, `TipoMonedaOC`, `MontoTotalOC_PesosChilenos`, `TotalNetoOC`, `Impuestos`, `PorcentajeIva`, `Descuentos`, `Cargos` |
| **Ítem / precio** | `IDItem`, `codigoProductoONU`, `codigoCategoria`, `Categoria`, `RubroN1`/`N2`/`N3`, `NombreroductoGenerico`, `cantidad`, `UnidadMedida`, **`precioNeto`**, `monedaItem`, `totalLineaNeto` |
| Trazabilidad | `CodigoLicitacion`, `Codigo_ConvenioMarco` |
| Fechas | `FechaCreacion`, `FechaEnvio`, `FechaAceptacion`, `FechaCancelacion`, `fechaUltimaModificacion` |
| Calidad | `PromedioCalificacion`, `CantidadEvaluacion` |

> ✅ **`precioNeto` + `cantidad` + `codigoProductoONU` = inteligencia de precios unitarios
> comparables.** Es la columna que el backlog daba por incierta (incógnita B6). Existe.

> ✅ **Resuelve el bloqueante de identidad** (§11 del doc de referencia): el CSV trae
> `CodigoProveedor` **y** `RutSucursal` en la misma fila. Basta un `grep` del RUT de
> Bioquimica.cl en un mes cualquiera para obtener su `CodigoProveedor` de la API V1 — sin
> gastar cuota.

> ⚠️ **TRAMPA ANALÍTICA GRAVE (P15).** `precioNeto` está expresado en `monedaItem`, que
> **no siempre es CLP**. La primera fila de la muestra trae `CLF` (Unidad de Fomento):
> `precioNeto = 279,8` son 279,8 UF ≈ $10,6 M, no $280. Sólo `MontoTotalOC_PesosChilenos`
> viene convertido, y existe únicamente a nivel de OC, **no de línea**.
> Un `AVG(precioNeto)` sin filtrar por moneda produce cifras sin sentido.
> **Regla obligatoria del ETL**: toda consulta de precios filtra `monedaItem = 'CLP'` o
> aplica conversión explícita. Documentarlo en el docstring de la tool.

### 4.2 `lic-da` — Licitaciones · 110 columnas

**Grano:** licitación × línea de adquisición × **oferta de proveedor**. Producto cartesiano
— de ahí que 311 MB sean un solo mes.

| Grupo | Columnas |
| :-- | :-- |
| Identidad | `Codigo` (interno `9515725`), **`CodigoExterno`** (`1057439-20-LP25`), `Link`, `Nombre`, `Descripcion` |
| Estado / tipo | `Estado`, `CodigoEstado`, `Tipo` (`LP`), `Tipo de Adquisicion`, `TipoConvocatoria`, `Etapas` |
| Comprador | `CodigoOrganismo`, `NombreOrganismo`, `sector`, `RutUnidad`, `CodigoUnidad`, `RegionUnidad`, `ComunaUnidad` |
| **Evaluación** | **`CriteriosEvaluacion`** (texto, `;`-separado interno), `NumeroOferentes`, `CantidadReclamos` |
| Montos | `MontoEstimado`, `VisibilidadMonto`, `Estimacion`, `CodigoMoneda`, `JustificacionMontoEstimado` |
| Cronograma | `FechaCreacion`, `FechaPublicacion`, `FechaCierre`, `FechaActoAperturaTecnica`/`Economica`, `FechaPubRespuestas`, `FechaAdjudicacion`, `FechaEstimadaAdjudicacion` |
| Contrato | `TiempoDuracionContrato`, `Modalidad`, `TipoPago`, `EsRenovable`, `SubContratacion`, `ProhibicionContratacion`, `ExtensionPlazo` |
| Sostenibilidad | `CriteriosRequisitosAmbientales`, `CriteriosRequisitosSociales` (+ descripciones) |
| Línea de producto | `Codigoitem`, `CodigoProductoONU`, `Rubro1`/`2`/`3`, `Nombre producto genrico`, `Nombre linea Adquisicion`, `Descripcion linea Adquisicion`, `UnidadMedida`, `Cantidad` |
| **🎯 OFERTA** | `RutProveedor`, `NombreProveedor`, `RazonSocialProveedor`, `DescripcionProveedor`, `CodigoSucursalProveedor`, `Nombre de la Oferta`, `Estado Oferta`, `Cantidad Ofertada`, `Moneda de la Oferta`, **`MontoUnitarioOferta`**, **`Valor Total Ofertado`**, `CantidadAdjudicada`, `MontoLineaAdjudica`, `FechaEnvioOferta`, **`Oferta seleccionada`** |

> 🎯 **Este es el dataset más valioso del sistema.** El bloque de oferta incluye a los
> proveedores **que perdieron**, con su precio unitario y el flag `Oferta seleccionada`
> (`"No Seleccionada"` en la muestra). Eso permite, sin gastar un solo request de cuota:
> - **Post-mortem** (HU-4.2): nuestra oferta vs. la ganadora, línea por línea.
> - **Benchmark de precios** (HU-3.1): distribución completa de precios por
>   `CodigoProductoONU`, no sólo el ganador.
> - **Mapa competitivo**: quién compite contra nosotros, en qué rubros, a qué precio, y
>   con qué tasa de éxito.
>
> Ni la API V1 ni LicitaLab entregan esto en volumen. Es el diferenciador del proyecto.

⚠️ `CantidadReclamos = 2778` en una licitación individual es implausible — probablemente un
contador global mal desnormalizado. **No usar sin validar.**

### 4.3 `COT` — Cotizaciones Compra Ágil · 34 columnas

**Grano:** cotización × producto × proveedor cotizante.

| Grupo | Columnas |
| :-- | :-- |
| Comprador | `NombreOOPP`, `RazonSocialUnidaddeCompra`, `NombreUnidaddeCompra`, `RUTUnidaddeCompra`, `CodigoUnidaddeCompra` |
| Cotización | `CodigoCotizacion` (`1079967-350-COT26`), `NombreCotizacion`, `DescripcionCotizacion`, `Estado`, `Region`, `DireccionEntrega`, `PlazoEntrega` |
| Fechas | `FechaPublicacionParaCotizar`, `FechaCierreParaCotizar`, `FechaAceptacionOCProveedor` |
| Presupuesto | `MontoTotalDisponble` *(typo en origen)* |
| Producto | `ProductoCotizado`, `CodigoProducto`, `NombreProductoGenerico`, `CantidadSolicitada` |
| **🎯 Cotizante** | `RazonSocialProveedor`, `RUTProveedor`, `Tamano` (`MiPyme`), `DetalleCotizacion`, **`ProveedorSeleccionado`** (`si`/`no`), `moneda`, **`MontoTotal`** |
| Resultado | `NombreCriterio`, `CodigoOC`, `EstadoOC`, `MotivoCancelacion` |
| Sostenibilidad | `ConsideraRequisitosMedioambientales`, `ConsideraRequisitosImpactoSocialEconomico` |

> 🎯 Mismo patrón ganador: `ProveedorSeleccionado` + `MontoTotal` por cotizante ⇒ se ve el
> **precio de todos los que cotizaron**, no sólo del ganador.
> `NombreCriterio` explica *por qué* ganó (ej. *"Plazos de entrega, el proveedor ofreció el
> plazo de entrega más conveniente"*) — señal directa de que competir por precio no siempre
> es la jugada.
> `MontoTotalDisponble` (presupuesto) vs `MontoTotal` (cotizado) ⇒ margen de holgura, útil
> para calibrar agresividad de la oferta.

---

## 5. Estabilidad del esquema — el esquema **no** es estable

Comparación de headers contra `2026-6`:

| Dataset | Periodo antiguo | Columnas | vs. 2026-6 |
| :-- | :-- | --: | :-- |
| `lic-da` | `2015-6` | 105 | faltan 6, sobra 1; índice absoluto desplazado por inserción |
| `lic-da` | `2019-3` | 105 | faltan 6, sobra 1; índice absoluto desplazado por inserción |
| `oc-da` | `2010-1` | 78 | `idPlanDeCompra` (idx 12) → `Codigo_ConvenioMarco` (idx 58) |
| `oc-da` | `2019-3` | 78 | `idPlanDeCompra` (idx 12) → `Codigo_ConvenioMarco` (idx 58) |

> **Precisión verificada con test** (`tests/test_parsing_trampas.py`): el **orden
> relativo** de las columnas presentes en ambos periodos **no cambió** — no hay un
> reordenamiento general. Lo que ocurre es más específico y, para un lector por
> índice, igual de destructivo: las columnas **agregadas** se insertan en medio
> del header y desplazan el **índice absoluto** de todo lo posterior. En `lic-da`,
> `NumeroOferentes` pasa de la posición 75 (2019) a la 80 (2026) sin que su
> significado cambie. En `oc-da`, la columna en la posición 12 significa una cosa
> en 2019 (`idPlanDeCompra`) y otra completamente distinta en 2026 (nada — esa
> columna ya no existe ahí; `Codigo_ConvenioMarco` vive en la posición 58).

Cambios concretos en `lic-da` (2019 → 2026), coherentes con la Ley 21.634 de compras
públicas y sus criterios de sostenibilidad:

```
+ CriteriosRequisitosAmbientales
+ DescripcionCriteriosRequisitosAmbientales
+ CriteriosRequisitosSociales
+ DescripcionCriteriosRequisitosSociales
+ DescripcionCriteriosRequisitosSociales.1
+ CriteriosEvaluacion
- ValorTiempoRenovacion
```

En `oc-da`: `idPlanDeCompra` → `Codigo_ConvenioMarco`.

**Tres reglas de ETL que se derivan de esto:**

1. **Mapear por nombre de columna, nunca por posición.** El índice absoluto se desplaza
   con cada columna agregada, incluso donde el conteo total coincide (`oc-da`: 78 = 78,
   pero la posición 12 significa algo distinto en cada periodo). Leer por índice produce
   datos corridos en silencio — el peor modo de falla posible.
2. **Esquema unión + versionado.** El Parquet destino usa el superconjunto de columnas;
   los periodos que no traen una columna la escriben `NULL`. Registrar `schema_version`
   por periodo en el manifest y **fallar ruidosamente** ante una columna desconocida, en
   vez de descartarla.
3. **Los periodos cerrados no son inmutables.** `oc-da/2026-6` se regeneró el 2026-08-05,
   dos meses después del cierre. Corolario: el manifest debe guardar el `ETag` por periodo
   y **reingerir cuando cambie**, no sólo cuando el periodo sea el actual. Esto invalida el
   supuesto "Parquet inmutable por periodo" del documento de referencia §5.3.

---

## 6. Recomendaciones de ingesta (actualizadas con datos reales)

```
HEAD blob (If-None-Match: etag_guardado)
  ├─ 304 → nada que hacer
  └─ 200 → descargar ZIP a temp
        └─ zipfile.namelist()  ← iterar; COT trae 2 CSV
             └─ stream: TextIOWrapper(encoding='latin-1', newline='')
                  └─ csv.reader(delimiter=';', quotechar='"')   ← parser real, por P3
                       └─ normalizar por chunks de ~200k filas:
                            · snake_case de nombres (P7–P11)
                            · coma→punto en decimales (P2)
                            · 'NA'/''/'1900-01-01' → NULL (P4,P5,P6)
                            · RUT sin puntos (P14)
                            · región texto→código (P13)
                            · marcar moneda ≠ CLP (P15)
                       └─ escribir Parquet: data/{ds}/anio=YYYY/mes=M/part-*.parquet
                            └─ manifest: (dataset, periodo, etag, filas, schema_version, sha256)
```

Parámetros dimensionados con los tamaños reales:

- `csv.field_size_limit` elevado — `DescripcionCotizacion` y `DetalleCotizacion` son largos.
- Chunks de 100–250 k filas: acota RAM con archivos de 736 MB.
- Compresión Parquet `zstd`: buena tasa en texto repetitivo (razones sociales, rubros).
- Particionar por `anio`/`mes` habilita *predicate pushdown* en DuckDB.
- **Presupuesto de disco**: ~2,4 GB CSV/mes ⇒ estimar **300–600 MB/mes en Parquet**
  (columnar + zstd sobre texto muy repetitivo). 24 meses ≈ 8–15 GB. Verificar tras el
  primer periodo real y ajustar el alcance histórico.

---

## 7. Estado de las incógnitas del spike (§5.2 del doc de referencia)

| # | Incógnita | Estado |
| :-- | :-- | :-- |
| B1 | Archivos dentro del ZIP | ✅ 1 CSV (`oc`, `lic`); **2 CSV** (`COT1_`, `COT2_`); nombre interno ≠ externo |
| B2 | Encoding | ✅ `latin-1`/`cp1252`, sin BOM |
| B3 | Separador | ✅ `;`, todo entrecomillado |
| B4 | Esquema y estabilidad | ✅ documentado §4; **NO estable** §5 |
| B5 | Tamaño descomprimido | ✅ 2,4 GB/mes en los 3 datasets |
| B6 | ¿Precio unitario? | ✅ **SÍ** — `precioNeto` (OC), `MontoUnitarioOferta` (LIC), `MontoTotal` (COT) |
| B7 | Rango disponible | ✅ `oc-da` desde `2007-1`; `lic-da` ≥ `2015-6`; `COT` 75 meses |
| B8 | Latencia de publicación | ✅ `oc`/`lic` ~1 día; `COT` ~1 mes |
| B9 | `ETag`/`Last-Modified` | ✅ ambos presentes ⇒ descarga condicional |
| B10 | Decimales | ✅ **coma** decimal, sin separador de miles |

Incógnitas **nuevas** que aparecieron y quedan abiertas:

| # | Nueva incógnita | Por qué importa |
| :-- | :-- | :-- |
| B11 | ¿Cómo convertir `CLF`/`USD`/`EUR` a CLP a nivel de línea? | Sin resolverlo, todo promedio de precios está contaminado (P15) |
| B12 | ¿`lic-da` existe antes de `2015-6`? | Define la profundidad histórica del análisis competitivo |
| B13 | ¿Qué es `ZGEN_{DD-MM-AAAA}.zip` (61 blobs, xlsx interno)? | Serie periódica no identificada; podría ser redundante |
| B15 | ¿Con qué frecuencia real cambia el `ETag` de un periodo cerrado? | Determina el costo de la política de reingesta |

**B14 resuelta**: `COT2_` es continuación de `COT1_` — corte por el límite de ~1 M
registros/archivo que ChileCompra aplica para compatibilidad con Excel. Ver §2.1.

---

*Fixtures de muestra en el scratchpad de la sesión: `cot1_head.bin`, `oc_head.bin`,
`lic_head.bin`, `lic2015.bin`, `lic2019.bin`, `oc2010.bin`, `oc2019.bin`.
Mover a `tests/fixtures/` al iniciar la implementación.*
