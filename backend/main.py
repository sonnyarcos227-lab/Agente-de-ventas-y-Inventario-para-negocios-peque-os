"""
main.py - API de Decorer (FastAPI).

  py -m uvicorn main:app --reload --port 8010        (desde la carpeta backend)
  Documentación interactiva: http://localhost:8010/docs

Cliente / agente:
  POST /api/chat                       {mensaje, conversacion_id?, canal: texto|voz}
  GET  /api/conversaciones/{id}        historial y pedido de la conversación
  GET  /api/productos?texto=&categoria=&solo_disponibles=
  GET  /api/salud                      estado de PostgreSQL, pgvector, embeddings y LLM

Dueño (cabecera X-Clave-Dueno):
  GET  /api/dueno/resumen              ventas de la semana, reabastecer, pendientes, separados, desempeño del agente
  GET  /api/dueno/alertas              alertas de stock en vivo (Server-Sent Events, LISTEN stock_bajo)
  POST /api/dueno/abono                {codigo, valor, metodo_pago}
  POST /api/dueno/entregado            {codigo}
  POST /api/dueno/entrada              {producto_id, cantidad, referencia}
"""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Literal, Optional

import psycopg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import agente
import config
import db
import embeddings
import herramientas as H
import llm
import vision
import voz


@asynccontextmanager
async def ciclo(app):
    # Carga la voz (Piper) y el oído (faster-whisper) en segundo plano para que la primera respuesta no tarde
    import threading
    threading.Thread(target=voz.precargar, daemon=True).start()
    yield
    db.cerrar()


app = FastAPI(title="Decorer · Agente de ventas e inventario", version="0.7", lifespan=ciclo)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/", include_in_schema=False)
def pagina_inicio():
    return FileResponse(FRONTEND / "landing.html")


@app.get("/chat", include_in_schema=False)
def pagina_chat():
    return FileResponse(FRONTEND / "chat.html")


# ── Cliente ───────────────────────────────────────────────────────────────────
class Chat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    conversacion_id: Optional[str] = None
    canal: Literal["texto", "voz"] = "texto"


@app.post("/api/chat")
def chat(c: Chat):
    return agente.responder(c.mensaje.strip(), c.conversacion_id, c.canal)


def _hablar(respuesta: dict) -> dict:
    """Convierte la respuesta en audio con Piper y anota el tiempo en la traza."""
    try:
        a = voz.sintetizar(respuesta["respuesta"])
        respuesta["audio_url"] = f"/api/audio/{a['archivo']}"
        respuesta["texto_hablado"] = a["texto_hablado"]
        respuesta["tiempos"]["ms_tts"] = a["ms"]
        if respuesta.get("traza_id"):
            with db.agente() as cn:
                cn.execute("UPDATE agente_trazas SET ms_tts = %s WHERE id = %s", (a["ms"], respuesta["traza_id"]))
    except Exception as e:      # sin Piper: el navegador lee el texto con su propia voz
        respuesta["audio_url"] = None
        respuesta["texto_hablado"] = voz.texto_para_hablar(respuesta["respuesta"])
        respuesta["aviso_voz"] = str(e)[:200]
    return respuesta


@app.post("/api/voz")
async def chat_por_voz(audio: UploadFile = File(...), conversacion_id: Optional[str] = Form(None)):
    """El cliente habla: audio -> faster-whisper -> agente (canal voz) -> Piper -> audio."""
    datos = await audio.read()
    if len(datos) < 1000:
        raise HTTPException(400, "El audio está vacío. Mantenga el micrófono un poco más.")
    sufijo = Path(audio.filename or "audio.webm").suffix or ".webm"
    try:
        wav = voz.a_wav16k(datos, sufijo)
        if voz.duracion(wav) > 60:
            raise HTTPException(400, "El audio es muy largo; máximo 1 minuto por mensaje.")
        stt = voz.transcribir(wav)
    except voz.VozError as e:
        raise HTTPException(422, str(e))
    if not stt["texto"]:
        raise HTTPException(422, "No le entendí. ¿Puede repetirlo un poco más cerca del micrófono?")
    r = agente.responder(stt["texto"], conversacion_id, "voz", ms_stt=stt["ms"], audio_path=wav.name)
    r["transcripcion"], r["motor_stt"] = stt["texto"], stt["motor"]
    return _hablar(r)


class Tts(BaseModel):
    texto: str = Field(min_length=1, max_length=1500)


@app.post("/api/tts")
def leer_en_voz(t: Tts):
    """Lee en voz alta un texto (cuando el cliente escribe pero tiene activado el modo voz)."""
    return _hablar({"respuesta": t.texto, "tiempos": {}})


@app.get("/api/audio/{nombre}")
def audio(nombre: str):
    archivo = voz.CARPETA_AUDIOS / Path(nombre).name        # .name evita rutas tipo ../../
    if not archivo.exists() or archivo.suffix != ".wav":
        raise HTTPException(404, "Audio no encontrado")
    return FileResponse(archivo, media_type="audio/wav")


