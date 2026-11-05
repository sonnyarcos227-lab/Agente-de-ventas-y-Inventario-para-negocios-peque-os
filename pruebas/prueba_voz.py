"""
prueba_voz.py - Prueba el circuito de voz completo:
  audio del navegador (webm) -> ffmpeg -> STT -> agente (canal voz) -> Piper -> audio wav

El oído y la voz se simulan (para no descargar modelos en la prueba); la conversión de audio,
los endpoints, la traza con ms_stt/ms_tts y el respaldo del navegador son los reales.

    py pruebas\\prueba_voz.py
"""
import os
import subprocess
import sys
import tempfile
import wave
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
import voz      # noqa: E402
from main import app   # noqa: E402

OK, FALLA = "\033[92mOK\033[0m", "\033[91mFALLA\033[0m"
resultados = []
api = TestClient(app)


def check(nombre, condicion, detalle=""):
    resultados.append(bool(condicion))
    print(f"  [{OK if condicion else FALLA}] {nombre}" + (f"  ->  {detalle}" if detalle else ""))


def audio_webm(segundos=2.0) -> bytes:
    """Un tono en webm/opus, como el que graba el navegador."""
    with tempfile.TemporaryDirectory() as d:
        salida = Path(d) / "voz.webm"
        subprocess.run([voz._ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
                        "-c:a", "libopus", str(salida)], check=True)
        return salida.read_bytes()


class VozFalsa:
    def synthesize_wav(self, texto, w, syn_config=None):
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 22050)


def main():
    print("\n1. Conversión de audio (ffmpeg real)")
    datos = audio_webm()
    wav = voz.a_wav16k(datos, ".webm")
    with wave.open(str(wav)) as w:
        check("El webm del navegador pasa a WAV 16 kHz mono", w.getframerate() == 16000 and w.getnchannels() == 1,
              f"{voz.duracion(wav):.1f} s")

    print("\n2. Texto que suena bien")
    t = voz.texto_para_hablar("Tenemos:\n- **COLCHON CASSATA 1.40** – $1.150.700 (4 und.). Su pedido es el DEC-2611-0009.")
    check("Precios en palabras", "un millón ciento cincuenta mil setecientos pesos" in t)
    check("Medidas como se dicen (uno cuarenta) y código cifra por cifra", "uno cuarenta" in t and "D E C, 2 6 1 1" in t, t[:80] + "...")
    check("Sin asteriscos ni viñetas", "*" not in t and "\n" not in t)

    print("\n3. Conversación por voz (oído y voz simulados)")
    voz._stt_local = lambda w: "¿Tienen colchones de 1.40?"
    config.STT_BACKEND = "local"
    voz._piper = VozFalsa()
    pasos = [("buscar_productos", {"texto": "colchon 1.40", "solo_disponibles": True}),
             "Sí, el Colchón Cassata 1.40 a $1.150.700. ¿Se lo aparto?"]

    def guion(messages, tools):
        p = pasos.pop(0)
        if isinstance(p, tuple):
            import json
            return {"content": None, "tool_calls": [{"id": "c1", "name": p[0], "arguments": json.dumps(p[1])}]}
        return {"content": p, "tool_calls": []}
    llm.usar_simulado(guion)
    r = api.post("/api/voz", files={"audio": ("voz.webm", datos, "audio/webm")})
    d = r.json()
    check("POST /api/voz responde", r.status_code == 200, d.get("transcripcion"))
    check("Usa el canal de voz con el prompt de respuestas cortas", d["herramientas"][0]["nombre"] == "buscar_productos")
    check("Devuelve el audio de la respuesta", d["audio_url"] and api.get(d["audio_url"]).status_code == 200, d["audio_url"])
    check("Lo que dice Deco está en palabras", "un millón" in d["texto_hablado"])
    with db.dueno() as c:
        tr = c.execute("SELECT ms_stt, ms_tts FROM agente_trazas WHERE id = %s", (d["traza_id"],)).fetchone()
        m = c.execute("SELECT audio_path FROM mensajes WHERE conversacion_id = %s AND rol = 'usuario'",
                      (d["conversacion_id"],)).fetchone()
    check("La traza guarda el tiempo del oído y de la voz", tr["ms_stt"] is not None and tr["ms_tts"] is not None,
          f"stt {tr['ms_stt']} ms, tts {tr['ms_tts']} ms")
    check("El mensaje del cliente guarda su audio", m["audio_path"] and m["audio_path"].endswith(".wav"))

    print("\n4. Respaldos y seguridad")
    voz._piper = None
    config.VOZ_PIPER = "voz-que-no-existe"
    r = api.post("/api/tts", json={"texto": "Total $500.000"}).json()
    check("Sin la voz de Piper, el navegador lee el texto", r["audio_url"] is None and "quinientos mil pesos" in r["texto_hablado"])
    check("Audio vacío: mensaje claro", api.post("/api/voz", files={"audio": ("v.webm", b"x", "audio/webm")}).status_code == 400)
    check("No se pueden pedir archivos fuera de la carpeta de audios", api.get("/api/audio/..%2Fmain.py").status_code == 404)
    s = api.get("/api/salud").json()
    check("/api/salud muestra el estado de la voz", "voz" in s and "stt" in s["voz"], str(s["voz"]["tts"]))

    print("\n5. Crédito pide teléfono (lo necesita el asesor)")
    import json
    pasos[:] = [("buscar_productos", {"texto": "sala chester"}),
                ("agregar_al_pedido", "PID"),
                ("registrar_cliente", {"documento": "9999000555", "nombre": "Sin Telefono"}),
                ("solicitar_credito", {"entidad": "sistecredito"}), "FIN"]
    vistos = []

    def guion2(messages, tools):
        res = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        p = pasos.pop(0)
        if p == "FIN":
            vistos.append(res[-1])
            return {"content": "Necesito su teléfono para el estudio.", "tool_calls": []}
        nombre, args = p
        if args == "PID":
            args = {"producto_id": res[-1]["resultados"][0]["producto_id"], "cantidad": 1}
        return {"content": None, "tool_calls": [{"id": f"c{len(pasos)}", "name": nombre, "arguments": json.dumps(args)}]}
    llm.usar_simulado(guion2)
    d = api.post("/api/chat", json={"mensaje": "quiero la sala chester a crédito, 9999000555, Sin Telefono"}).json()
    check("Sin teléfono no deja la solicitud de crédito", vistos and vistos[0].get("tipo") == "falta_telefono",
          vistos[0].get("error", "")[:70] if vistos else "")
    check("El pedido sigue sin solicitud de crédito", not d["pedido"]["solicita_credito"])

    db.cerrar()
    print(f"\nResultado: {sum(resultados)}/{len(resultados)} pruebas correctas")
    sys.exit(0 if all(resultados) else 1)


if __name__ == "__main__":
    main()
