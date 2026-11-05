"""
agente.py - El ciclo del agente en cada turno de la conversación.

  mensaje del cliente
      -> prompt del sistema (rol, tarea, contexto con la hora y el pedido actual, formato)
      -> LLM decide: responder o usar herramientas
      -> se ejecutan las herramientas (PostgreSQL / pgvector) y el resultado vuelve al LLM
      -> (hasta AGENTE_MAX_PASOS rondas)
      -> respuesta final + traza con tiempos en agente_trazas
"""
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import db
import herramientas as H
import llm

PROMPT_BASE = (Path(__file__).resolve().parent / "prompts" / "sistema.md").read_text(encoding="utf-8")
ZONA = ZoneInfo("America/Bogota")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

FORMATO = {
    "texto": "- Responde en 1 a 4 oraciones claras. Si das varias opciones, usa una lista corta con guiones. Sin tablas.",
    "voz": "- Tu respuesta también se lee en voz alta: máximo 3 oraciones cortas, sin listas, sin emojis ni asteriscos. "
           "Escribe precios, medidas y códigos normal, en números (ej. $1.150.700, colchón 1.40, DEC-2611-0009) y "
           "los nombres de producto como salen en el sistema: el sistema los convierte a palabras al hablar.",
}


def tienda_abierta(ahora: datetime) -> str:
    if ahora.weekday() == 6:
        return "cerrada (es domingo; un asesor confirma si se atiende)"
    m = ahora.hour * 60 + ahora.minute
    if 9 * 60 + 15 <= m < 12 * 60 + 15 or 14 * 60 <= m < 18 * 60 + 15:
        return "abierta"
    if 12 * 60 + 15 <= m < 14 * 60:
        return "cerrada al mediodía (abre otra vez a las 2:00 p. m.)"
    return "cerrada en este momento"


def _pedido_actual(e: H.Estado) -> str:
    if not e.pedido_id:
        return "todavía no hay productos en el pedido."
    with db.agente() as c:
        r = H._resumen(c, e.pedido_id)
    if not r:
        return "todavía no hay productos en el pedido."
    items = "; ".join(f"{i['cantidad']} x {i['producto']} (producto_id {i['producto_id']}) {i['subtotal_texto']}"
                      for i in r["items"]) or "sin productos"
    extra = ""
    if r["estado"] == "borrador":
        extra = (" El cliente YA VIO este resumen; si en su último mensaje dijo que sí, puedes confirmar."
                 if e.version_vista == e.version_pedido else
                 " El cliente AÚN NO ha visto el resumen final: muéstraselo antes de confirmar.")
    return (f"{r['codigo']} ({r['estado']}) · {items} · domicilio: {r['domicilio_texto'] if r['con_domicilio'] else 'recoge en tienda'}"
            f" · total {r['total_texto']}" + (" · cliente registrado" if e.cliente_id else " · cliente sin registrar") + extra)


def prompt_sistema(e: H.Estado) -> str:
    ahora = datetime.now(ZONA)
    reemplazos = {
        "{direccion}": config.TIENDA["direccion"], "{whatsapp}": config.TIENDA["whatsapp"],
        "{horario}": config.TIENDA["horario"], "{redes}": config.TIENDA["redes"],
        "{fecha_hora}": f"{DIAS[ahora.weekday()]} {ahora:%d/%m/%Y %I:%M %p}",
        "{abierta}": tienda_abierta(ahora), "{canal}": e.canal,
        "{pedido_actual}": _pedido_actual(e), "{formato_canal}": FORMATO.get(e.canal, FORMATO["texto"]),
    }
    texto = PROMPT_BASE
    for k, v in reemplazos.items():
        texto = texto.replace(k, v)
    return texto


# Frases con las que el agente afirma que la venta quedó hecha
AFIRMA_VENTA = re.compile(r"(queda|qued[oó]|est[aá]|fue|ha sido)\s+(registrad|confirmad|apartad|separad)|"
                          r"pedido\s+(registrad|confirmad)|ya\s+(lo|le|se)\s+confirm|compra\s+(qued|est[aá])\s+lista", re.I)


