"""
indexar_conocimiento.py - Lleva los documentos de conocimiento de Decorer a pgvector.

  py conocimiento\\indexar_conocimiento.py                 (indexa todos los .md de esta carpeta)
  py conocimiento\\indexar_conocimiento.py --buscar "¿lo puedo pagar por cuotas?"
  py conocimiento\\indexar_conocimiento.py --prueba        (sin llama.cpp: vectores de mentira, solo para probar)

Cada sección "## ..." de un documento es un fragmento (chunk): así la respuesta
del agente puede citar la política exacta. Los vectores salen de EmbeddingGemma 2
en llama.cpp (el mismo servidor de Archivo Vivo, puerto 8081), con sus prefijos:
    documento:  "title: {titulo} | text: {contenido}"
    pregunta:   "task: search result | query: {pregunta}"
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

AQUI = Path(__file__).resolve().parent
LLAMACPP = os.getenv("LLAMACPP_EMBED_URL", "http://127.0.0.1:8081").rstrip("/")
DIM = 768
ADMIN = os.getenv("DECORER_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/decorer")


def vector_prueba(texto: str):
    """Vector determinista a partir del texto (solo para probar sin llama.cpp)."""
    h = hashlib.sha256(texto.encode()).digest()
    v = [((h[i % 32] + i * 37) % 255) / 255 - 0.5 for i in range(DIM)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def embeber(textos, prueba=False):
    if prueba:
        return [vector_prueba(t) for t in textos]
    req = urllib.request.Request(
        f"{LLAMACPP}/v1/embeddings",
        data=json.dumps({"model": "embeddinggemma2", "input": textos, "encoding_format": "float"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
    except urllib.error.URLError:
        sys.exit("llama.cpp no está corriendo en el puerto 8081. Ábrelo con:\n"
                 "  llama-server -hf unsloth/embeddinggemma-2-GGUF:UD-Q4_K_XL --embeddings --port 8081 --device none -ngl 0\n"
                 "(o usa --prueba para probar sin embeddings reales)")
    vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    vecs = [v[0] if v and isinstance(v[0], list) else v for v in vecs]
    if len(vecs[0]) != DIM:
        sys.exit(f"El modelo devolvió {len(vecs[0])} dimensiones y la tabla espera {DIM}. ¿Es EmbeddingGemma 2?")
    return vecs


def a_pgvector(v):
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def leer_documento(ruta: Path):
    texto = ruta.read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    if m:
        for linea in m.group(1).splitlines():
            if ":" in linea:
                k, v = linea.split(":", 1)
                meta[k.strip()] = v.strip()
        texto = texto[m.end():]
    secciones = re.split(r"\n(?=## )", "\n" + texto.strip())
    chunks = []
    for s in secciones:
        s = s.strip()
        if not s.startswith("## "):
            continue
        titulo, _, cuerpo = s[3:].partition("\n")
        chunks.append({"titulo": titulo.strip(), "contenido": f"{titulo.strip()}. {cuerpo.strip()}"})
    return meta.get("tipo", "faq"), meta.get("titulo", ruta.stem), chunks


def indexar(prueba=False):
    docs = sorted(p for p in AQUI.glob("*.md") if not p.name.upper().startswith("LEEME"))
    total = 0
    with psycopg.connect(ADMIN) as conn:
        for ruta in docs:
            tipo, titulo_doc, chunks = leer_documento(ruta)
            vecs = embeber([f"title: {titulo_doc} - {c['titulo']} | text: {c['contenido']}" for c in chunks], prueba)
            conn.execute("DELETE FROM conocimiento WHERE fuente = %s", (ruta.name,))
            for i, (c, v) in enumerate(zip(chunks, vecs)):
                conn.execute("""INSERT INTO conocimiento(fuente, tipo, titulo, chunk_index, contenido, metadatos, embedding)
                                VALUES (%s, %s, %s, %s, %s, %s, %s::vector)""",
                             (ruta.name, tipo, c["titulo"], i, c["contenido"],
                              json.dumps({"documento": titulo_doc, "vectores_de_prueba": prueba}), a_pgvector(v)))
            total += len(chunks)
            print(f"  {ruta.name:28} {tipo:20} {len(chunks):>3} fragmentos")
        conn.commit()
    print(f"\n{total} fragmentos en la tabla conocimiento" + ("  (vectores de PRUEBA)" if prueba else ""))


def buscar(pregunta, prueba=False):
    v = embeber([f"task: search result | query: {pregunta}"], prueba)[0]
    with psycopg.connect(ADMIN) as conn:
        filas = conn.execute("SELECT fuente, titulo, similitud, left(contenido, 160) FROM fn_buscar_conocimiento(%s::vector, NULL, 4, 0)",
                             (a_pgvector(v),)).fetchall()
    print(f"\nPregunta: {pregunta}")
    for fuente, titulo, sim, txt in filas:
        print(f"  {sim:.3f}  [{fuente} > {titulo}]  {txt}...")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--buscar")
    ap.add_argument("--prueba", action="store_true")
    a = ap.parse_args()
    if a.buscar:
        buscar(a.buscar, a.prueba)
    else:
        indexar(a.prueba)
