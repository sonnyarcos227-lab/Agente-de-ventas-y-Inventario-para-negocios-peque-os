"""
leer_syscafe.py - Convierte el PDF "Listado de saldos de inventario" de SysCafé en un CSV.

Uso:  py importar\\leer_syscafe.py INVENTARIO.pdf  importar\\syscafe_articulos.csv
Requiere: pip install pymupdf   (ya está en Archivo Vivo)

También muestra cuántos artículos tienen saldo negativo: es la primera señal de que
en SysCafé se registran ventas sin registrar las compras o entradas de mercancía.

Cada artículo del PDF ocupa una línea (código de 5 dígitos, nombre y tres cifras:
unidades, valor unitario y valor total) y a veces una segunda línea con el resto del nombre.
"""
import csv
import re
import sys

NUM = r"(-?[\d,]+\.\d{2})"
FILA = re.compile(rf"^(\d{{5}})\s+(.+?)\s{{2,}}{NUM}\s+{NUM}\s+{NUM}\s*$")
RUIDO = re.compile(r"SysCaf|DECOR JEMSA|Nit:|LISTADO DE|Articulo|INVENTARIO MERCAN|M/CIAS NO FABRICADAS|Total unds")


def num(s):
    return float(s.replace(",", ""))


def lineas_del_pdf(ruta):
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # PyMuPDF (nombre antiguo)
        doc = fitz.open(ruta)
        for pagina in doc:
            # "blocks" ordenado mantiene las columnas en la misma línea
            for linea in pagina.get_text("text", sort=True).splitlines():
                yield linea
    except ImportError:
        import subprocess
        out = subprocess.run(["pdftotext", "-layout", ruta, "-"], capture_output=True, text=True).stdout
        yield from out.splitlines()


def leer(ruta):
    articulos, actual = [], None
    for linea in lineas_del_pdf(ruta):
        if not linea.strip() or RUIDO.search(linea):
            continue
        m = FILA.match(linea.strip()) or FILA.match(linea)
        if m:
            actual = {"codigo": m.group(1), "nombre": re.sub(r"\s+", " ", m.group(2)).strip(),
                      "unidades": num(m.group(3)), "vr_unit": num(m.group(4)), "vr_total": num(m.group(5))}
            articulos.append(actual)
        elif actual and not re.search(NUM, linea):
            actual["nombre"] += " " + re.sub(r"\s+", " ", linea).strip()   # segunda línea del nombre
    return articulos


if __name__ == "__main__":
    origen = sys.argv[1] if len(sys.argv) > 1 else "INVENTARIO.pdf"
    destino = sys.argv[2] if len(sys.argv) > 2 else "syscafe_articulos.csv"
    arts = leer(origen)
    with open(destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["codigo", "nombre", "unidades", "vr_unit", "vr_total"])
        w.writeheader()
        w.writerows(arts)
    positivos = sum(1 for a in arts if a["unidades"] > 0)
    negativos = sum(1 for a in arts if a["unidades"] < 0)
    print(f"{len(arts)} artículos -> {destino}")
    print(f"  con existencias positivas: {positivos} | en cero: {len(arts) - positivos - negativos} | negativas: {negativos}")
    print(f"  suma de unidades: {sum(a['unidades'] for a in arts):,.2f}")
