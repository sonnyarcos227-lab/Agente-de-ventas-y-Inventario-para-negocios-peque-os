"""
vision.py - Lee la foto de una factura de proveedor y propone la entrada de mercancía.

  foto -> qwen2.5vl:3b en Ollama (el mismo modelo de visión de Archivo Vivo)
       -> JSON con las líneas de la factura (descripción, cantidad, código, valor)
       -> cada línea se cruza con el catálogo (fn_buscar_productos)
       -> el DUEÑO revisa y confirma en el panel (nunca entra mercancía sin su confirmación)
"""
import base64
import io
import json
import re
import urllib.error
import urllib.request

import config
import herramientas as H

PROMPT = (
    "Esta imagen es una factura o remisión de un proveedor de una tienda de muebles y electrodomésticos. "
    "Extrae SOLO las líneas de productos. Responde únicamente con JSON con esta forma: "
    '{"proveedor": "...", "numero_factura": "...", "lineas": [{"descripcion": "...", "cantidad": 1, '
    '"codigo": "...", "valor_unitario": 0}]}. Usa null si un dato no se ve. No inventes productos: si no se lee '
    "una línea, no la pongas. La cantidad es un número entero."
)


class VisionError(RuntimeError):
    pass


def _achicar(datos: bytes) -> bytes:
    """Reduce fotos grandes del celular (en CPU, qwen2.5vl tarda mucho con imágenes de 4000 px)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(datos))
        img = img.convert("RGB")
        img.thumbnail((1600, 1600))
        salida = io.BytesIO()
        img.save(salida, format="JPEG", quality=88)
        return salida.getvalue()
    except Exception:
        return datos


def _json_de(texto: str) -> dict:
    texto = (texto or "").strip()
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise VisionError("El modelo de visión no devolvió datos de la factura.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise VisionError(f"El modelo de visión devolvió un JSON inválido: {e}")


def leer_factura_ollama(imagen: bytes) -> dict:
    payload = {"model": config.OLLAMA_VISION_MODEL, "stream": False, "format": "json", "keep_alive": "120s",
               "messages": [{"role": "user", "content": PROMPT,
                             "images": [base64.b64encode(_achicar(imagen)).decode("ascii")]}],
               "options": {"temperature": 0, "num_predict": 900}}
    req = urllib.request.Request(f"{config.OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=config.VISION_TIMEOUT) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise VisionError(f"Ollama respondió {e.code}: {e.read().decode(errors='ignore')[:200]}. "
                          f"¿Está descargado el modelo? ollama pull {config.OLLAMA_VISION_MODEL}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise VisionError(f"No se pudo conectar con Ollama ({config.OLLAMA_URL}). Ábralo y vuelva a intentar. ({e})")
    return _json_de((data.get("message") or {}).get("content", ""))


# se puede reemplazar en las pruebas
leer_factura = leer_factura_ollama


def _entero(v, defecto=None):
    try:
        n = int(float(str(v).replace(",", ".").strip()))
        return n if n > 0 else defecto
    except (TypeError, ValueError):
        return defecto


def proponer_entrada(imagen: bytes) -> dict:
    """Lee la factura y propone, para cada línea, el producto del catálogo más parecido."""
    datos = leer_factura(imagen)
    propuesta = []
    for linea in (datos.get("lineas") or [])[:40]:
        desc = str(linea.get("descripcion") or "").strip()
        if not desc:
            continue
        candidatos = H._filas_productos(desc, None, None, False, limite=4)
        if not candidatos:   # nombres de factura largos: probar con las primeras palabras
            candidatos = H._filas_productos(" ".join(desc.split()[:3]), None, None, False, limite=4)
        propuesta.append({
            "descripcion": desc, "codigo_proveedor": linea.get("codigo"),
            "cantidad": _entero(linea.get("cantidad"), 1), "valor_unitario": _entero(linea.get("valor_unitario")),
            "candidatos": [{"producto_id": c["producto_id"], "nombre": c["nombre"], "existencias": c["existencias"]}
                           for c in candidatos],
            "producto_id": candidatos[0]["producto_id"] if candidatos else None,
        })
    return {"proveedor": datos.get("proveedor"), "numero_factura": datos.get("numero_factura"),
            "lineas": propuesta, "modelo": config.OLLAMA_VISION_MODEL,
            "nota": "Revise cada línea: el producto propuesto puede no ser el correcto." if propuesta
                    else "No se encontraron líneas de productos en la imagen."}