@app.get("/dueno", include_in_schema=False)
def pagina_dueno():
    return FileResponse(FRONTEND / "panel.html")


@app.get("/api/conversaciones/{conversacion_id}")
def conversacion(conversacion_id: str):
    with db.agente() as cn:
        conv = cn.execute("SELECT id, canal, pedido_id, iniciada_en FROM conversaciones WHERE id = %s",
                          (conversacion_id,)).fetchone()
        if not conv:
            raise HTTPException(404, "Conversación no encontrada")
        mensajes = cn.execute("SELECT rol, contenido, creado_en FROM mensajes WHERE conversacion_id = %s ORDER BY id",
                              (conversacion_id,)).fetchall()
        pedido = H._resumen(cn, conv["pedido_id"]) if conv["pedido_id"] else None
    return {"conversacion": conv, "mensajes": mensajes, "pedido": pedido}


@app.get("/api/productos")
def productos(texto: Optional[str] = None, categoria: Optional[str] = None, solo_disponibles: bool = False):
    return H.buscar_productos(None, texto, categoria, None, solo_disponibles)


@app.get("/api/salud")
def salud():
    estado = {"llm": llm.estado(), "embeddings": {"url": config.LLAMACPP_EMBED_URL, "online": embeddings.disponible()},
              "voz": voz.estado()}
    try:
        with db.agente() as cn:
            estado["base"] = cn.execute("""SELECT (SELECT count(*) FROM productos WHERE activo) AS productos,
                                                  (SELECT count(*) FROM productos WHERE activo AND precio IS NOT NULL) AS con_precio,
                                                  (SELECT count(*) FROM inventario i JOIN productos p ON p.id = i.producto_id
                                                   WHERE p.activo AND i.existencias > 0) AS con_stock,
                                                  (SELECT count(*) FROM conocimiento) AS fragmentos_conocimiento""").fetchone()
        estado["status"] = "ok"
    except psycopg.Error as e:
        estado["status"], estado["base"] = "sin base de datos", str(e)[:200]
    return estado


# ── Dueño ─────────────────────────────────────────────────────────────────────
def clave_dueno(x_clave_dueno: str = Header(default="")):
    if x_clave_dueno != config.CLAVE_DUENO:
        raise HTTPException(401, "Clave del dueño incorrecta")


@app.get("/api/dueno/resumen", dependencies=[Depends(clave_dueno)])
def resumen_dueno(dias: int = 7):
    dias = max(1, min(dias, 90))
    desde = date.today() - timedelta(days=dias - 1)
    with db.dueno() as cn:
        return {
            "periodo": {"desde": desde, "hasta": date.today(), "dias": dias},
            "ventas": cn.execute("SELECT fn_reporte_ventas(%s, current_date) AS r", (desde,)).fetchone()["r"],
            # un punto por día, también los días sin ventas (para que la gráfica no salte días)
            "por_dia": cn.execute("""
                SELECT d::date AS dia, coalesce(v.pedidos, 0) AS pedidos, coalesce(v.total_vendido, 0) AS total
                FROM generate_series(%s::date, current_date, interval '1 day') d
                LEFT JOIN v_ventas_por_dia v ON v.dia = d::date ORDER BY 1""", (desde,)).fetchall(),
            "ultimas_ventas": cn.execute("""
                SELECT pe.codigo, v.vendida_en, v.metodo_pago, pe.canal, v.total, v.registrada_por,
                       (SELECT string_agg(i.cantidad || ' x ' || p.nombre, ', ') FROM pedido_items i
                        JOIN productos p ON p.id = i.producto_id WHERE i.pedido_id = pe.id) AS productos
                FROM ventas v JOIN pedidos pe ON pe.id = v.pedido_id
                WHERE NOT v.anulada ORDER BY v.vendida_en DESC LIMIT 10""").fetchall(),
            "reabastecer": cn.execute("SELECT * FROM v_reabastecer LIMIT 30").fetchall(),
            "pendientes_asesor": cn.execute("SELECT * FROM v_pendientes_asesor").fetchall(),
            "separados": cn.execute("SELECT * FROM v_separados").fetchall(),
            "alertas": cn.execute("""SELECT a.creada_en, p.nombre, a.existencias, a.stock_minimo FROM alertas_stock a
                                     JOIN productos p ON p.id = a.producto_id WHERE NOT a.atendida
                                     ORDER BY a.creada_en DESC LIMIT 20""").fetchall(),
            "agente": cn.execute("""
                SELECT count(*) AS turnos,
                       round(100.0 * avg(ok::int), 1) AS pct_exito,
                       round(100.0 * avg(derivado_asesor::int), 1) AS pct_derivado,
                       count(DISTINCT conversacion_id) AS conversaciones,
                       round(avg(ms_stt)) AS ms_stt, round(avg(ms_llm)) AS ms_llm,
                       round(avg(ms_herramientas)) AS ms_herramientas, round(avg(ms_tts)) AS ms_tts,
                       count(*) FILTER (WHERE ms_stt IS NOT NULL) AS turnos_voz
                FROM agente_trazas WHERE creado_en >= %s""", (desde,)).fetchone(),
            "intenciones": cn.execute("""SELECT intencion, count(*) AS n FROM agente_trazas WHERE creado_en >= %s
                                         GROUP BY 1 ORDER BY 2 DESC""", (desde,)).fetchall(),
            "inventario": cn.execute("""SELECT count(*) FILTER (WHERE existencias > 0) AS con_stock,
                                               coalesce(sum(existencias * precio) FILTER (WHERE existencias > 0), 0) AS valor_venta,
                                               count(*) FILTER (WHERE estado = 'agotado') AS agotados
                                        FROM v_inventario""").fetchone(),
            "descuadre_syscafe": cn.execute("SELECT count(*) AS articulos FROM v_descuadre_syscafe").fetchone(),
        }


