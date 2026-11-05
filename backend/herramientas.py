"""
herramientas.py - Las "manos" del agente.

Cada herramienta llama a UNA función de PostgreSQL (fn_*) o a la búsqueda en pgvector.
El LLM solo elige la herramienta y sus argumentos; los precios, totales y existencias
siempre salen de la base. El carrito (pedido en borrador) lo lleva la conversación,
así el modelo no tiene que recordar números de pedido.

Candado de confirmación: confirmar_compra y separar_producto solo funcionan si el
cliente ya vio el resumen del pedido en un turno anterior y el pedido no cambió desde
entonces. Aunque el LLM se equivoque, no se puede vender algo que el cliente no aceptó.
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import psycopg

import config
import db
import embeddings


def pesos(n) -> Optional[str]:
    if n is None:
        return None
    return "$" + f"{int(n):,}".replace(",", ".")


# ── Estado de cada conversación ───────────────────────────────────────────────
@dataclass
class Estado:
    conversacion_id: str
    canal: str = "texto"
    cliente_id: Optional[int] = None
    pedido_id: Optional[int] = None
    tiene_telefono: bool = False
    version_pedido: int = 0           # sube cada vez que cambia el carrito
    version_vista: int = -1           # versión del resumen que el cliente ya vio (turno anterior)
    resumen_en_este_turno: bool = False
    derivado: bool = False
    herramientas_usadas: list = field(default_factory=list)
    fotos: list = field(default_factory=list)


_estados: dict = {}


def estado(conversacion_id: str, canal: str = "texto") -> Estado:
    """Recupera el estado (el cliente y el carrito se guardan en la tabla conversaciones)."""
    if conversacion_id not in _estados:
        with db.agente() as c:
            fila = c.execute("SELECT cliente_id, pedido_id, canal FROM conversaciones WHERE id = %s",
                             (conversacion_id,)).fetchone()
        e = Estado(conversacion_id, canal=(fila or {}).get("canal") or canal)
        if fila:
            e.cliente_id, e.pedido_id = fila["cliente_id"], fila["pedido_id"]
        _estados[conversacion_id] = e
    return _estados[conversacion_id]


def _guardar_vinculos(e: Estado):
    with db.agente() as c:
        c.execute("UPDATE conversaciones SET cliente_id = %s, pedido_id = %s WHERE id = %s",
                  (e.cliente_id, e.pedido_id, e.conversacion_id))


def _resumen(c, pedido_id) -> Optional[dict]:
    r = c.execute("SELECT fn_resumen_pedido(%s) AS r", (pedido_id,)).fetchone()["r"]
    if not r:
        return None
    r["total_texto"] = pesos(r["total"])
    r["subtotal_texto"] = pesos(r["subtotal"])
    r["descuento_texto"] = pesos(r["descuento"])
    r["domicilio_texto"] = "por confirmar con un asesor" if r["domicilio_por_confirmar"] else (
        "gratis" if r["con_domicilio"] and not r["domicilio"] else pesos(r["domicilio"]))
    if r.get("falta_para_domicilio_gratis"):
        r["falta_para_domicilio_gratis_texto"] = pesos(r["falta_para_domicilio_gratis"])
    for it in r["items"]:
        it["precio_texto"] = pesos(it["precio_unitario"] - it["descuento_unitario"])
        it["subtotal_texto"] = pesos(it["subtotal"])
    return r


def _pedido_abierto(e: Estado, c) -> Optional[dict]:
    """El carrito de la conversación, si sigue en borrador."""
    if not e.pedido_id:
        return None
    r = _resumen(c, e.pedido_id)
    if not r or r["estado"] != "borrador":
        return None
    return r


# ── Las herramientas ──────────────────────────────────────────────────────────
def url_foto(drive_id, ancho=600):
    return f"https://drive.google.com/thumbnail?id={drive_id}&sz=w{ancho}" if drive_id else None


def _filas_productos(texto, categoria, precio_max, solo_disponibles, limite=5):
    with db.agente() as c:
        filas = c.execute("SELECT * FROM fn_buscar_productos(%s, %s, %s, %s, %s)",
                          (texto or None, categoria or None, precio_max, bool(solo_disponibles), limite)).fetchall()
        ids = [f["producto_id"] for f in filas]
        fotos = {r["id"]: r["drive_id"] for r in c.execute(
            "SELECT id, drive_id FROM productos WHERE id = ANY(%s) AND drive_id IS NOT NULL", (ids,)).fetchall()} if ids else {}
    for f in filas:
        f["drive_id"] = fotos.get(f["producto_id"])
    return filas


def buscar_productos(e, texto=None, categoria=None, precio_max=None, solo_disponibles=False):
    filas = _filas_productos(texto, categoria, precio_max, solo_disponibles)
    nota = None
    if not filas and solo_disponibles:
        # No hay unidades en el almacén, pero el producto SÍ existe en el catálogo: no decir "no tenemos"
        filas = _filas_productos(texto, categoria, precio_max, False)
        if filas:
            nota = ("En este momento no hay unidades en el almacén, pero Decorer sí maneja estos productos: "
                    "dile al cliente que están agotados y que un asesor le confirma si se pueden pedir por encargo.")
    if not filas:
        nota = "No encontré productos con esa búsqueda en el catálogo. Pregunta por otra palabra o deriva a un asesor."
    resultados = []
    for f in filas:
        r = {"producto_id": f["producto_id"], "nombre": f["nombre"],
             "precio": pesos(f["precio_final"]) if not f["precio_por_confirmar"] else "por confirmar con un asesor",
             "disponibilidad": f"disponible ({f['existencias']} und.)" if f["disponible"] else "agotado, se puede pedir por encargo"}
        if f["promocion"]:
            r["promocion"], r["precio_antes"] = f["promocion"], pesos(f["precio_lista"])
        if f["color"]:
            r["color"] = f["color"]
        if f["material"]:
            r["material"] = f["material"]
        if f.get("drive_id"):
            r["tiene_foto"] = True          # la foto la pone el chat solo; el LLM no necesita el enlace
            e and e.fotos.append({"titulo": f["nombre"], "url": url_foto(f["drive_id"]), "drive_id": f["drive_id"],
                                  "referencia": True})
        resultados.append(r)
    return {"resultados": resultados, "nota": nota}


def ver_fotos(e, texto):
    """Fotos del catálogo del Drive de Decorer (salas, sofacamas, comedores, Maderkit)."""
    palabras = [w for w in re.sub(r"[^\wáéíóúñ ]", " ", (texto or "").lower()).split() if len(w) > 2]
    with db.agente() as c:
        filas = c.execute("""
            SELECT modelo, drive_id, carpeta FROM fotos_catalogo
            WHERE NOT EXISTS (SELECT 1 FROM unnest(%s::text[]) w
                              WHERE unaccent(lower(modelo || ' ' || carpeta)) NOT LIKE '%%' || unaccent(rtrim(w, 's')) || '%%')
            ORDER BY similarity(unaccent(lower(modelo)), unaccent(lower(%s))) DESC LIMIT 4""", (palabras, texto)).fetchall()
        if not filas:
            filas = c.execute("""SELECT modelo, drive_id, carpeta FROM fotos_catalogo
                                 WHERE word_similarity(unaccent(lower(%s)), unaccent(lower(modelo || ' ' || carpeta))) > 0.4
                                 ORDER BY similarity(unaccent(lower(modelo)), unaccent(lower(%s))) DESC LIMIT 4""",
                              (texto, texto)).fetchall()
    for f in filas:
        e and e.fotos.append({"titulo": f["modelo"].title(), "url": url_foto(f["drive_id"]), "drive_id": f["drive_id"],
                              "referencia": True})
    return {"fotos_mostradas": [f["modelo"].title() for f in filas],
            "nota": ("Las fotos ya se muestran en el chat (son de referencia: el color o la tela pueden variar). "
                     "No escribas enlaces." if filas else
                     f"No hay fotos de '{texto}' en el catálogo; ofrece pedirlas por WhatsApp {config.TIENDA['whatsapp']}.")}


def buscar_informacion(e, pregunta, tipo=None):
    """Políticas, preguntas frecuentes, datos de la tienda y modelos (pgvector)."""
    with db.agente() as c:
        try:
            vec = embeddings.vector_pregunta(pregunta)
            filas = c.execute("SELECT titulo, contenido, fuente, similitud AS puntaje "
                              "FROM fn_buscar_conocimiento(%s::vector, %s, 2, 0.35)", (vec, tipo)).fetchall()
            metodo = "pgvector (EmbeddingGemma 2)"
        except embeddings.EmbeddingsApagados:
            filas = []
            metodo = None
        if not filas:   # llama.cpp apagado o nada parecido: búsqueda de texto completo
            filas = c.execute("SELECT titulo, contenido, fuente, puntaje FROM fn_buscar_conocimiento_texto(%s, %s, 2)",
                              (pregunta, tipo)).fetchall()
            metodo = metodo and metodo + " + texto" or "texto completo (respaldo)"
    return {"metodo": metodo, "fragmentos": [
        {"titulo": f["titulo"], "texto": f["contenido"], "fuente": f["fuente"], "puntaje": round(float(f["puntaje"]), 3)}
        for f in filas]}


def registrar_cliente(e, documento, nombre, telefono=None, direccion=None, barrio=None, municipio="Mocoa", zona="urbana"):
    with db.agente() as c:
        e.cliente_id = c.execute("SELECT fn_registrar_cliente(%s,%s,%s,%s,%s,%s,%s) AS id",
                                 (documento, nombre, telefono, direccion, municipio or "Mocoa", barrio,
                                  zona or "urbana")).fetchone()["id"]
        e.tiene_telefono = e.tiene_telefono or bool((telefono or "").strip())
        r = None
        if _pedido_abierto(e, c):
            c.execute("SELECT fn_actualizar_pedido(%s, %s, NULL)", (e.pedido_id, e.cliente_id))
            e.version_pedido += 1          # con la dirección puede cambiar el domicilio: hay que mostrar el resumen
            e.resumen_en_este_turno = True
            r = _resumen(c, e.pedido_id)
    _guardar_vinculos(e)
    return {"ok": True, "cliente": nombre, "pedido": r}


def agregar_al_pedido(e, producto_id, cantidad=1, con_domicilio=None):
    with db.agente() as c:
        if not _pedido_abierto(e, c):
            e.pedido_id = c.execute("SELECT fn_crear_pedido(%s, %s, %s) AS id",
                                    (e.cliente_id, e.canal if e.canal in ("texto", "voz") else "texto",
                                     bool(con_domicilio))).fetchone()["id"]
            _guardar_vinculos(e)
        else:
            actual = _resumen(c, e.pedido_id)
            ya_esta = any(i["producto_id"] == int(producto_id) and i["cantidad"] == int(cantidad) for i in actual["items"])
            mismo_dom = con_domicilio is None or bool(con_domicilio) == actual["con_domicilio"]
            if ya_esta and mismo_dom:
                # Nada cambió: no se reinicia la confirmación (el cliente ya vio este resumen)
                return {"ok": True, "nota": "Ese producto ya estaba en el pedido con esa cantidad.", "pedido": actual}
            if con_domicilio is not None:
                c.execute("SELECT fn_actualizar_pedido(%s, NULL, %s)", (e.pedido_id, con_domicilio))
        c.execute("SELECT fn_agregar_item(%s, %s, %s)", (e.pedido_id, int(producto_id), int(cantidad)))
        e.version_pedido += 1
        e.resumen_en_este_turno = True
        return {"ok": True, "pedido": _resumen(c, e.pedido_id)}


def definir_entrega(e, con_domicilio):
    with db.agente() as c:
        if not _pedido_abierto(e, c):
            return {"error": "Todavía no hay productos en el pedido."}
        c.execute("SELECT fn_actualizar_pedido(%s, NULL, %s)", (e.pedido_id, bool(con_domicilio)))
        e.version_pedido += 1
        e.resumen_en_este_turno = True
        return {"ok": True, "pedido": _resumen(c, e.pedido_id)}


def ver_pedido(e):
    with db.agente() as c:
        if not e.pedido_id:
            return {"pedido": None, "nota": "El cliente todavía no tiene productos en el pedido."}
        r = _resumen(c, e.pedido_id)
        if r and r["estado"] == "borrador":
            e.resumen_en_este_turno = True
        return {"pedido": r}


def _candado(e, c) -> Optional[dict]:
    r = _pedido_abierto(e, c)
    if not r or not r["items"]:
        return {"error": "No hay un pedido en borrador con productos.", "tipo": "sin_pedido"}
    if not e.cliente_id:
        return {"error": "Antes de cerrar la compra registra al cliente (documento y nombre).", "tipo": "falta_cliente"}
    if e.version_vista != e.version_pedido:
        return {"error": "El cliente aún no ha visto el resumen final de este pedido. Muéstrale el resumen "
                         "(productos, total y entrega) y pregúntale si confirma.", "tipo": "falta_confirmacion"}
    return None


def confirmar_compra(e, metodo_pago, cliente_confirmo=False):
    with db.agente() as c:
        bloqueo = _candado(e, c)
        if bloqueo:
            return bloqueo
        if not cliente_confirmo:
            return {"error": "Falta que el cliente diga explícitamente que confirma.", "tipo": "falta_confirmacion"}
        r = c.execute("SELECT fn_confirmar_pedido(%s, %s, 'agente') AS r", (e.pedido_id, metodo_pago)).fetchone()["r"]
        return {"ok": True, "pedido": _resumen(c, r["pedido_id"]),
                "siguiente_paso": "Darle al cliente el código del pedido. Si pagó por transferencia, que envíe el "
                                  f"comprobante al WhatsApp {config.TIENDA['whatsapp']}."}


def separar_producto(e, abono, metodo_pago, cliente_confirmo=False):
    with db.agente() as c:
        bloqueo = _candado(e, c)
        if bloqueo:
            return bloqueo
        if not cliente_confirmo:
            return {"error": "Falta que el cliente diga explícitamente que confirma.", "tipo": "falta_confirmacion"}
        c.execute("SELECT fn_separar_pedido(%s, %s, %s, 'agente')", (e.pedido_id, abono, metodo_pago))
        r = _resumen(c, e.pedido_id)
        r["saldo_texto"] = pesos(r["saldo"])
        r["abonado_texto"] = pesos(r["abonado"])
        return {"ok": True, "pedido": r}


def solicitar_credito(e, entidad):
    with db.agente() as c:
        if not _pedido_abierto(e, c):
            return {"error": "Primero agrega al pedido el producto que quiere a crédito.", "tipo": "sin_pedido"}
        if not e.cliente_id or not e.tiene_telefono:
            return {"error": "Para que el asesor lo llame para el estudio de crédito, pide cédula, nombre y TELÉFONO "
                             "y usa registrar_cliente.", "tipo": "falta_telefono"}
        c.execute("SELECT fn_solicitar_credito(%s, %s)", (e.pedido_id, entidad))
        e.derivado = True
        return {"ok": True, "pedido": _resumen(c, e.pedido_id),
                "siguiente_paso": f"Un asesor de Decorer lo contacta para el estudio de crédito ({entidad}). "
                                  f"También puede escribir al WhatsApp {config.TIENDA['whatsapp']}."}


def consultar_pedido(e, codigo, documento):
    with db.agente() as c:
        r = c.execute("SELECT fn_estado_pedido(%s, %s) AS r", (codigo, documento)).fetchone()["r"]
        cambio = c.execute("SELECT fn_consultar_cambio(%s, %s) AS r", (codigo, documento)).fetchone()["r"]
    if not r:
        return {"error": "No encontré un pedido con ese código y ese documento.", "tipo": "no_encontrado"}
    r["total_texto"] = pesos(r["total"])
    r["saldo_texto"] = pesos(r["saldo"])
    return {"pedido": r, "cambio": cambio}


def cancelar_pedido(e, motivo="El cliente desistió"):
    """Solo cancela el pedido de ESTA conversación (los de otros días los cancela un asesor)."""
    with db.agente() as c:
        if not e.pedido_id:
            return {"error": "No hay un pedido en esta conversación."}
        r = c.execute("SELECT fn_cancelar_pedido(%s, %s) AS r", (e.pedido_id, motivo)).fetchone()["r"]
        e.version_pedido += 1
        return {"ok": True, "pedido": r}


def derivar_a_asesor(e, motivo):
    e.derivado = True
    return {"ok": True, "whatsapp": config.TIENDA["whatsapp"], "horario": config.TIENDA["horario"],
            "mensaje": f"Caso para asesor: {motivo}"}


# ── Catálogo de herramientas (formato de llamadas a funciones de OpenAI/Groq/Ollama) ──
def _f(nombre, descripcion, props, requeridos=()):
    return {"type": "function", "function": {"name": nombre, "description": descripcion, "parameters": {
        "type": "object", "properties": props, "required": list(requeridos)}}}


CATEGORIAS = ["Salas", "Comedores", "Sillas", "Camas y colchones", "Alcobas", "Armarios y muebles", "Oficina",
              "Lencería", "Decoración", "Electrodomésticos", "Cocina y pequeños electrodomésticos", "Tecnología"]

ESQUEMAS = [
    _f("buscar_productos", "Productos del inventario con producto_id, precio y existencias. Úsala antes de dar precios.",
       {"texto": {"type": "string", "description": "ej. 'colchón 1.40', 'sofacama'"},
        "categoria": {"type": "string", "enum": CATEGORIAS},
        "precio_max": {"type": "integer"}, "solo_disponibles": {"type": "boolean"}}),
    _f("ver_fotos", "Muestra al cliente fotos del catálogo de Decorer (ej. 'sala roma', 'sofacama', 'comedor flor morado', 'armario'). "
       "Úsala cuando quiera ver cómo es un mueble.", {"texto": {"type": "string"}}, ["texto"]),
    _f("buscar_informacion", "Políticas y preguntas frecuentes: cambios, garantía, domicilios, pagos, crédito, separado, "
       "horario, WhatsApp, modelos y colores.", {"pregunta": {"type": "string"}}, ["pregunta"]),
    _f("registrar_cliente", "Registra al cliente (necesario para confirmar, separar o pedir crédito).",
       {"documento": {"type": "string"}, "nombre": {"type": "string"}, "telefono": {"type": "string"},
        "direccion": {"type": "string"}, "barrio": {"type": "string"}, "municipio": {"type": "string"},
        "zona": {"type": "string", "enum": ["urbana", "rural"]}}, ["documento", "nombre"]),
    _f("agregar_al_pedido", "Agrega un producto o cambia su cantidad (0 lo quita). Devuelve el resumen con el total.",
       {"producto_id": {"type": "integer"}, "cantidad": {"type": "integer", "minimum": 0},
        "con_domicilio": {"type": "boolean"}}, ["producto_id", "cantidad"]),
    _f("confirmar_compra", "Cierra la compra de contado. Solo si el cliente vio el resumen y dijo que sí.",
       {"metodo_pago": {"type": "string", "enum": ["efectivo", "transferencia"]},
        "cliente_confirmo": {"type": "boolean"}}, ["metodo_pago", "cliente_confirmo"]),
    _f("separar_producto", "Separa el pedido con un abono. Solo con el sí del cliente.",
       {"abono": {"type": "integer"}, "metodo_pago": {"type": "string", "enum": ["efectivo", "transferencia"]},
        "cliente_confirmo": {"type": "boolean"}}, ["abono", "metodo_pago", "cliente_confirmo"]),
    _f("solicitar_credito", "Deja la solicitud de crédito para un asesor.",
       {"entidad": {"type": "string", "enum": ["sistecredito", "addi", "credito_personal"]}}, ["entidad"]),
    _f("consultar_pedido", "Estado de un pedido anterior y si aplica cambio. Pide código DEC-... y cédula.",
       {"codigo": {"type": "string"}, "documento": {"type": "string"}}, ["codigo", "documento"]),
    _f("cancelar_pedido", "Cancela el pedido de esta conversación.", {"motivo": {"type": "string"}}),
    _f("derivar_a_asesor", "Pasa el caso a una persona: reclamos, garantías, encargos, domicilios por cotizar, o si lo pide.",
       {"motivo": {"type": "string"}}, ["motivo"]),
]

FUNCIONES = {f["function"]["name"]: globals()[f["function"]["name"]] for f in ESQUEMAS}


def ejecutar(e: Estado, nombre: str, argumentos: str | dict) -> dict:
    """Ejecuta una herramienta y nunca lanza excepción: los errores vuelven al LLM para que los explique."""
    t0 = time.perf_counter()
    try:
        args = json.loads(argumentos or "{}") if isinstance(argumentos, str) else (argumentos or {})
    except json.JSONDecodeError:
        args, resultado = {}, {"error": "Argumentos inválidos (no es JSON)."}
    else:
        fn = FUNCIONES.get(nombre)
        if not fn:
            resultado = {"error": f"La herramienta {nombre} no existe."}
        else:
            try:
                resultado = fn(e, **args)
            except psycopg.Error as ex:
                resultado = db.error_legible(ex)
            except TypeError as ex:
                resultado = {"error": f"Argumentos incorrectos para {nombre}: {ex}"}
    ms = int((time.perf_counter() - t0) * 1000)
    e.herramientas_usadas.append({"nombre": nombre, "argumentos": args, "ok": "error" not in resultado,
                                  "ms": ms, "resultado": resultado})
    return resultado
