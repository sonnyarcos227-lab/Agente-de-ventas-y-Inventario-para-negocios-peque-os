"""
chat_consola.py - Habla con Deco desde la terminal (sin interfaz web todavía).

    py chat_consola.py            (desde la carpeta backend)
    py chat_consola.py --voz      (simula el canal de voz: respuestas cortas)

Escribe "salir" para terminar. Muestra qué herramientas usó el agente y cuánto tardó.
"""
import sys

if sys.platform == "win32":
    import os
    os.system("")

import agente
import db
import llm

canal = "voz" if "--voz" in sys.argv else "texto"
print(f"Deco · Decorer  (canal: {canal}, LLM: {llm.estado()['proveedor']})  -  escribe 'salir' para terminar\n")
conv = None
try:
    while True:
        try:
            msg = input("\033[96mUsted:\033[0m ").strip()
        except EOFError:
            break
        if not msg:
            continue
        if msg.lower() in ("salir", "exit", "chao"):
            break
        r = agente.responder(msg, conv, canal)
        conv = r["conversacion_id"]
        herr = ", ".join(f"{h['nombre']}{'' if h['ok'] else ' (error)'}" for h in r["herramientas"]) or "ninguna"
        print(f"\033[93mDeco:\033[0m {r['respuesta']}")
        print(f"\033[90m      [{r['modelo']} · herramientas: {herr} · LLM {r['tiempos']['ms_llm']} ms"
              f" · base {r['tiempos']['ms_herramientas']} ms]\033[0m")
        if r["error"]:
            print(f"\033[91m      error: {r['error'][:200]}\033[0m")
        if r["pedido"] and r["pedido"]["items"]:
            p = r["pedido"]
            print(f"\033[90m      pedido {p['codigo']} ({p['estado']}): total {p['total_texto']}\033[0m")
        print()
finally:
    db.cerrar()
