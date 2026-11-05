"""config.py - Configuración del backend de Decorer (se lee de backend/.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

AQUI = Path(__file__).resolve().parent
load_dotenv(AQUI / ".env")


def _lista(v: str):
    return [x.strip() for x in v.split(",") if x.strip()]


# Base de datos: el agente y el dueño entran con usuarios distintos (mínimo privilegio)
DB_HOST = os.getenv("DECORER_HOST", "localhost:5432")
URL_AGENTE = os.getenv("DECORER_AGENTE_URL", f"postgresql://agente_decorer:decorer_agente_2026@{DB_HOST}/decorer")
URL_DUENO = os.getenv("DECORER_DUENO_URL", f"postgresql://dueno_decorer:decorer_dueno_2026@{DB_HOST}/decorer")

# LLM: groq | ollama | auto (Groq y, si falla, Ollama) | simulado (solo pruebas)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
if not GROQ_API_KEY or "YOUR_KEY" in GROQ_API_KEY:
    # Si no hay clave aquí, usa la de Archivo Vivo (Escritorio\Chatpdf\backend\.env), que ya funciona
    _archivo_vivo = AQUI.parent.parent / "Chatpdf" / "backend" / ".env"
    if _archivo_vivo.exists():
        from dotenv import dotenv_values
        GROQ_API_KEY = dotenv_values(_archivo_vivo).get("GROQ_API_KEY") or GROQ_API_KEY
GROQ_MODELS = _lista(os.getenv("GROQ_MODELS", "openai/gpt-oss-120b,llama-3.3-70b-versatile,openai/gpt-oss-20b,qwen/qwen3.8-27b"))
ESPERA_MAX_429 = float(os.getenv("ESPERA_MAX_429", "8"))     # segundos que vale la pena esperar si Groq pide esperar
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low")       # gpt-oss: low | medium | high
MAX_PASOS = int(os.getenv("AGENTE_MAX_PASOS", "6"))          # rondas de herramientas por turno
HISTORIAL = int(os.getenv("AGENTE_HISTORIAL", "10"))        # mensajes previos que ve el LLM

# Embeddings: EmbeddingGemma 2 en llama.cpp (el de Archivo Vivo)
LLAMACPP_EMBED_URL = os.getenv("LLAMACPP_EMBED_URL", "http://127.0.0.1:8081").rstrip("/")

# Panel del dueño (clave sencilla para el prototipo)
CLAVE_DUENO = os.getenv("CLAVE_DUENO", "decorer2026")

# Datos de la tienda que el agente siempre tiene a mano
TIENDA = {
    "nombre": "Decorer",
    "direccion": "Carrera 9 # 19-49, Avenida Colombia, al lado del Hospital José María Hernández, Mocoa",
    "whatsapp": "322 378 7495",
    "horario": "lunes a sábado de 9:15 a. m. a 12:15 p. m. y de 2:00 p. m. a 6:15 p. m.",
    "redes": "@decorermocoa en Instagram y TikTok, Decorer Mocoa en Facebook",
}

# Voz
STT_BACKEND = os.getenv("STT_BACKEND", "auto").lower()          # local (faster-whisper) | groq | auto
STT_MODELO = os.getenv("STT_MODELO", "small")                   # tiny | base | small (recomendado en CPU)
STT_MODELO_GROQ = os.getenv("STT_MODELO_GROQ", "whisper-large-v3-turbo")
# Palabras de la tienda para que Whisper las escriba bien
STT_PISTA = os.getenv("STT_PISTA", "Decorer, Mocoa, colchón, sofacama, comedor flor morado, nevecón, Cassata, "
                                   "Maderkit, Sistecrédito, Addi, separado, domicilio, cédula.")
VOZ_PIPER = os.getenv("VOZ_PIPER", "es_MX-claude-high")
VOZ_VELOCIDAD = float(os.getenv("VOZ_VELOCIDAD", "1.0"))        # >1 más despacio, <1 más rápido

# Visión (factura del proveedor): qwen2.5vl en Ollama, como en Archivo Vivo
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "300"))      # en CPU una factura puede tardar 1-3 minutos
