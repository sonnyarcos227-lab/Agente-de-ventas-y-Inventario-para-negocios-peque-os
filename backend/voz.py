"""
voz.py - Oído y boca de Deco.

  STT (voz -> texto):  faster-whisper en el PC (modelo "small", int8, CPU)
                       respaldo: Whisper large-v3-turbo de Groq (como en Archivo Vivo)
  TTS (texto -> voz):  Piper con la voz es_MX-claude-high (local, rápida en CPU)
                       respaldo: la voz del navegador (speechSynthesis), la pone el frontend

El audio del navegador llega en webm/ogg; ffmpeg (incluido en imageio-ffmpeg) lo pasa a
WAV 16 kHz mono, que es lo que espera Whisper.
"""
import io
import os
import re
import subprocess
import tempfile
import time
import uuid
import wave
from pathlib import Path

import config

CARPETA_AUDIOS = Path(__file__).resolve().parent / "audios"
CARPETA_AUDIOS.mkdir(exist_ok=True)

_whisper = None
_piper = None


class VozError(RuntimeError):
    pass


# ── ffmpeg ────────────────────────────────────────────────────────────────────
def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def a_wav16k(datos: bytes, sufijo: str = ".webm") -> Path:
    """Convierte cualquier audio a WAV 16 kHz mono y lo guarda en backend/audios."""
    destino = CARPETA_AUDIOS / f"cliente_{uuid.uuid4().hex[:12]}.wav"
    with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as f:
        f.write(datos)
        origen = f.name
    try:
        r = subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", origen, "-ar", "16000", "-ac", "1", str(destino)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not destino.exists():
            raise VozError(f"No se pudo leer el audio: {r.stderr.strip()[:200]}")
    finally:
        os.unlink(origen)
    return destino


def duracion(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / float(w.getframerate())


# ── STT ───────────────────────────────────────────────────────────────────────
def _stt_local(wav: Path) -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel   # la primera vez descarga el modelo (small ≈ 460 MB)
        _whisper = WhisperModel(config.STT_MODELO, device="cpu", compute_type="int8",
                                cpu_threads=max(2, (os.cpu_count() or 4) - 1))
    segmentos, _ = _whisper.transcribe(str(wav), language="es", beam_size=1, vad_filter=True,
                                       initial_prompt=config.STT_PISTA)
    return " ".join(s.text.strip() for s in segmentos).strip()


def _stt_groq(wav: Path) -> str:
    if not config.GROQ_API_KEY or "YOUR_KEY" in config.GROQ_API_KEY:
        raise VozError("No hay clave de Groq para transcribir")
    from openai import OpenAI
    cliente = OpenAI(api_key=config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", timeout=40, max_retries=0)
    with open(wav, "rb") as f:
        r = cliente.audio.transcriptions.create(model=config.STT_MODELO_GROQ, file=f, language="es",
                                                prompt=config.STT_PISTA)
    return (r.text or "").strip()


def transcribir(wav: Path) -> dict:
    """Devuelve {texto, motor, ms}. Prueba el motor configurado y luego el otro."""
    orden = {"local": ["local"], "groq": ["groq"]}.get(config.STT_BACKEND, ["local", "groq"])
    errores = []
    for motor in orden:
        t0 = time.perf_counter()
        try:
            texto = _stt_local(wav) if motor == "local" else _stt_groq(wav)
            return {"texto": texto, "motor": f"faster-whisper {config.STT_MODELO}" if motor == "local"
                    else f"groq {config.STT_MODELO_GROQ}", "ms": int((time.perf_counter() - t0) * 1000)}
        except Exception as e:
            errores.append(f"{motor}: {type(e).__name__}: {str(e)[:150]}")
    raise VozError("No se pudo transcribir el audio. " + " | ".join(errores))


# ── Texto que suena bien ──────────────────────────────────────────────────────
def _numero_en_palabras(n: int) -> str:
    try:
        from num2words import num2words
        return num2words(n, lang="es")
    except Exception:
        return str(n)


def texto_para_hablar(texto: str) -> str:
    """Quita lo que se ve pero no se dice (markdown, emojis) y pasa precios y códigos a palabras."""
    t = texto or ""
    t = re.sub(r"[*_#`>|]+", " ", t)                                  # markdown
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)                     # viñetas
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿←-⇿✀-➿✋✓✗]", "", t)   # emojis y flechas
    t = re.sub(r"\$\s?(\d{1,3}(?:\.\d{3})+|\d+)",
               lambda m: _numero_en_palabras(int(m.group(1).replace(".", ""))) + " pesos", t)
    t = re.sub(r"\b(\d{1,3}(?:\.\d{3})+)\b", lambda m: _numero_en_palabras(int(m.group(1).replace(".", ""))), t)
    t = re.sub(r"\bDEC-(\d{4})-(\d{4})\b",                           # código del pedido, cifra por cifra
               lambda m: "D E C, " + " ".join(m.group(1)) + ", " + " ".join(m.group(2)), t)
    t = re.sub(r"\b(\d{3}) (\d{3}) (\d{4})\b", lambda m: " ".join(m.group(1)) + ", " + " ".join(m.group(2))
               + ", " + " ".join(m.group(3)), t)                       # teléfonos
    t = re.sub(r"\b(\d)\.00\b", lambda m: "un metro", t)     # 1.00 -> "un metro"
    t = re.sub(r"\b(\d)\.(\d{2})\b",                                # medidas: 1.40 -> "uno cuarenta"
               lambda m: _numero_en_palabras(int(m.group(1))) + " " + _numero_en_palabras(int(m.group(2))), t)
    t = re.sub(r"\b(\d)\s?[xX*]\s?(\d)\b",                            # 2X2 -> "dos por dos"
               lambda m: _numero_en_palabras(int(m.group(1))) + " por " + _numero_en_palabras(int(m.group(2))), t)
    t = re.sub(r"\bC\.?C\.?\b", "cédula", t)
    t = re.sub(r"\s+[–—]\s+", ", ", t)
    t = re.sub(r":\s*\n+", ": ", t)
    t = t.replace("Sistecrédito", "Siste crédito")
    t = re.sub(r"\b1 und\.?", "una unidad", t)
    t = re.sub(r"\b(\d+) und\.?", lambda m: _numero_en_palabras(int(m.group(1))) + " unidades", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t).replace("..", ".")
    return t.strip()


