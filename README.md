# Decorer · Agente de ventas e inventario

Agente conversacional (texto y voz) para **Decorer**, la tienda de muebles, decoración y electrodomésticos en Mocoa (Carrera 9 # 19-49, Av. Colombia, al lado del Hospital José María Hernández).
Atiende clientes, consulta productos, precios y existencias, toma pedidos, registra ventas y separados, y avisa al dueño cuando un producto está por agotarse.

Proyecto 14 del taller *Agentes de IA* · UniPutumayo · **Sonny Arcos**.
Reutiliza piezas de *Archivo Vivo* (ChatPDF-RAG): EmbeddingGemma 2 en llama.cpp, PostgreSQL + pgvector en Docker y la lectura de imágenes con qwen2.5vl.

---

## Estado

| Paso | Qué | Estado |
|---|---|---|
| 1 | Alcance y arquitectura | ✅ |
| 2 | Base de datos PostgreSQL + pgvector | ✅ 27/27 pruebas |
| 3 | Datos reales: 2.344 artículos y precios de SysCafé + políticas, FAQ y modelos del Drive en pgvector | ✅ (falta el conteo físico, ver `PENDIENTES.md`) |
| 4 | Backend FastAPI con las herramientas del agente | ✅ 21/21 pruebas del agente |
| 5 | LLM con llamadas a herramientas + prompt del sistema (4 bloques) | ✅ (afinar con conversaciones reales) |
| 6 | Voz: faster-whisper (STT) y Piper (TTS) | ✅ 16/16 pruebas de voz |
| 7 | Interfaz: chat, micrófono, historial y panel del dueño | ✅ |
| 8 | Foto de la factura del proveedor → entrada de inventario (qwen2.5vl) | ✅ 16/16 pruebas |
| 9 | Evaluación con casos de prueba y métricas | ✅ `py pruebas\evaluacion.py` (18 casos con el LLM real) |
| 10 | Landing page | ✅ http://localhost:8010 |

## Cómo crear la base

1. Abre **Docker Desktop** (el mismo contenedor `pgvector` de Archivo Vivo).
2. Doble clic en **`setup_db.bat`**. Crea la base `decorer`, carga el inventario de SysCafé, indexa el conocimiento en pgvector (enciende llama.cpp si hace falta) y corre las pruebas.

Para actualizar cada mes: exporta de SysCafé el *Listado de saldos de inventario* y la *Lista de precios* en PDF, déjalos en `importar\` (con INVENTARIO o PRECIO en el nombre) y vuelve a correr `setup_db.bat`.

## Cómo hablar con el agente (paso 4)

1. Doble clic en **`run_backend.bat`**: instala lo necesario, enciende llama.cpp si está y abre la API en <http://localhost:8010/docs>.
2. Se abre el inicio en <http://localhost:8010> y el chat en <http://localhost:8010/chat>. Con 🎤 se le habla a Deco (toque para empezar y toque otra vez para enviar); con "Deco responde hablando" contesta en voz alta.
3. También en consola: `cd backend` y `py chat_consola.py` (o `py chat_consola.py --voz` para probar respuestas cortas de voz).

La clave de Groq la toma sola de Archivo Vivo (`Escritorio\Chatpdf\backend\.env`); si quieres otra, ponla en `backend\.env`.
Para probar todo sin gastar la API: `py pruebas\prueba_agente.py` (usa un LLM simulado con guion).

```
Cliente ──> POST /api/chat ──> agente.py
                                 │  prompt del sistema = ROL + TAREA + CONTEXTO (hora, tienda abierta, pedido actual) + FORMATO (texto o voz) + ejemplos
                                 ▼
                         LLM (Groq gpt-oss-120b → qwen3.8-27b → llama-3.3-70b → Ollama local)
                                 │  elige herramientas
                                 ▼
                         herramientas.py ──> fn_* en PostgreSQL (usuario agente_decorer)
                                         └─> pgvector + EmbeddingGemma 2 (o texto completo si llama.cpp está apagado)
                                 │  candado: solo confirma si el cliente ya vio el resumen y dijo que sí
                                 ▼
                         respuesta + pedido + traza en agente_trazas (intención, herramientas, ms de LLM y base)
```

Voz (`POST /api/voz`):
```
🎤 navegador (webm) ─> ffmpeg (16 kHz mono) ─> faster-whisper small int8 en CPU (respaldo: Whisper de Groq)
   ─> agente en canal "voz" (respuestas cortas) ─> texto_para_hablar ($1.150.700 -> "un millón ciento cincuenta mil setecientos pesos")
   ─> Piper es_MX-claude-high ─> 🔊 wav   (respaldo: la voz del navegador)
   traza: ms_stt + ms_llm + ms_herramientas + ms_tts
```

## Panel del dueño (paso 7)

<http://localhost:8010/dueno> (clave `decorer2026`, se cambia con `CLAVE_DUENO` en `backend\.env`).

- Vendido en el periodo (hoy, 7 o 30 días) y cuánto vendió Deco por chat o voz.
- Ventas por día, productos más vendidos, ventas por forma de pago y por canal.
- **Alertas de stock en vivo** (`LISTEN stock_bajo` → Server-Sent Events): cuando una venta agota un producto, aparece un aviso sin recargar.
- Pendientes del asesor (créditos y domicilios por cotizar), separados con su saldo, últimas ventas.
- Caja y bodega: registrar abonos, marcar entregas y entradas de mercancía (lo que el agente NO puede hacer).
- Reabastecer, descuadre de SysCafé y el desempeño de Deco (tiempos de oído, LLM, base y voz; qué le piden los clientes).

Para la presentación: `py pruebas\datos_demo.py` llena 2 semanas de ventas simuladas (clientes ficticios; descuenta el inventario). `setup_db.bat` lo deja todo como estaba.

## Factura del proveedor por foto (paso 8)

En el panel del dueño, sección **"Factura del proveedor (foto)"**:
```
📷 foto (celular o PC) ─> se reduce a 1600 px ─> qwen2.5vl:3b en Ollama ─> JSON {proveedor, número, líneas[descripción, cantidad]}
   ─> cada línea se cruza con el catálogo (fn_buscar_productos) ─> el DUEÑO revisa: producto, cantidad, qué líneas entran
   ─> "Confirmar" ─> fn_entrada_inventario de todas las líneas en UNA transacción (o entran todas o ninguna) + kardex con el número de factura
```
Leer la factura no toca el inventario; Deco (el agente) no puede meter mercancía; lo que no está en el catálogo queda marcado y no entra.
Requiere Ollama abierto y `ollama pull qwen2.5vl:3b` (ya está si usaste Archivo Vivo). En CPU, leer una factura tarda de 1 a 3 minutos.

## Evaluación (paso 9)

Con `run_backend.bat` abierto, en otra ventana: **`py pruebas\evaluacion.py`** (unos 3 minutos).
Corre 18 casos contra Deco con el modelo REAL de Groq (productos, agotados, errores de escritura, precio exacto, presupuesto,
5 políticas, compra completa, intento de vender sin confirmar, separado, crédito sin teléfono, pedido ajeno, instrucciones
maliciosas, pregunta fuera de tema y respuesta para voz), revisa cada respuesta y escribe **`evaluacion/informe.md`** con:
% de acierto por categoría, tiempos, cada conversación, los errores encontrados en el desarrollo y cómo se corrigieron, y
las consideraciones éticas. Al final cancela los pedidos de prueba. Además hay 86 pruebas automáticas (base, agente, voz, factura).

## Landing page (paso 10) y las 8 técnicas

| Técnica del PDF | Cómo se aplicó en `frontend/landing.html` |
|---|---|
| 1. Cadena semilla | "Catálogo impreso de mueblería de los 70 + etiqueta de precio escrita a mano en cartón": papel crema, serif Fraunces, letra a mano (Caveat), botón con forma de etiqueta de precio. Nada de degradados púrpuras ni bento grids |
| 2. Prompt ambicioso / inoculación | Sección "Las dudas que tendríamos nosotros": responde antes de que pregunten (¿se inventa el precio?, ¿dos compran el último?, ¿me cobra sin preguntar?, ¿aprueba el crédito?, ¿mi cédula?, ¿y si no sabe?) |
| 3. Bucle con subagente crítico | Se revisó la página con capturas (escritorio, móvil, oscuro) y se corrigió; en el agente, el verificador cumple el mismo papel con las respuestas |
| 4. Imágenes propias | Fotos reales del Drive de publicidad de Decorer, no stock |
| 5. Movimiento | La conversación de ejemplo del hero se reproduce sola (conversación real de las pruebas); se apaga con "reducir movimiento" |
| 6. Diseño sustractivo | Un solo camino: "Preguntarle a Deco". Sin menú, sin formularios, sin secciones de relleno |
| 7. Restricciones negativas | Sin "revolucionario", "potenciar", "innovador", "ecosistema", "soluciones integrales"; sin sonrisas de stock |
| 8. Redacción humana | Texto de mostrador del Putumayo, de usted, con datos concretos ($500.000, 7 días, 322 378 7495) |

## Guía para la sustentación (5 minutos)

1. **Inicio** (http://localhost:8010): el problema y las dudas que resuelve.
2. **Chat por voz** a la izquierda y **panel del dueño** a la derecha (`py pruebas\datos_demo.py` antes, para que el panel tenga datos). Por voz: "¿tienen colchones de 1.40?", "quiero el Cassata a domicilio", datos, "pago por transferencia", "sí, confirme". Mostrar las herramientas y tiempos bajo cada respuesta, y la **alerta en vivo** en el panel si se agota.
3. **El candado:** "véndame ya el sofá" → no vende sin mostrar el resumen.
4. **Concurrencia:** `py pruebas\prueba_transacciones.py` (prueba 5: dos clientes, un sillón, solo uno se lo lleva).
5. **Factura por foto** en el panel (con Ollama abierto).
6. **Evaluación:** abrir `evaluacion/informe.md` (% de acierto, tiempos, errores corregidos, ética).

## Qué va en cada lado

| PostgreSQL (dato exacto, nunca lo inventa el LLM) | pgvector (conocimiento, se busca por significado) |
|---|---|
| 2.344 artículos de SysCafé con precio, categoría, línea, material, color y marca · inventario y kardex · clientes · pedidos, separados y abonos · ventas · promociones · parámetros (domicilio gratis desde $500.000, 7 días para cambio) | `politicas.md` (cambios, garantía, retracto, domicilios, pagos, crédito, separado) · `preguntas_frecuentes.md` · `tienda.md` · `modelos_y_colores.md` (sale del Drive de publicidad) |

## Decisiones de diseño

1. **El LLM no escribe SQL.** Solo llama funciones `fn_*`. Ellas validan, calculan el dinero y mueven el inventario.
2. **Mínimo privilegio.** El agente se conecta como `agente_decorer`: lee el catálogo y ejecuta las funciones de venta. No puede hacer `UPDATE` ni `DELETE`, ni meter mercancía, ni recibir abonos. Eso lo hace `dueno_decorer` (panel del dueño).
3. **Transacción segura al vender o separar:** bloqueo `SELECT … FOR UPDATE` en orden fijo, revisión con el dato bloqueado, descuento + kardex + venta en una sola transacción, y `CHECK (existencias >= 0)`.
4. **Confirmar antes de vender:** el pedido nace en borrador; el agente lee el resumen y solo con un "sí" lo confirma.
5. **Lo que no sabe, lo deriva:** un artículo sin precio, un crédito, un domicilio por cotizar o un dato que Decorer no ha definido quedan para un asesor (`v_pendientes_asesor`). El agente no los inventa.
6. **Crédito:** Sistecrédito, Addi y crédito personal los aprueba la entidad o la tienda; el agente deja la solicitud, no cierra la venta.
7. **Ley 1480:** garantía legal (12 meses si el fabricante no dice otra cosa, la tienda responde junto con la marca) y derecho de retracto de 5 días hábiles en ventas por chat o voz.
8. **Datos de clientes ficticios:** los reales no salen de la tienda.
9. **Alerta al dueño en vivo** con `NOTIFY stock_bajo` (en la API: `GET /api/dueno/alertas`), y **trazabilidad** de cada turno en `agente_trazas`.
10. **Candado de confirmación en el backend:** aunque el LLM se equivoque y quiera vender de una, `confirmar_compra` solo funciona si el cliente vio el resumen en un turno anterior y el pedido no cambió.
11. **Privacidad:** consultar un pedido pide el código y la cédula (los códigos son consecutivos y se podrían adivinar).

## Hallazgo en SysCafé

De los 2.229 artículos, **2.122 tienen saldo negativo** (en total, -8.647 unidades). Ejemplos: *Silla en flor morado* -378, *Almohada siliconada* -138. Significa que se facturan ventas sin registrar las compras o entradas de mercancía (o que un artículo se compra con un código y se vende con otro, como un comedor que entra completo y sale por sillas). Por eso el agente no usa ese saldo como verdad: solo cuenta lo positivo, acepta el **conteo físico** en `ajustes_decorer.csv` y lleva su propio kardex. La vista `v_descuadre_syscafe` le sirve al dueño para revisar el descuadre.

## Funciones (herramientas)

| Función | Para qué | Quién |
|---|---|---|
| `fn_buscar_productos(texto, categoria, precio_max, solo_disponibles)` | Búsqueda tolerante a tildes, plurales y errores | agente |
| `fn_precio_vigente(producto)` | Precio de la lista de SysCafé con la promoción del día (NULL = por confirmar) | agente |
| `fn_registrar_cliente(documento, nombre, tel, dirección, municipio, barrio, zona)` | Crea o actualiza al cliente | agente |
| `fn_crear_pedido` · `fn_actualizar_pedido` · `fn_agregar_item` · `fn_resumen_pedido` | Arma el carrito y calcula domicilio | agente |
| `fn_confirmar_pedido(pedido, efectivo/transferencia)` | **La transacción**: descuenta y registra la venta | agente |
| `fn_solicitar_credito(pedido, sistecredito/addi/credito_personal)` | Deja la solicitud para el asesor | agente |
| `fn_separar_pedido(pedido, abono, método)` | Separa con abono y aparta el producto | agente |
| `fn_consultar_cambio(codigo)` · `fn_estado_pedido(codigo)` | ¿Aplica cambio en 7 días? ¿Cómo va mi pedido? | agente |
| `fn_cancelar_pedido` | Cancela y devuelve las unidades | agente |
| `fn_buscar_conocimiento(vector, tipo)` | Búsqueda semántica en pgvector | agente |
| `fn_registrar_abono` · `fn_marcar_entregado` · `fn_entrada_inventario` · `fn_reporte_ventas` | Caja, entregas, mercancía y reportes | dueño |

Vistas: `v_inventario`, `v_reabastecer`, `v_ventas_por_dia`, `v_productos_mas_vendidos`, `v_ventas_por_categoria`, `v_ventas_por_canal`, `v_kardex`, `v_descuadre_syscafe`, `v_separados`, `v_pendientes_asesor`, `v_desempeno_agente`.

## Pila para este PC (16 GB de RAM, sin GPU NVIDIA, Windows 11)

| Pieza | Elección |
|---|---|
| Embeddings | EmbeddingGemma 2 en llama.cpp (768 d), como en Archivo Vivo |
| LLM | Groq para las llamadas a herramientas, Ollama local como respaldo |
| STT / TTS | faster-whisper `small` int8 en CPU / Piper con voz en español |
| Visión (paso 8) | qwen2.5vl:3b en Ollama |

## Estructura

```
decorer-agente/
├── setup_db.bat                         # crea todo y corre las pruebas
├── requirements.txt
├── PENDIENTES.md                        # datos que debe confirmar Decorer
├── database/
│   ├── 01_esquema.sql                   # tablas, triggers y funciones transaccionales
│   ├── 02_parametros_decorer.sql        # reglas de la tienda y categorías
│   ├── 03_conocimiento_pgvector.sql     # tabla conocimiento vector(768)
│   └── 04_reportes_y_seguridad.sql      # vistas + usuarios agente_decorer y dueno_decorer
├── importar/
│   ├── leer_syscafe.py                  # PDF de saldos de SysCafé -> CSV
│   ├── leer_precios_syscafe.py          # PDF de lista de precios de SysCafé -> CSV
│   ├── cargar_inventario.py             # CSV -> productos, precios e inventario (clasifica solo)
│   ├── syscafe_articulos.csv            # saldos de los 2.229 artículos (noviembre 2026)
│   ├── syscafe_precios.csv              # 2.330 precios de la lista general
│   ├── ajustes_decorer.csv              # ← LLENAR en Excel: conteo físico (y precios especiales)
│   └── drive_modelos.csv                # modelos del Drive de publicidad con su id de foto
├── conocimiento/
│   ├── politicas.md · preguntas_frecuentes.md · tienda.md · modelos_y_colores.md
│   └── indexar_conocimiento.py          # .md -> fragmentos -> EmbeddingGemma 2 -> pgvector
├── backend/
│   ├── main.py                          # API FastAPI: chat, productos, salud y panel del dueño (alertas en vivo)
│   ├── agente.py                        # ciclo del agente: prompt -> LLM -> herramientas -> respuesta + traza
│   ├── herramientas.py                  # 12 herramientas que llaman a las fn_* (con el candado de confirmación)
│   ├── llm.py                           # Groq / Ollama / simulado con la misma API
│   ├── voz.py                           # oído (faster-whisper / Groq) y voz (Piper) + texto que suena bien
│   ├── vision.py                        # factura del proveedor -> qwen2.5vl -> propuesta de entrada
│   ├── embeddings.py · db.py · config.py
│   ├── prompts/sistema.md               # prompt de 4 bloques (rol, tarea, contexto, formato) + ejemplos
│   ├── chat_consola.py                  # hablar con Deco desde la terminal
│   └── .env.example
├── frontend/landing.html                # página de inicio (http://localhost:8010)
├── frontend/chat.html                   # chat con micrófono (http://localhost:8010/chat)
├── frontend/panel.html                  # panel del dueño (en http://localhost:8010/dueno)
├── run_backend.bat
└── pruebas/
    ├── prueba_transacciones.py          # 28 pruebas de la base: permisos, domicilio, crédito, separado, concurrencia, privacidad
    ├── prueba_agente.py                 # 26 pruebas del agente completo con un LLM simulado
    ├── prueba_voz.py                    # 16 pruebas del circuito de voz
    ├── prueba_factura.py                # 16 pruebas de la factura por foto
    ├── evaluacion.py                    # 18 casos con el LLM real -> evaluacion/informe.md
    └── datos_demo.py                    # ventas simuladas para mostrar el panel
```