def revisar_respuesta(texto: str, e: H.Estado) -> str | None:
    """Verificador: compara lo que dice el agente con lo que de verdad hicieron las herramientas.
    Devuelve una corrección para el LLM, o None si la respuesta es coherente."""
    hechas = {u["nombre"] for u in e.herramientas_usadas if u["ok"]}
    if "consultar_pedido" in hechas:       # está informando el estado de un pedido anterior: puede decir "confirmado"
        return None
    with db.agente() as c:
        abierto = H._pedido_abierto(e, c)
    if abierto and abierto["items"] and AFIRMA_VENTA.search(texto or "") \
            and not hechas & {"confirmar_compra", "separar_producto"}:
        fallo = next((u["resultado"].get("error") for u in reversed(e.herramientas_usadas)
                      if u["nombre"] in ("confirmar_compra", "separar_producto") and not u["ok"]), None)
        return ("REVISIÓN INTERNA: tu respuesta dice que el pedido quedó registrado o confirmado, pero NO se ejecutó "
                "confirmar_compra ni separar_producto con éxito, así que el pedido sigue en borrador. "
                + (f"El sistema respondió: {fallo}. " if fallo else "")
                + "Si el cliente ya dijo que sí y sabes la forma de pago (efectivo o transferencia), llama ahora a "
                  "confirmar_compra. Si falta la forma de pago, pregúntala. No digas que está confirmado hasta que la "
                  "herramienta responda ok. Responde de nuevo al cliente.")
    return None


def _asegurar_conversacion(conversacion_id: str | None, canal: str) -> str:
    with db.agente() as c:
        if conversacion_id:
            if c.execute("SELECT 1 FROM conversaciones WHERE id = %s", (conversacion_id,)).fetchone():
                return conversacion_id
        nuevo = conversacion_id or str(uuid.uuid4())
        c.execute("INSERT INTO conversaciones(id, canal) VALUES (%s, %s)", (nuevo, canal))
        return nuevo


def _historial(conversacion_id: str) -> list:
    with db.agente() as c:
        filas = c.execute("SELECT rol, contenido FROM mensajes WHERE conversacion_id = %s AND rol IN ('usuario','agente') "
                          "ORDER BY id DESC LIMIT %s", (conversacion_id, config.HISTORIAL)).fetchall()
    return [{"role": "user" if f["rol"] == "usuario" else "assistant", "content": f["contenido"]} for f in reversed(filas)]


def _guardar_mensaje(conversacion_id, rol, contenido, audio_path=None):
    with db.agente() as c:
        c.execute("INSERT INTO mensajes(conversacion_id, rol, contenido, audio_path) VALUES (%s,%s,%s,%s)",
                  (conversacion_id, rol, contenido, audio_path))


def _intencion(usadas: list) -> str:
    nombres = [u["nombre"] for u in usadas]
    for clave in ("confirmar_compra", "separar_producto", "solicitar_credito", "agregar_al_pedido", "registrar_cliente",
                  "consultar_pedido", "cancelar_pedido", "derivar_a_asesor", "buscar_informacion", "buscar_productos"):
        if clave in nombres:
            return clave
    return "conversacion"


