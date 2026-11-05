"""
llm.py - Cliente del modelo de lenguaje con llamadas a herramientas.

Groq y Ollama hablan el mismo idioma (la API de chat de OpenAI), así que un solo
cliente sirve para los dos:
  - groq:   modelos grandes en la nube, gratis y rápidos (lo recomendado en un PC sin GPU)
  - ollama: modelo local (qwen2.5:7b por defecto) como respaldo sin internet
  - auto:   intenta Groq con cada modelo de la lista y, si todo falla, Ollama
  - simulado: respuestas programadas, solo para las pruebas automáticas
"""
import re
import time
from typing import Callable, Optional

import config

_simulado: Optional[Callable] = None


class LLMNoDisponible(RuntimeError):
    pass


def usar_simulado(fn: Optional[Callable]):
    """fn(messages, tools) -> {"content": str|None, "tool_calls": [{"id","name","arguments"}]}"""
    global _simulado
    _simulado = fn


def _cliente(proveedor: str):
    from openai import OpenAI
    if proveedor == "groq":
        if not config.GROQ_API_KEY or "YOUR_KEY" in config.GROQ_API_KEY:
            raise LLMNoDisponible("Falta GROQ_API_KEY en backend/.env (gratis en https://console.groq.com)")
        return OpenAI(api_key=config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", timeout=25, max_retries=0)
    return OpenAI(api_key="ollama", base_url=f"{config.OLLAMA_URL}/v1", timeout=180, max_retries=0)


def _normalizar(msg) -> dict:
    llamadas = []
    for tc in (msg.tool_calls or []):
        llamadas.append({"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments or "{}"})
    return {"content": msg.content, "tool_calls": llamadas}


def _espera_429(e: Exception) -> Optional[float]:
    """Segundos que pide Groq esperar en un error 429 ("Please try again in 3.2s" / "in 1m2s")."""
    texto = str(e)
    if "429" not in texto and "rate limit" not in texto.lower():
        return None
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", texto)
    if not m:
        return 5.0
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def chat(messages: list, tools: list, preferido: Optional[str] = None) -> tuple[dict, str]:
    """Devuelve (respuesta normalizada, modelo que respondió).
    preferido: el modelo que ya respondió en este turno; se intenta primero para no cambiar de "cerebro" a mitad."""
    if config.LLM_PROVIDER == "simulado" or _simulado:
        if not _simulado:
            raise LLMNoDisponible("LLM simulado sin guion")
        return _simulado(messages, tools), "simulado"

    intentos = []
    if config.LLM_PROVIDER in ("groq", "auto"):
        intentos += [("groq", m) for m in config.GROQ_MODELS]
    if config.LLM_PROVIDER in ("ollama", "auto"):
        intentos.append(("ollama", config.OLLAMA_MODEL))
    if preferido:
        intentos.sort(key=lambda pm: f"{pm[0]}:{pm[1]}" != preferido)

    errores = []
    for proveedor, modelo in intentos:
        for intento in range(2):
            try:
                extra = {}
                if proveedor == "groq" and "gpt-oss" in modelo:
                    # gpt-oss "piensa" antes de responder; para vender basta poco razonamiento y es mucho más rápido
                    extra["reasoning_effort"] = config.REASONING_EFFORT
                r = _cliente(proveedor).chat.completions.create(
                    model=modelo, messages=messages, tools=tools, tool_choice="auto",
                    temperature=config.LLM_TEMPERATURE, max_tokens=700, extra_body=extra or None)
                return _normalizar(r.choices[0].message), f"{proveedor}:{modelo}"
            except LLMNoDisponible as e:
                if str(e) not in errores:
                    errores.append(str(e))
                break
            except Exception as e:
                espera = _espera_429(e)
                if espera is not None and espera <= config.ESPERA_MAX_429 and intento == 0:
                    time.sleep(espera + 0.3)      # límite por minuto: esperar unos segundos sale mejor que cambiar de modelo
                    continue
                errores.append(f"{proveedor}:{modelo} -> {type(e).__name__}: {str(e)[:160]}")
                break
    raise LLMNoDisponible(" | ".join(errores) or "No hay proveedor de LLM configurado")


def estado() -> dict:
    return {"proveedor": config.LLM_PROVIDER, "groq_modelos": config.GROQ_MODELS,
            "groq_clave": bool(config.GROQ_API_KEY and "YOUR_KEY" not in config.GROQ_API_KEY),
            "ollama": f"{config.OLLAMA_URL} ({config.OLLAMA_MODEL})", "simulado": bool(_simulado)}
