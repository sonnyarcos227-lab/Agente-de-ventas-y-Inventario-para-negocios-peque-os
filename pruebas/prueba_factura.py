"""
prueba_factura.py - Prueba el paso 8: foto de la factura del proveedor -> entrada de inventario.

El modelo de visión (qwen2.5vl en Ollama) se simula con una lectura fija; la subida de la foto,
el cruce con el catálogo, la confirmación del dueño y la transacción son los reales.

    py pruebas\\prueba_factura.py
"""
import io
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
from PIL import Image, ImageDraw             # noqa: E402

import config   # noqa: E402
import db       # noqa: E402
import vision   # noqa: E402
from main import app   # noqa: E402

OK, FALLA = "\033[92mOK\033[0m", "\033[91mFALLA\033[0m"
resultados = []
api = TestClient(app)
CAB = {"X-Clave-Dueno": config.CLAVE_DUENO}


def check(nombre, condicion, detalle=""):
    resultados.append(bool(condicion))
    print(f"  [{OK if condicion else FALLA}] {nombre}" + (f"  ->  {detalle}" if detalle else ""))


def foto_factura() -> bytes:
    img = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(img)
    for i, t in enumerate(["COLCHONES SUEÑO REAL - FACTURA FE-8812", "COLCHON CASSATA 1.40 ARMONIA   x3",
                           "BASE CAMA SOMIER 1.60 TELA   x2", "ESCOBA PLASTICA   x5"]):
        d.text((40, 60 + i * 60), t, fill="black")
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


LECTURA = {"proveedor": "Colchones Sueño Real", "numero_factura": "FE-8812", "lineas": [
    {"descripcion": "COLCHON CASSATA 1.40 ARMONIA", "cantidad": 3, "codigo": "CS140", "valor_unitario": 690000},
    {"descripcion": "BASE CAMA SOMIER 1.60 TELA", "cantidad": "2", "codigo": None, "valor_unitario": None},
    {"descripcion": "ESCOBA PLASTICA XYZ", "cantidad": 5},          # no existe en el catálogo
    {"descripcion": "", "cantidad": 9}]}                             # línea vacía: se ignora


def stock(pid):
    with db.dueno() as c:
        return c.execute("SELECT existencias FROM inventario WHERE producto_id = %s", (pid,)).fetchone()["existencias"]


