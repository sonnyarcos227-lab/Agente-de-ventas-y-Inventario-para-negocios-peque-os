"""
leer_precios_syscafe.py - Convierte el PDF "Lista de precios - Lista general" de SysCafé en un CSV.

Uso:  py importar\\leer_precios_syscafe.py LISTA_DE_PRECIOS.pdf  importar\\syscafe_precios.csv

Cada artículo ocupa una línea (referencia de 5 dígitos, detalle y precio) y a veces
una segunda línea con el resto del detalle. cargar_inventario.py toma estos precios
por la referencia (el mismo código del listado de inventario).
"""
import csv
import re
import sys

FILA = re.compile(r"^(\d{5})\s+(.+?)\s{2,}(\d{1,3}(?:,\d{3})*)(?:\s+(\d+(?:\.\d+)?))?\s*$")
RUIDO = re.compile(r"SysCaf|JEMSA|LISTA DE PRECIOS|Referencia|INVENTARIO MERCAN|M/CIAS NO FABRICADAS|CLL \d")


def lineas_del_pdf(ruta):
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        for pagina in fitz.open(ruta):
            yield from pagina.get_text("text", sort=True).splitlines()
    except ImportError:
        import subprocess
        yield from subprocess.run(["pdftotext", "-layout", ruta, "-"], capture_output=True, text=True).stdout.splitlines()


def leer(ruta):
    precios, actual = [], None
    for linea in lineas_del_pdf(ruta):
        if not linea.strip() or RUIDO.search(linea):
            continue
        m = FILA.match(linea.strip())
        if m:
            actual = {"codigo": m.group(1), "detalle": re.sub(r"\s+", " ", m.group(2)).strip(),
                      "precio": int(m.group(3).replace(",", "")), "iva": m.group(4) or ""}
            precios.append(actual)
        elif actual and not re.search(r"\d{1,3},\d{3}\s*$", linea):
            actual["detalle"] += " " + re.sub(r"\s+", " ", linea).strip()
    return precios


if __name__ == "__main__":
    origen = sys.argv[1] if len(sys.argv) > 1 else "LISTA_DE_PRECIOS.pdf"
    destino = sys.argv[2] if len(sys.argv) > 2 else "syscafe_precios.csv"
    filas = leer(origen)
    with open(destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["codigo", "detalle", "precio", "iva"])
        w.writeheader()
        w.writerows(filas)
    con_precio = [r for r in filas if r["precio"] > 0]
    print(f"{len(filas)} referencias -> {destino}  ({len(con_precio)} con precio mayor que cero)")
