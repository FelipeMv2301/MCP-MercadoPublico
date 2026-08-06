# Conector en claude.ai — HU-7.4

## 1. Instrucciones personalizadas (pegar en claude.ai)

Van en **Configuración → Personalización → Instrucciones personalizadas** (o en las
instrucciones de un Proyecto, si el uso es siempre desde ahí). Complementan — no
reemplazan — el campo `instructions` que el servidor ya envía por protocolo MCP
(`server.py`, variable `INSTRUCCIONES`); Claude puede necesitar el recordatorio en un
lugar que el usuario controla directamente.

```
Cuando uses el conector "mercado-publico-bioquimica":

1. MARKET-CENTRIC: nunca concluyas sobre precios o competencia a partir sólo del
   historial de Bioquimica.cl — el 67% de su catálogo tiene una sola línea de venta
   al mes, no alcanza para ninguna estadística. Usa siempre las tools de mercado
   (benchmark_precio, descubrir_rivales, etc.), que agregan sobre todo el lake.

2. CANAL: el 76% del negocio de Bioquimica.cl entra por compra ágil, no licitación.
   Ante una pregunta genérica sobre "cómo nos está yendo" o "cómo cotizar", prioriza
   compra ágil salvo que la pregunta sea explícitamente sobre licitaciones.

3. FRESCURA: el data lake es histórico. Cotizaciones de compra ágil (COT) tienen
   ~1 mes de rezago; licitaciones y órdenes de compra ~1 día. Para "qué está abierto
   HOY" usa el conector LicitaLab o la API en línea, no el lake — el lake sirve para
   calibrar precio/argumento, no para detectar oportunidades del momento.

4. DIVISIÓN DE TRABAJO: LicitaLab detecta oportunidades abiertas; este MCP calibra
   precio y analiza competencia sobre el histórico. Son complementarios: LicitaLab
   dice "esto se abrió", este MCP dice "a qué precio y contra quién".

5. CONFIANZA: toda tool de precio devuelve `metodo_resolucion` y `confianza` (de
   resolver_producto) y muchas devuelven `n`/`muestra_insuficiente`. Repórtaselo
   siempre al usuario en la respuesta — no presentes un precio de mercado sin decir
   qué tan bien identificado está el producto o qué tan chica es la muestra.

6. EL PRECIO NO ES EL ÚNICO CRITERIO: antes de sugerir bajar precio para ganar una
   licitación o cotización, cruza con criterios_que_deciden — en varios casos
   medidos, el ganador no fue el más barato (plazo de entrega, experiencia, etc.
   pesaron más).
```

## 2. Registrar el conector (pasos esperados)

⚠️ No pude verificar la UI exacta de claude.ai sin poder navegar ahí en este momento
— confirmamos juntos el detalle cuando lleguemos a esta parte. La secuencia esperada:

1. **claude.ai → Configuración → Conectores → Agregar conector personalizado.**
2. **URL del servidor:** `https://<dominio-de-railway>.up.railway.app/mcp`
   (el dominio real lo asigna Railway al desplegar — HU-7 del deploy).
3. **Autenticación:** el servidor exige `Authorization: Bearer <MCP_AUTH_TOKEN>`
   (HU-7.1). Si claude.ai permite un header personalizado o un campo "API key/token"
   al agregar el conector, ahí va el mismo valor de `MCP_AUTH_TOKEN` configurado en
   Railway. **Si claude.ai sólo ofrece OAuth para conectores remotos** (sin opción de
   header estático), este esquema de auth no calzaría directo con esa UI — lo
   evaluamos en el momento y, de ser necesario, se ajusta (opción más simple:
   confirmar primero si soporta headers personalizados antes de descartarlo).
4. Guardar y probar: pedirle a Claude que llame `verificar_estado` — debe devolver
   el RUT/código de proveedor de Bioquimica.cl (confirma que `identidad.toml` se
   leyó bien en el contenedor desplegado).

## 3. Prueba de aceptación conversacional (5 preguntas)

Antes de considerar el conector "en producción", correr estas 5 preguntas reales
desde claude.ai y confirmar que las respuestas usan las tools correctas:

| # | Pregunta | Tool(s) esperada(s) |
| :-- | :-- | :-- |
| 1 | "¿Contra quién compito en licitaciones de material didáctico?" | `descubrir_rivales(canal="lic")` |
| 2 | "¿A qué precio se vendió el ácido cítrico en compra ágil este año?" | `resolver_producto` → `benchmark_precio` |
| 3 | "¿Por qué perdimos la cotización X?" (con un código real) | `postmortem` |
| 4 | "¿Nos conviene bajar el precio para ganarle a [rival]?" | `precio_para_ganar` + `criterios_que_deciden` |
| 5 | "¿Qué compra la Universidad de Talca y con qué frecuencia?" | `perfil_comprador` |

Cada respuesta debe: (a) usar la tool correspondiente, no inventar el dato; (b)
declarar `n`/confianza cuando la tool lo entrega; (c) si la pregunta es sobre HOY
("¿qué está abierto ahora?"), Claude debe aclarar que el lake es histórico y sugerir
LicitaLab/API en línea en vez de inventar una respuesta desde datos viejos.