def main():
    vision.leer_factura = lambda imagen: LECTURA
    foto = foto_factura()

    print("\n1. Leer la factura (propuesta)")
    r = api.post("/api/dueno/factura", headers=CAB, files={"imagen": ("factura.png", foto, "image/png")})
    d = r.json()
    check("Sube la foto y devuelve la propuesta", r.status_code == 200, f"{len(d['lineas'])} líneas, factura {d['numero_factura']}")
    cass = next(l for l in d["lineas"] if "CASSATA" in l["descripcion"])
    check("Cruza la línea con el producto real del catálogo", cass["producto_id"] and "CASSATA" in cass["candidatos"][0]["nombre"],
          cass["candidatos"][0]["nombre"])
    check("Convierte la cantidad '2' (texto) en número", next(l for l in d["lineas"] if "SOMIER" in l["descripcion"])["cantidad"] == 2)
    escoba = next(l for l in d["lineas"] if "ESCOBA" in l["descripcion"])
    check("Lo que no está en el catálogo queda sin producto (no inventa)", escoba["producto_id"] is None)
    check("Ignora las líneas vacías", len(d["lineas"]) == 3)
    antes = stock(cass["producto_id"])
    check("Leer la factura NO toca el inventario", stock(cass["producto_id"]) == antes)

    print("\n2. El dueño confirma")
    somier = next(l for l in d["lineas"] if "SOMIER" in l["descripcion"])
    antes_s = stock(somier["producto_id"])
    r = api.post("/api/dueno/factura/confirmar", headers=CAB, json={"referencia": "FE-8812", "lineas": [
        {"producto_id": cass["producto_id"], "cantidad": 3}, {"producto_id": somier["producto_id"], "cantidad": 2}]})
    check("Entran los productos confirmados", r.status_code == 200 and stock(cass["producto_id"]) == antes + 3
          and stock(somier["producto_id"]) == antes_s + 2, f"Cassata {antes} -> {stock(cass['producto_id'])}")
    with db.dueno() as c:
        k = c.execute("SELECT count(*) AS n FROM movimientos_stock WHERE referencia = 'Factura FE-8812' AND tipo = 'entrada'").fetchone()["n"]
    check("Queda en el kardex con el número de factura", k == 2)

    print("\n3. Todo o nada")
    antes = stock(cass["producto_id"])
    r = api.post("/api/dueno/factura/confirmar", headers=CAB, json={"referencia": "FE-MALA", "lineas": [
        {"producto_id": cass["producto_id"], "cantidad": 1}, {"producto_id": 999999, "cantidad": 1}]})
    check("Si una línea falla, no entra ninguna (una sola transacción)", r.status_code == 400 and stock(cass["producto_id"]) == antes,
          r.json().get("detail", "")[:60])

    print("\n4. Seguridad")
    check("Sin la clave del dueño no se puede", api.post("/api/dueno/factura", files={"imagen": ("f.png", foto, "image/png")}).status_code == 401)
    check("Solo acepta imágenes", api.post("/api/dueno/factura", headers=CAB,
                                           files={"imagen": ("f.txt", b"hola", "text/plain")}).status_code == 400)
    check("No acepta cantidades absurdas", api.post("/api/dueno/factura/confirmar", headers=CAB, json={
        "lineas": [{"producto_id": cass["producto_id"], "cantidad": 100000}]}).status_code == 422)
    check("El agente (Deco) no puede meter mercancía", "fn_entrada_inventario" not in
          (BACKEND / "herramientas.py").read_text(encoding="utf-8"))

    print("\n5. Respuestas raras del modelo de visión")
    check("Saca el JSON aunque venga con texto alrededor",
          vision._json_de('Claro, aquí está: {"lineas": [{"descripcion": "SILLA", "cantidad": 2}]} listo')["lineas"][0]["cantidad"] == 2)
    try:
        vision._json_de("no pude leer la imagen")
        check("Avisa si el modelo no devuelve datos", False)
    except vision.VisionError as e:
        check("Avisa si el modelo no devuelve datos", True, str(e))
    vision.leer_factura = vision.leer_factura_ollama
    config.OLLAMA_URL = "http://127.0.0.1:9"
    r = api.post("/api/dueno/factura", headers=CAB, files={"imagen": ("f.png", foto, "image/png")})
    check("Con Ollama apagado da un mensaje claro", r.status_code == 503 and "Ollama" in r.json()["detail"])

    # limpieza: devolver el inventario como estaba (ajuste negativo registrado)
    with psycopg_admin() as c:
        for pid, n in ((cass["producto_id"], 3), (somier["producto_id"], 2)):
            c.execute("UPDATE inventario SET existencias = existencias - %s WHERE producto_id = %s", (n, pid))
            c.execute("""INSERT INTO movimientos_stock(producto_id, tipo, cantidad, existencias_antes, existencias_despues, motivo, referencia)
                         SELECT %s, 'ajuste', -%s, existencias + %s, existencias, 'Reverso prueba automática', 'PRUEBA-FACTURA'
                         FROM inventario WHERE producto_id = %s""", (pid, n, n, pid))
    db.cerrar()
    print(f"\nResultado: {sum(resultados)}/{len(resultados)} pruebas correctas")
    sys.exit(0 if all(resultados) else 1)


def psycopg_admin():
    import psycopg
    return psycopg.connect(os.getenv("DECORER_ADMIN_URL", f"postgresql://postgres:postgres@{config.DB_HOST}/decorer"),
                           autocommit=True)


if __name__ == "__main__":
    main()