@app.post("/api/dueno/factura", dependencies=[Depends(clave_dueno)])
async def leer_factura(imagen: UploadFile = File(...)):
    """Paso 1: la foto de la factura -> propuesta de entrada (no toca el inventario)."""
    datos = await imagen.read()
    if len(datos) > 15 * 1024 * 1024:
        raise HTTPException(400, "La imagen pesa más de 15 MB.")
    if not (imagen.content_type or "").startswith("image/"):
        raise HTTPException(400, "Suba una foto (jpg, png o webp) de la factura.")
    import time
    t0 = time.perf_counter()
    try:
        p = vision.proponer_entrada(datos)
    except vision.VisionError as e:
        raise HTTPException(503, str(e))
    p["ms"] = int((time.perf_counter() - t0) * 1000)
    return p


class LineaFactura(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0, le=500)


class ConfirmarFactura(BaseModel):
    referencia: Optional[str] = Field(default=None, max_length=80)
    lineas: list[LineaFactura] = Field(min_length=1, max_length=40)


@app.post("/api/dueno/factura/confirmar", dependencies=[Depends(clave_dueno)])
def confirmar_factura(f: ConfirmarFactura):
    """Paso 2: el dueño revisó y confirma. Todas las líneas entran en UNA transacción: o entran todas o ninguna."""
    ref = f"Factura {f.referencia}" if f.referencia else "Factura proveedor (foto)"
    try:
        with db.dueno() as cn:
            with cn.transaction():
                hechas = [cn.execute("SELECT fn_entrada_inventario(%s, %s, %s, 'dueño (factura)') AS r",
                                     (l.producto_id, l.cantidad, ref)).fetchone()["r"] for l in f.lineas]
    except psycopg.Error as e:
        raise HTTPException(400, "No entró nada al inventario: " + db.error_legible(e)["error"])
    return {"ok": True, "referencia": ref, "lineas": hechas}


@app.get("/api/dueno/buscar_producto", dependencies=[Depends(clave_dueno)])
def buscar_producto_dueno(texto: str):
    """Para registrar la entrada de mercancía: busca en todo el catálogo (con y sin stock)."""
    return H.buscar_productos(None, texto, None, None, False)


@app.get("/api/dueno/alertas")
async def alertas(clave: str = ""):
    """Server-Sent Events: el navegador se queda escuchando (EventSource no manda cabeceras, por eso va la clave en la URL)."""
    if clave != config.CLAVE_DUENO:
        raise HTTPException(401, "Clave del dueño incorrecta")

    async def eventos():
        async with await psycopg.AsyncConnection.connect(config.URL_DUENO, autocommit=True) as cn:
            await cn.execute("LISTEN stock_bajo")
            yield "event: listo\ndata: {}\n\n"
            async for n in cn.notifies():
                yield f"event: stock_bajo\ndata: {n.payload}\n\n"
    return StreamingResponse(eventos(), media_type="text/event-stream")


class Abono(BaseModel):
    codigo: str
    valor: int = Field(gt=0)
    metodo_pago: Literal["efectivo", "transferencia"]


class Codigo(BaseModel):
    codigo: str


class Entrada(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0)
    referencia: Optional[str] = None


def _dueno_fn(sql, params):
    try:
        with db.dueno() as cn:
            return cn.execute(sql, params).fetchone()["r"]
    except psycopg.Error as e:
        raise HTTPException(400, db.error_legible(e)["error"])


@app.post("/api/dueno/abono", dependencies=[Depends(clave_dueno)])
def abono(a: Abono):
    return _dueno_fn("SELECT fn_registrar_abono(%s, %s, %s, 'asesor') AS r", (a.codigo, a.valor, a.metodo_pago))


@app.post("/api/dueno/entregado", dependencies=[Depends(clave_dueno)])
def entregado(c: Codigo):
    return _dueno_fn("SELECT fn_marcar_entregado(%s) AS r", (c.codigo,))


@app.post("/api/dueno/entrada", dependencies=[Depends(clave_dueno)])
def entrada(en: Entrada):
    return _dueno_fn("SELECT fn_entrada_inventario(%s, %s, %s, 'dueño') AS r", (en.producto_id, en.cantidad, en.referencia))
