"""embeddings.py - EmbeddingGemma 2 servido por llama.cpp (el mismo de Archivo Vivo)."""
import json
import urllib.error
import urllib.request

import config

DIM = 768


class EmbeddingsApagados(RuntimeError):
    pass


def vector_pregunta(pregunta: str):
    """Vector de una pregunta, con el prefijo que pide EmbeddingGemma 2."""
    req = urllib.request.Request(
        f"{config.LLAMACPP_EMBED_URL}/v1/embeddings",
        data=json.dumps({"model": "embeddinggemma2", "input": [f"task: search result | query: {pregunta}"],
                         "encoding_format": "float"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError) as e:
        raise EmbeddingsApagados(str(e)) from e
    v = data["data"][0]["embedding"]
    v = v[0] if v and isinstance(v[0], list) else v
    if len(v) != DIM:
        raise EmbeddingsApagados(f"El modelo devolvió {len(v)} dimensiones, se esperaban {DIM}")
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def disponible() -> bool:
    try:
        with urllib.request.urlopen(f"{config.LLAMACPP_EMBED_URL}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False