def responder(mensaje: str, conversacion_id: str | None = None, canal: str = "texto",
              ms_stt: int | None = None, audio_path: str | None = None) -> dict:
    canal = canal if canal in ("texto", "voz") else "texto"
    conversacion_id = _asegurar_conversacion(conversacion_id, canal)
    e = H.estado(conversacion_id, canal)
    e.canal = canal
    e.herramientas_usadas, e.resumen_en_este_turno, e.derivado, e.fotos = [], False, False, []

    _guardar_mensaje(conversacion_id, "usuario", mensaje, audio_path)
    mensajes = [{"role": "system", "content": prompt_sistema(e)}] + _historial(conversacion_id)

    ms_llm, llamadas, revisiones = 0, [], 0
    modelo, error, texto = None, None, None
    try:
        for _ in range(config.MAX_PASOS + 1):
            t0 = time.perf_counter()
            r, modelo = llm.chat(mensajes, H.ESQUEMAS, preferido=modelo)
            ms = int((time.perf_counter() - t0) * 1000)
            ms_llm += ms
            llamadas.append({"modelo": modelo, "ms": ms, "herramientas": [tc["name"] for tc in r["tool_calls"]]})
            if not r["tool_calls"]:
                texto = (r["content"] or "").strip()
                correccion = revisar_respuesta(texto, e) if revisiones == 0 else None
                if correccion:
                    revisiones += 1
                    e.herramientas_usadas.append({"nombre": "verificador", "argumentos": {}, "ok": False, "ms": 0,
                                                  "resultado": {"error": "respuesta corregida: afirmaba una venta no hecha"}})
                    mensajes.append({"role": "assistant", "content": texto})
                    mensajes.append({"role": "system", "content": correccion})
                    texto = None
                    continue
                break
            mensajes.append({"role": "assistant", "content": r["content"] or "",
                             "tool_calls": [{"id": tc["id"], "type": "function",
                                             "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                            for tc in r["tool_calls"]]})
            for tc in r["tool_calls"]:
                resultado = H.ejecutar(e, tc["name"], tc["arguments"])
                mensajes.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(resultado, ensure_ascii=False, default=str)})
        else:
            error = "Se alcanzó el máximo de pasos sin respuesta final"
    except llm.LLMNoDisponible as ex:
        error = str(ex)

    if not texto:
        texto = (f"Disculpe, en este momento no puedo responder bien. Escríbanos al WhatsApp "
                 f"{config.TIENDA['whatsapp']} y un asesor le ayuda.")
        e.derivado = True
    if e.resumen_en_este_turno:
        e.version_vista = e.version_pedido      # el cliente ve el resumen en esta respuesta

    _guardar_mensaje(conversacion_id, "agente", texto)
    ms_herr = sum(u["ms"] for u in e.herramientas_usadas)
    with db.agente() as c:
        c.execute("""INSERT INTO agente_trazas(conversacion_id, intencion, herramientas, ok, derivado_asesor, error,
                                               modelo_llm, ms_stt, ms_llm, ms_herramientas)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (conversacion_id, _intencion(e.herramientas_usadas),
                   json.dumps({"herramientas": [{k: v for k, v in u.items() if k != "resultado"} for u in e.herramientas_usadas],
                               "llamadas_llm": llamadas}, ensure_ascii=False, default=str),
                   error is None, e.derivado, error, modelo, ms_stt, ms_llm, ms_herr))
        traza_id = c.execute("SELECT currval('agente_trazas_id_seq') AS id").fetchone()["id"]
        pedido = H._resumen(c, e.pedido_id) if e.pedido_id else None

    vistas, fotos = set(), []
    for f in e.fotos:                       # máximo 4 fotos por respuesta, sin repetir
        if f["drive_id"] not in vistas and len(fotos) < 4:
            vistas.add(f["drive_id"]); fotos.append(f)
    return {"conversacion_id": conversacion_id, "traza_id": traza_id, "respuesta": texto, "pedido": pedido, "fotos": fotos,
            "herramientas": [{"nombre": u["nombre"], "argumentos": u["argumentos"], "ok": u["ok"], "ms": u["ms"],
                              "error": None if u["ok"] else str(u["resultado"].get("error", ""))[:200]}
                             for u in e.herramientas_usadas],
            "derivado_asesor": e.derivado, "modelo": modelo, "error": error,
            "tiempos": {"ms_stt": ms_stt, "ms_llm": ms_llm, "ms_herramientas": ms_herr, "llamadas_llm": llamadas}}
