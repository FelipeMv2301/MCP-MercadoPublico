Actúa como un Ingeniero de Software Senior experto en Python, arquitecturas de datos y en el protocolo MCP (Model Context Protocol).

Tu objetivo es construir un servidor MCP completo, robusto y altamente optimizado en Python utilizando el framework oficial `FastMCP` (`from mcp.server.fastmcp import FastMCP`). 

Este servidor actuará como un "Copiloto de Inteligencia Comercial" integrado con Claude para la empresa **Bioquimica.cl**, permitiendo buscar oportunidades, espiar a la competencia, analizar licitaciones ganadas/perdidas y procesar automáticamente las bases y actas adjuntas en Mercado Público de Chile.

---

### 1. REQUISITOS TÉCNICOS Y ARQUITECTURA GENERAL

1. **Framework Principal:** `FastMCP` para Python.
2. **Librerías Requeridas:** `requests`, `pydantic`, `pandas`, `pdfplumber` / `pymupdf` (FitZ), `pytesseract` (o `easyocr`) para OCR, y `openpyxl`.
3. **Autenticación Doble (Crítico):**
   - Debe leer el ticket desde la variable de entorno `MERCADO_PUBLICO_TICKET`.
   - **Regla API V1 (Licitaciones y OC):** El ticket se envía en la URL como Query Parameter (`?ticket=TICKET`).
   - **Regla API V2 (Compra Ágil):** El ticket se envía obligatoriamente en la cabecera HTTP (`headers={'ticket': TICKET}`).
4. **Optimización de Tokens (Formato TSV + XML):**
   - Para no agotar el contexto de Claude, NO conviertas tablas largas a Markdown tradicional.
   - Todo cuadro de evaluación, planilla Excel o lista de productos procesada debe devolverse formateada en **TSV (Tab-Separated Values)** delimitado por etiquetas **XML nativas de Anthropic** (ej: `<cuadro_evaluacion formato="TSV"> ... </cuadro_evaluacion>`).
5. **Resiliencia y Manejo del Límite de Cuota (Error HTTP 429):**
   - Captura cualquier respuesta HTTP 429. En lugar de lanzar una excepción que rompa el servidor, devuelve un mensaje en lenguaje natural:
     `"⚠️ Límite de cuota diaria alcanzado en la API de Mercado Público. El ticket se reiniciará a la medianoche."`

---

### 2. ESTRATEGIA DE PROCESAMIENTO DE DOCUMENTOS Y PDFs ESCANEADOS

Implementa una función helper robusta para procesar adjuntos (Bases, Actas de Adjudicación, Cuadros Comparativos):

1. **Detección de Texto vs. Imagen:** Calcula la densidad de texto extraído. Si un PDF de varias páginas devuelve menos de 100 caracteres legibles, clasifícalo como `DOCUMENTO_ESCANEADO`.
2. **OCR Automático:** Si es un documento escaneado, aplica OCR automáticamente usando `pytesseract` o `easyocr`.
3. **Estructura de Respuesta del Documento:**
   - Si el OCR logra extraer texto, envíalo a Claude indicando la etiqueta:
     `<documento_adjunto tipo="OCR_PROCESADO"> [Texto/TSV extraído] </documento_adjunto>`
   - Si el OCR falla por baja resolución o imagen ilegible, devuelve una advertencia clara para evitar alucinaciones:
     `"⚠️ DOCUMENTO_ESCANEADO_ILEGIBLE: El archivo [nombre] es una imagen sin capa de texto seleccionable y el OCR no pudo procesarlo con suficiente precisión. Notifica al usuario de esta limitación y NO inventes el contenido."`

---

### 3. HERRAMIENTAS (TOOLS) A IMPLEMENTAR EN EL MCP

Decora cada función con `@mcp.tool()` e incluye docstrings (comentarios de función) extremadamente explícitos para que Claude sepa exactamente cuándo e invocarlas.

#### Módulo 1: Oportunidades y Búsqueda Rápida
* **`buscar_compras_agiles_v2`**:
  - Consulta `https://api2.mercadopublico.cl/v2/compra-agil`.
  - Parámetros: `q` (palabras clave), `region` (int 1-16), `estado` (default 'publicada'), `publicado_desde` / `publicado_hasta` (ISO-8601), `numero_pagina`.
  - *Nota en docstring:* Aclarar a Claude que esta API no acepta `codigo_organismo` (se debe filtrar por región).
* **`obtener_detalle_oportunidad_v2`**:
  - Consulta `https://api2.mercadopublico.cl/v2/compra-agil/{codigo}`.
  - Devuelve los productos solicitados, presupuesto disponible y plazos.

#### Módulo 2: Inteligencia Competitiva
* **`consultar_oc_competencia_v1`**:
  - Consulta `https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.json` usando `CodigoProveedor` (RUT o ID del competidor).
  - Permite a Claude auditar a qué precios, en qué fechas y a qué organismos le vende la competencia a Bioquimica.cl.

#### Módulo 3: Análisis de Desempeño Propio (Bioquimica.cl)
* **`consultar_historial_bioquimica_v1`**:
  - Consulta Licitaciones u Órdenes de Compra filtrando por el `CodigoProveedor` de Bioquimica.cl y estado (`adjudicada`, `cerrada`, etc.).
  - Permite hacer "autopsias" de licitaciones ganadas y perdidas.

#### Módulo 4: Ingesta Automática y Conversión
* **`procesar_adjuntos_licitacion`**:
  - Recibe el `codigo_licitacion` o la `url_documento`.
  - Descarga el PDF/Excel, detecta si requiere OCR, convierte tablas a formato TSV envuelto en etiquetas XML y se lo entrega a Claude para análisis estratégico de requisitos o actas de evaluación.

#### Módulo 5: Gestión de Infraestructura
* **`verificar_estado_cuota`**:
  - Permite verificar el estado de la conexión a la API y las respuestas HTTP recibidas.

---

### 4. ENTREGABLES REQUERIDOS

1. **`server.py`**: El código completo en Python con todas las herramientas, decoradores y funciones de conversión (PDF/Excel a TSV/XML + OCR).
2. **`requirements.txt`**: Lista completa de dependencias de Python.
3. **`claude_desktop_config.json`**: Ejemplo de archivo de configuración listo para instalar en Windows y macOS, incluyendo la inyección de la variable de entorno `MERCADO_PUBLICO_TICKET`.
4. **Instrucciones para el System Prompt de Claude**: Un texto corto que deba agregarse a las instrucciones personalizadas de Claude para actuar como el Estratega de Licitaciones de Bioquimica.cl.

Escribe el código siguiendo los estándares PEP 8, asegurando que sea robusto frente a caídas de red y aplicando tipado estricto (`typing`).