# ── TTS ───────────────────────────────────────────────────────────────────────
def ruta_voz() -> Path:
    return Path(__file__).resolve().parent / "voz_modelos" / f"{config.VOZ_PIPER}.onnx"


def _cargar_piper():
    global _piper
    if _piper is None:
        modelo = ruta_voz()
        if not modelo.exists():
            raise VozError(f"Falta la voz de Piper ({modelo.name}). Descárgala con: "
                           f"py -m piper.download_voices {config.VOZ_PIPER} --download-dir voz_modelos")
        from piper import PiperVoice
        _piper = PiperVoice.load(str(modelo))
    return _piper


def sintetizar(texto: str) -> dict:
    """Devuelve {archivo, ms, texto_hablado} o lanza VozError si Piper no está disponible."""
    hablado = texto_para_hablar(texto)
    t0 = time.perf_counter()
    voz = _cargar_piper()
    nombre = f"deco_{uuid.uuid4().hex[:12]}.wav"
    try:
        from piper import SynthesisConfig
        ajustes = SynthesisConfig(length_scale=config.VOZ_VELOCIDAD)
    except Exception:
        ajustes = None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voz.synthesize_wav(hablado, w, syn_config=ajustes)
    (CARPETA_AUDIOS / nombre).write_bytes(buf.getvalue())
    return {"archivo": nombre, "ms": int((time.perf_counter() - t0) * 1000), "texto_hablado": hablado}


def precargar():
    """Deja la voz y el oído listos en memoria (se llama al arrancar el servidor, en segundo plano)."""
    try:
        if ruta_voz().exists():
            _cargar_piper()
            voz_lista = _piper
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:        # la primera síntesis es la lenta: se hace aquí, no con el cliente
                voz_lista.synthesize_wav("Hola.", w)
            print("[voz] Piper listo")
    except Exception as e:
        print(f"[voz] Piper no se pudo precargar: {e}")
    if config.STT_BACKEND in ("local", "auto"):
        try:
            global _whisper
            if _whisper is None:
                from faster_whisper import WhisperModel
                _whisper = WhisperModel(config.STT_MODELO, device="cpu", compute_type="int8",
                                        cpu_threads=max(2, (os.cpu_count() or 4) - 1))
            print(f"[voz] faster-whisper {config.STT_MODELO} listo")
        except Exception as e:
            print(f"[voz] faster-whisper no se pudo cargar (se usará Whisper de Groq): {type(e).__name__}: {e}")


def estado() -> dict:
    from importlib.util import find_spec
    return {"stt": {"backend": config.STT_BACKEND, "faster_whisper_instalado": find_spec("faster_whisper") is not None,
                    "modelo": config.STT_MODELO, "respaldo_groq": config.STT_MODELO_GROQ},
            "stt_local_cargado": _whisper is not None,
            "tts": {"piper_instalado": find_spec("piper") is not None, "piper_cargado": _piper is not None, "voz": config.VOZ_PIPER,
                    "voz_descargada": ruta_voz().exists(), "respaldo": "voz del navegador"}}
