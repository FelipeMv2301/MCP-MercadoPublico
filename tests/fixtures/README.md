# Fixtures del spike de Datos Abiertos (2026-08-05)

Muestras reales capturadas durante la caracterización de los datasets. **Ningún test debe
tocar la red**: estos archivos son la única fuente de verdad para los tests de parsing.

| Archivo | Origen | Contenido | Uso |
| :-- | :-- | :-- | :-- |
| `oc_head.bin` | `oc-da/2026-6.zip` → `2026-6.csv` | primeros 40 KB (78 columnas) | esquema actual de OC |
| `lic_head.bin` | `lic-da/2026-6.zip` → `lic_2026-6.csv` | primeros 40 KB (110 columnas) | esquema actual de licitaciones |
| `cot1_head.bin` | `COT_2026-06.zip` → `COT1_2026-06.csv` | primeros 30 KB (34 columnas) | esquema actual de cotizaciones |
| `oc2010.bin` | `oc-da/2010-1.zip` | primeros 20 KB (78 columnas) | deriva de esquema: trae `idPlanDeCompra` en vez de `Codigo_ConvenioMarco` |
| `oc2019.bin` | `oc-da/2019-3.zip` | primeros 20 KB (78 columnas) | ídem |
| `lic2015.bin` | `lic-da/2015-6.zip` | primeros 20 KB (105 columnas) | deriva: faltan los 6 campos de criterios ambientales/sociales; sobra `ValorTiempoRenovacion` |
| `lic2019.bin` | `lic-da/2019-3.zip` | primeros 20 KB (105 columnas) | ídem |
| `watchlist_ruts.txt` | usuario | 33 RUT, uno por línea | test del validador mod-11 (incluye `77.814.808-2`, con DV inválido) |

## Cómo leerlos

Son **bytes crudos**, no texto decodificado. El encoding es `latin-1`/`cp1252` **sin BOM** —
abrirlos como UTF-8 lanza `UnicodeDecodeError`, que es exactamente el primer test que deben
pasar.

```python
import csv, io
d = open('oc_head.bin', 'rb').read().decode('latin-1')
rows = list(csv.reader(io.StringIO(d), delimiter=';', quotechar='"'))
header = rows[0]
```

Los archivos están **truncados a mitad de fila** a propósito: la última fila de cada uno
está incompleta. Los tests deben descartarla, o usar sólo el header y las primeras filas
completas.

## Trampas que estas fixtures permiten testear

Referencia completa en [`../../docs/esquema-datos-abiertos.md`](../../docs/esquema-datos-abiertos.md) §3.

- **P1** encoding latin-1 sin BOM → `oc_head.bin`
- **P2** decimal con coma → `oc_head.bin` (`MontoTotalOC = "19977,72"`)
- **P3** newlines embebidos en campo entrecomillado → `oc_head.bin` (`Descripcion/Obervaciones`)
- **P4** `"NA"` como nulo → `oc_head.bin` (`FechaCancelacion`, `PaisProveedor`)
- **P5/P6** `1900-01-01` como sentinela, incluso en campos de dirección → `lic_head.bin`
  (`DireccionVisita`, `DireccionEntrega`)
- **P7** typos del origen → `MontoTotalDisponble` (`cot1_head.bin`),
  `NombreroductoGenerico` (`oc_head.bin`), `Nombre producto genrico` (`lic_head.bin`)
- **P8/P9** nombres con espacios, `/` y casing mixto → los tres
- **P10** columna duplicada con sufijo `.1` → `lic_head.bin`
  (`DescripcionCriteriosRequisitosSociales.1`)
- **P11** `FormaPago` vs `Forma de Pago` → `oc_head.bin`
- **P12** `;` dentro de un campo → `lic_head.bin` (`CriteriosEvaluacion`)
- **P13** región como texto con espacios finales → `cot1_head.bin` (`"Región de Tarapacá  "`)
- **P14** RUT con puntos y DV `K` → `cot1_head.bin` (`78.167.575-K`)
- **P15** moneda distinta de CLP → `oc_head.bin` (`monedaItem = "CLF"`, `precioNeto = "279,8"`)
- **Deriva de esquema** → comparar `oc2019.bin` vs `oc_head.bin`, `lic2019.bin` vs `lic_head.bin`
