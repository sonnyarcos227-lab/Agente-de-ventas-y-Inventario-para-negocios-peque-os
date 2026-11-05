"""
prueba_agente.py - Prueba el backend completo (API + agente + herramientas + base de datos)
con un LLM SIMULADO: un guion decide qué herramientas llamar, igual que haría Groq.
Así se prueba todo el circuito sin gastar la API ni depender de internet.

    py pruebas\\prueba_agente.py

Usa productos reales del inventario de Decorer y al final cancela lo que vendió.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "simulado")
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

if os.name == "nt":
    os.system("")

from fastapi.testclient import TestClient   # noqa: E402

import config   # noqa: E402
import db       # noqa: E402
import llm      # noqa: E402
from main import app   # noqa: E402

OK, FALLA = "\033[92mOK\033[0m", "\033[91mFALLA\033[0m"
resultados = []
cliente_api = TestClient(app)


def check(nombre, condicion, detalle=""):
    resultados.append(bool(condicion))
    print(f"  [{OK if condicion else FALLA}] {nombre}" + (f"  ->  {detalle}" if detalle else ""))


# ── LLM simulado ──────────────────────────────────────────────────────────────
class Guion:
    """Cada turno es una lista de pasos. Un paso es una llamada a herramienta (nombre, args o función que
    arma los args con lo que devolvieron las herramientas anteriores) o el texto final (str o función)."""

    def __init__(self):
        self.pasos, self.prompts = [], []

    def turno(self, *pasos):
        self.pasos = list(pasos)

    def __call__(self, messages, tools):
        self.prompts.append(messages[0]["content"])
        resultados_previos = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        paso = self.pasos.pop(0)
        if isinstance(paso, tuple):
            nombre, args = paso
            args = args(resultados_previos) if callable(args) else args
            return {"content": None, "tool_calls": [{"id": f"call_{len(self.prompts)}", "name": nombre,
                                                     "arguments": json.dumps(args)}]}
        texto = paso(resultados_previos) if callable(paso) else paso
        return {"content": texto, "tool_calls": []}


guion = Guion()
llm.usar_simulado(guion)


def hablar(mensaje, conv=None, canal="texto"):
    r = cliente_api.post("/api/chat", json={"mensaje": mensaje, "conversacion_id": conv, "canal": canal})
    assert r.status_code == 200, r.text
    return r.json()


def stock(producto_id):
    with db.dueno() as c:
        return c.execute("SELECT existencias FROM inventario WHERE producto_id = %s", (producto_id,)).fetchone()["existencias"]


def main():
    vendidos = []
    try:
        _pruebas(vendidos)
    finally:
        with db.agente() as c:   # anula las ventas de prueba y devuelve los productos, pase lo que pase
            for p in vendidos:
                try:
                    c.execute("SELECT fn_cancelar_pedido(%s, 'Prueba automática del agente')", (p,))
                except Exception:
                    pass
        db.cerrar()
    print(f"\nResultado: {sum(resultados)}/{len(resultados)} pruebas correctas")
    sys.exit(0 if all(resultados) else 1)


def _pruebas(vendidos):

    # 1 ─────────────────────────────────────────────────────────────────
    print("\n1. Salud de la API")
    s = cliente_api.get("/api/salud").json()
    check("La API responde y ve la base", s["status"] == "ok",
          f"{s['base']['productos']} productos, {s['base']['con_precio']} con precio, {s['base']['con_stock']} con stock")

    # 2 ─────────────────────────────────────────────────────────────────
    print("\n2. Compra completa por chat (colchón 1.40 a domicilio)")
    guion.turno(("buscar_productos", {"texto": "colchon 1.40", "solo_disponibles": True}),
                lambda r: "Tenemos: " + "; ".join(f"{x['nombre']} a {x['precio']}" for x in r[-1]["resultados"][:2]))
    t1 = hablar("Buenas, ¿tienen colchones de 1.40?")
    conv = t1["conversacion_id"]
    print(f"     Deco: {t1['respuesta']}")
    check("Busca en el inventario antes de responder", t1["herramientas"][0]["nombre"] == "buscar_productos")
    check("El prompt del sistema trae la hora y si la tienda está abierta", "la tienda está" in guion.prompts[-1])

    cassata = {}

    def elegir(r):
        res = next(x for x in r[-1]["resultados"] if "CASSATA" in x["nombre"]) if r else None
        cassata.update(res)
        return {"producto_id": res["producto_id"], "cantidad": 1, "con_domicilio": True}

    guion.turno(("buscar_productos", {"texto": "colchon cassata 1.40"}), ("agregar_al_pedido", elegir),
                lambda r: f"Listo: {r[-1]['pedido']['items'][0]['producto']}, total {r[-1]['pedido']['total_texto']}, "
                          f"domicilio {r[-1]['pedido']['domicilio_texto']}. ¿Me da su cédula y nombre?")
    t2 = hablar("Me llevo el Cassata, a domicilio por favor", conv)
    print(f"     Deco: {t2['respuesta']}")
    antes = stock(cassata["producto_id"])
    check("El total lo calcula la base, no el LLM", t2["pedido"]["total"] == t2["pedido"]["subtotal"] - t2["pedido"]["descuento"])
    check("Domicilio gratis (supera $500.000)", t2["pedido"]["domicilio"] == 0 and not t2["pedido"]["domicilio_por_confirmar"])

    # el LLM intenta confirmar sin que el cliente haya dado sus datos ni visto el resumen final
    guion.turno(("confirmar_compra", {"metodo_pago": "transferencia", "cliente_confirmo": True}),
                lambda r: "Primero necesito sus datos.")
    t3 = hablar("confírmelo ya", conv)
    with db.dueno() as c:
        hay_venta = c.execute("SELECT count(*) AS n FROM ventas WHERE pedido_id = %s", (t2["pedido"]["pedido_id"],)).fetchone()["n"]
    check("CANDADO: sin datos del cliente no se cierra la venta", hay_venta == 0 and not t3["herramientas"][0]["ok"])

    guion.turno(("registrar_cliente", {"documento": "9999000777", "nombre": "Cliente Prueba Agente",
                                       "telefono": "3000000777", "direccion": "Calle 5 # 3-20", "barrio": "Centro"}),
                lambda r: f"Gracias. Resumen: total {r[-1]['pedido']['total_texto']}, domicilio gratis. ¿Le confirmo?")
    t4 = hablar("Cédula 9999000777, Cliente Prueba Agente, calle 5 # 3-20 Centro", conv)
    print(f"     Deco: {t4['respuesta']}")

    guion.turno(("confirmar_compra", {"metodo_pago": "transferencia", "cliente_confirmo": True}),
                lambda r: f"¡Listo! Su pedido es el {r[-1]['pedido']['codigo']}. {r[-1]['siguiente_paso']}")
    t5 = hablar("sí, confirmo, pago por transferencia", conv)
    print(f"     Deco: {t5['respuesta']}")
    check("Con el resumen visto y el 'sí' del cliente, se confirma", t5["pedido"]["estado"] == "confirmado")
    check("Se descontó el inventario", stock(cassata["producto_id"]) == antes - 1, f"{antes} -> {stock(cassata['producto_id'])}")
    check("La respuesta trae el WhatsApp para el comprobante", config.TIENDA["whatsapp"] in t5["respuesta"])
    vendidos.append(t5["pedido"]["pedido_id"])

    # 3 ─────────────────────────────────────────────────────────────────
    print("\n3. Candado: el LLM intenta vender en el mismo turno en que arma el pedido")
    guion.turno(("buscar_productos", {"texto": "sala L venecia"}),
                ("agregar_al_pedido", lambda r: {"producto_id": r[-1]["resultados"][0]["producto_id"], "cantidad": 1}),
                ("confirmar_compra", {"metodo_pago": "efectivo", "cliente_confirmo": True}),
                lambda r: f"No pude confirmar: {r[-1].get('error')}")
    t = hablar("quiero la sala Venecia, véndamela de una")
    ultima = t["herramientas"][-1]
    check("Bloquea confirmar sin que el cliente vea el resumen", ultima["nombre"] == "confirmar_compra" and not ultima["ok"])
    check("El pedido sigue en borrador", t["pedido"]["estado"] == "borrador")

    # 4 ─────────────────────────────────────────────────────────────────
    print("\n4. Políticas (pgvector, o texto completo si llama.cpp está apagado)")
    guion.turno(("buscar_informacion", {"pregunta": "¿lo puedo pagar por cuotas?"}),
                lambda r: f"[{r[-1]['metodo']}] {r[-1]['fragmentos'][0]['titulo']}")
    t = hablar("¿lo puedo pagar por cuotas?")
    print(f"     Deco: {t['respuesta']}")
    check("Encuentra la política de crédito", "cuotas" in t["respuesta"].lower() or "crédito" in t["respuesta"].lower())

    # 5 ─────────────────────────────────────────────────────────────────
    print("\n5. Crédito con Addi")
    guion.turno(("buscar_productos", {"texto": "colchon", "solo_disponibles": True}),
                ("agregar_al_pedido", lambda r: {"producto_id": r[-1]["resultados"][0]["producto_id"], "cantidad": 1}),
                ("solicitar_credito", {"entidad": "addi"}),
                lambda r: f"{r[-1].get('error') or r[-1].get('siguiente_paso')}")
    t = hablar("quiero la sala chester a crédito con Addi")
    check("Sin datos del cliente no deja la solicitud", not t["herramientas"][-1]["ok"])
    conv_credito = t["conversacion_id"]
    guion.turno(("registrar_cliente", {"documento": "9999000888", "nombre": "Cliente Credito", "telefono": "3000000888"}),
                ("solicitar_credito", {"entidad": "addi"}), lambda r: r[-1]["siguiente_paso"])
    t = hablar("9999000888, Cliente Credito, 3000000888", conv_credito)
    check("Deja la solicitud para el asesor y deriva", t["derivado_asesor"] and t["pedido"]["solicita_credito"] == "addi")
    vendidos.append(t["pedido"]["pedido_id"])
    r = cliente_api.get("/api/dueno/resumen", headers={"X-Clave-Dueno": config.CLAVE_DUENO}).json()
    check("Aparece en los pendientes del panel del dueño",
          any(p["codigo"] == t["pedido"]["codigo"] for p in r["pendientes_asesor"]))

    # 6 ─────────────────────────────────────────────────────────────────
    print("\n6. Privacidad y seguridad")
    guion.turno(("consultar_pedido", {"codigo": t5["pedido"]["codigo"], "documento": "111"}),
                lambda r: r[-1].get("error", "?"))
    t = hablar(f"¿cómo va el pedido {t5['pedido']['codigo']}? mi cédula es 111")
    check("No muestra un pedido ajeno sin la cédula correcta", "No encontré" in t["respuesta"])
    guion.turno(("consultar_pedido", {"codigo": t5["pedido"]["codigo"], "documento": "9999000777"}),
                lambda r: f"Su pedido está {r[-1]['pedido']['estado']}; cambio inmediato: {r[-1]['cambio']['aplica_cambio_inmediato']}")
    t = hablar(f"¿cómo va el pedido {t5['pedido']['codigo']}? cédula 9999000777")
    check("Con la cédula correcta sí lo muestra, y dice si aplica cambio", "confirmado" in t["respuesta"])
    check("El panel del dueño pide clave", cliente_api.get("/api/dueno/resumen").status_code == 401)

    # 7 ─────────────────────────────────────────────────────────────────
    print("\n7. Canal de voz y LLM caído")
    guion.turno("Hola, soy Deco.")
    hablar("hola", canal="voz")
    check("En voz el prompt pide respuestas cortas sin listas", "se lee en voz alta" in guion.prompts[-1] and "en números" in guion.prompts[-1])
    llm.usar_simulado(None)
    config.LLM_PROVIDER, config.GROQ_API_KEY = "groq", ""
    t = hablar("hola")
    check("Si el LLM no responde, da el WhatsApp y lo registra como error", config.TIENDA["whatsapp"] in t["respuesta"] and t["error"])
    llm.usar_simulado(guion)
    config.LLM_PROVIDER = "simulado"

    # 8 ─────────────────────────────────────────────────────────────────
    print("\n8. Errores vistos en la prueba real con Groq (3 nov)")
    guion.turno(("buscar_productos", {"texto": "nevecones", "solo_disponibles": True}),
                lambda r: f"{r[-1]['nota']} | {r[-1]['resultados'][0]['nombre'] if r[-1]['resultados'] else '-'}")
    t = hablar("¿tienen nevecones?")
    check("Nevecones agotados: dice que existen y se piden por encargo (no 'no tenemos')",
          "encargo" in t["respuesta"] and "NEVECON" in t["respuesta"].upper(), t["respuesta"][:90] + "...")

    # reproducción: cliente dice "sí confirma" y el LLM responde "queda registrado" SIN llamar a confirmar_compra
    guion.turno(("buscar_productos", {"texto": "colchon cassata 1.40", "solo_disponibles": True}),
                ("agregar_al_pedido", lambda r: {"producto_id": r[-1]["resultados"][0]["producto_id"], "cantidad": 1}),
                lambda r: "¿Me da su cédula, nombre y forma de pago?")
    t = hablar("quiero el colchón Cassata 1.40, lo recojo en la tienda")
    pid8 = t["pedido"]["items"][0]["producto_id"]
    conv8 = t["conversacion_id"]
    guion.turno(("registrar_cliente", {"documento": "9999000999", "nombre": "Cliente Verificador"}),
                lambda r: f"Resumen: total {r[-1]['pedido']['total_texto']}, pago en efectivo. ¿Le confirmo?")
    hablar("9999000999, Cliente Verificador, pago en efectivo", conv8)
    guion.turno(("agregar_al_pedido", {"producto_id": pid8, "cantidad": 1}),
                "Su pedido queda registrado. ¿Algo más?",                     # <- la mentira
                ("confirmar_compra", {"metodo_pago": "efectivo", "cliente_confirmo": True}),   # tras la corrección
                lambda r: f"Ahora sí: pedido {r[-1]['pedido']['codigo']} confirmado.")
    t = hablar("sí, confirme el pedido", conv8)
    nombres = [h["nombre"] for h in t["herramientas"]]
    check("Volver a agregar lo mismo no reinicia la confirmación", "agregar_al_pedido" in nombres)
    check("El VERIFICADOR detecta 'queda registrado' sin venta y obliga a corregir", "verificador" in nombres)
    check("Después de la corrección la venta sí queda confirmada", t["pedido"]["estado"] == "confirmado", t["respuesta"])
    vendidos.append(t["pedido"]["pedido_id"])
    check("La traza guarda cada llamada al LLM con su tiempo", len(t["tiempos"]["llamadas_llm"]) == 4)

    print("\n9. Fotos del catálogo")
    guion.turno(("ver_fotos", {"texto": "sala roma"}), "Esta es la Sala Roma (foto de referencia).")
    t = hablar("¿me muestra la sala Roma?")
    check("ver_fotos devuelve la foto del Drive al chat", t["fotos"] and "drive.google.com/thumbnail" in t["fotos"][0]["url"],
          t["fotos"][0]["titulo"] if t["fotos"] else "")
    guion.turno(("buscar_productos", {"texto": "sala capri"}), "Tenemos varias Salas Capri.")
    t = hablar("¿tienen la sala capri?")
    check("Productos con foto la muestran sin repetirla", len(t["fotos"]) == len({f["drive_id"] for f in t["fotos"]}) >= 1,
          f"{len(t['fotos'])} foto(s)")
    guion.turno(("ver_fotos", {"texto": "nevera"}), "No tengo fotos de neveras; se las enviamos por WhatsApp.")
    t = hablar("muéstreme neveras")
    check("Sin foto en el catálogo no inventa ninguna", t["fotos"] == [])

    with db.dueno() as c:
        n = c.execute("SELECT count(*) AS n, count(*) FILTER (WHERE derivado_asesor) AS d FROM agente_trazas").fetchone()
    check("Cada turno quedó en agente_trazas (intención, herramientas, tiempos)", n["n"] >= 12, f"{n['n']} turnos, {n['d']} derivados")



if __name__ == "__main__":
    main()
