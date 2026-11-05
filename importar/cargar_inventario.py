"""
cargar_inventario.py - Carga los artículos de SysCafé a la base de Decorer.

  py importar\\cargar_inventario.py
        [--articulos importar\\syscafe_articulos.csv]     (sale de leer_syscafe.py)
        [--lista-precios importar\\syscafe_precios.csv]  (sale de leer_precios_syscafe.py)
        [--ajustes   importar\\ajustes_decorer.csv]      (lo llenas tú: conteo físico y precios especiales)
        [--url postgresql://postgres:postgres@localhost:5432/decorer]

Qué hace:
  1. Clasifica cada artículo en una categoría (Salas, Comedores, Camas y colchones...)
     y saca línea, material, color y marca del nombre.
  2. Guarda el saldo de SysCafé tal cual (existencias_syscafe, puede ser negativo)
     y pone como existencias del agente el saldo positivo (o 0).
  3. Toma el precio de la lista de precios de SysCafé (los de menos de $1.000 son de relleno
     y quedan "por confirmar").
  4. Si ajustes_decorer.csv trae precio o conteo físico, manda sobre SysCafé.
Se puede correr cada mes con el inventario nuevo: actualiza sin duplicar.
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from pathlib import Path

import psycopg

AQUI = Path(__file__).resolve().parent


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# (categoría, línea, expresión regular sobre el nombre sin tildes). La primera que coincide gana.
REGLAS = [
    # combos y casos especiales primero
    ("Salas", "Juego de sala", r"^JUEGO (DE )?SALA|^MODULO SALA|^SOFAS\b"),
    ("Alcobas", "Juego de alcoba", r"^JUEGO (DE )?ALCOBA"),
    ("Salas", "Mesa de centro", r"^JUEGO DE MESAS? DE CENTRO"),
    ("Comedores", "Comedor", r"^JUEGO DE MESA"),
    ("Cocina y pequeños electrodomésticos", "Menaje", r"^JUEGO.*(OLLA|COPA|VASO|CUBIERTO|SENSACION)"),
    ("Comedores", "Cristal para mesa", r"^CRISTAL"),
    ("Tecnología", "Accesorios", r"^BASE (BRAZO|KALL|TV|FIJA)"),
    ("Camas y colchones", "Base cama", r"^BASE DESARMABLE|^SOMM?ER|^ESPALDAR"),
    ("Comedores", "Base de comedor",
     r"^BASE .*(COMEDOR|PTS|PUESTOS|FLOR MORADO|FOR MORADO|FL\.?M|IMITACION|CANOA|CLASICA|DUQUESA|HOLAND|LIBRO|MEDITERRANEA|MILLAN|SEMILLERO|ZAFIRO)"),
    ("Tecnología", "Computador", r"^TORRE .*(RYZEN|INTEL|CORE|GHZ)"),
    ("Tecnología", "Audio", r"^(EQUIPO|MINICOMPONENTE|MNICOMPONENTE|TEATRO|PROYECTOR)"),
    ("Electrodomésticos", "Nevera", r"^NEVARA"),
    ("Oficina", "Escritorio", r"^ESCRITIORIO"),
    ("Cocina y pequeños electrodomésticos", "Pequeño electrodoméstico", r"^(SECADOR|PROCESADOR|PICATODO|RAPIFRY|PANINI)"),
    ("Cocina y pequeños electrodomésticos", "Menaje", r"^(MOLDE|MUG|POSILLO|PORCELANA|LICORERA|MINITERMO|SARTE\b)"),
    ("Armarios y muebles", "Organizador", r"^(PERCHERO|ORGANIZADOR|MU.EQUERO|PAPELERA|PORTACEPILLO)"),
    ("Decoración", "Iluminación", r"^(BOMBILLO|LED\b)"),
    ("Otros", "Servicio", r"^(TAPIZADO|REFACCION|CAMBIO (COLOR|PATA)|FABRICACION|FAB\.)"),
    ("Otros", "Código interno", r"^(VARIOS|ELECTRODOMESTICOS VARIOS|SEPARADO)\b"),
    ("Alcobas", "Semanario", r"^SEMANARIO"),
    ("Armarios y muebles", "Armario", r"^(CLOSE\b|BAUL)"),
    ("Comedores", "Comedor", r"^COMEDO\b"),
    ("Tecnología", "Celular", r"^CELUAR"),
    ("Camas y colchones", "Cama", r"^CORRAL"),
    ("Electrodomésticos", "Estufa y horno", r"^CUBIERTA"),
    ("Cocina y pequeños electrodomésticos", "Pequeño electrodoméstico", r"^(BATI\b|ASADOR|COMBO B\+D)"),
    ("Cocina y pequeños electrodomésticos", "Menaje", r"^(CACER|CASEROLA|CUBIERTOS|COPAS|COMBO SARTEN)"),
    ("Salas", "Sofacama", r"\bSOFA ?CAMA|SOFACAMA"),
    ("Salas", "Sala en L", r"\bSALA (EN )?L\b|\bSALA L\b"),
    ("Salas", "Sala modular", r"\bMODULAR|\bSALA .*MODULO"),
    ("Salas", "Sala", r"^SALA\b"),
    ("Salas", "Sofá", r"^SOFA\b"),
    ("Salas", "Poltrona o sillón", r"^(POLTRONA|SILLON|RECLINO|RECLINABLE)"),
    ("Salas", "Puff", r"^PUFF?\b"),
    ("Salas", "Mesa de centro", r"^MESA (DE )?CENTRO"),
    ("Salas", "Mesa de TV", r"^MESA (DE )?T\.?V|CENTRO DE ENTRET"),
    ("Camas y colchones", "Colchón", r"^COLCHON(?!ETA)"),
    ("Camas y colchones", "Colchoneta", r"^COLCHONETA"),
    ("Camas y colchones", "Base cama", r"^BASE CAMA|^SOMIER|^CABECERO Y SOMIER"),
    ("Camas y colchones", "Cabecero", r"^CABECERO"),
    ("Camas y colchones", "Cama", r"^CAMA\b|^CAMAROTE|^LITERA"),
    ("Camas y colchones", "Espuma", r"^ESPUMA"),
    ("Alcobas", "Tocador", r"^TOCADOR|^COQUETA"),
    ("Alcobas", "Nochero", r"^NOCHERO|^MESA (DE )?NOCHE"),
    ("Alcobas", "Cómoda", r"^COMODA|^CAJONER"),
    ("Comedores", "Comedor", r"^COMEDOR"),
    ("Comedores", "Base de comedor", r"^BASE (PETALO|COPA|ITALIA|ESCANDINAVA|COMEDOR)"),
    ("Comedores", "Barra", r"^BARRA\b"),
    ("Sillas", "Butaco", r"^BUTACO"),
    ("Oficina", "Silla de oficina", r"^SILLA.*(OFICINA|ERGONOM|GERENT|GAMER|SECRETAR|EJECUTIV|INTERLOCUTORA)"),
    ("Sillas", "Silla", r"^SILLAS?\b"),
    ("Oficina", "Escritorio", r"^ESCRITO"),
    ("Oficina", "Archivador", r"^ARCHIVADOR"),
    ("Armarios y muebles", "Armario", r"^(ARMARIO|CLOSET|GUARDAROPA)"),
    ("Armarios y muebles", "Zapatero", r"^ZAPATERO"),
    ("Armarios y muebles", "Cocina", r"^(ALACENA|MUEBLE (DE )?COCINA|MUEBLE CNA|AUXILIAR COCINA|TORRE DE HORNOS)"),
    ("Armarios y muebles", "Biblioteca", r"^(BIBLIOTECA|ESTANTE|REPISA)"),
    ("Armarios y muebles", "Buffet", r"^(BUFFE|BIFE|BIFET|VITRINERO)"),
    ("Armarios y muebles", "Mueble auxiliar", r"^(MUEBLE|GABINETE|PRACTIMUEBLE|MULTIORGANIZADOR|CENTRO DE COMPUTO)"),
    ("Comedores", "Mesa", r"^MESA\b"),
    ("Lencería", "Ropa de cama", r"^(SABANA|EDREDON|COBIJA|COBERTOR|CUBRELECHO|PROTECTOR|CUBRECOLCHON|PIE DE CAMA)"),
    ("Lencería", "Almohada", r"^ALMOHADA"),
    ("Lencería", "Cojín", r"^COJIN"),
    ("Lencería", "Toalla", r"^TOALLA"),
    ("Decoración", "Alfombra", r"^(ALFOMBRA|ALFOMRA|TAPETE)"),
    ("Decoración", "Espejo", r"^ESPEJO"),
    ("Decoración", "Lámpara", r"^LAMPARA"),
    ("Decoración", "Decorativo", r"^(CUADRO|JARRON|MATERA|FLOR|FLORES|FLORERO|PLANTA|CORTINA|CESTA|DECO|RENO|RELOJ DE PARED|PORTARRETRATO|VELA)"),
    ("Electrodomésticos", "Nevera", r"^(NEVERA|NEVECON|REFRIGERADOR)"),
    ("Electrodomésticos", "Congelador", r"^(CONGELADOR|VITRINA)"),
    ("Electrodomésticos", "Lavadora", r"^(LAVADORA|LAV\b|SECADORA|CENTRIFUGA)"),
    ("Electrodomésticos", "Estufa y horno", r"^(ESTUFA|HORNO|CAMPANA|COCINETA)"),
    ("Electrodomésticos", "Aire acondicionado", r"^AIRE"),
    ("Electrodomésticos", "Ventilador", r"^(VENTILADOR|ENFRIADOR|TORRE C)"),
    ("Electrodomésticos", "Otros electrodomésticos", r"^(DISPENSADOR|ASPIRADORA|HIDROLAVADORA|EXTRACTOR|CALENTADOR|MAQUINA)"),
    ("Cocina y pequeños electrodomésticos", "Pequeño electrodoméstico",
     r"^(LICUADORA|FREIDORA|PLANCHA|SANDUCHERA|CAFETERA|WAFLERA|MOLINO|CORTADORA|BATIDORA|OLLA ARROCERA|ARROCERA|EXPRIMIDOR|TOSTADORA|ACCESORIO EASY)"),
    ("Cocina y pequeños electrodomésticos", "Menaje",
     r"^(OLLA|SARTEN|CALDERO|BATERIA (DE )?COCINA|BATERIA\b(?!.*(CEL|LITIO))|VAJILLA|WOK|CACEROLA|CUCHILL|JARRA|VASO|TERMO|LONCHERA|SET|JUEGO DE (OLLAS|VASOS|CUBIERTOS|COPAS))"),
    ("Tecnología", "Televisor", r"^(TELEVISOR|TV\b|SMART TV)"),
    ("Tecnología", "Celular", r"^(CELULAR|CEL\b|SMARTPHONE)"),
    ("Tecnología", "Computador", r"^(COMPUTADOR|PORTATIL|PORT\b|TABLET|IMPRESORA|TODO EN UNO)"),
    ("Tecnología", "Audio", r"^(PARLANTE|ALTAVOZ|AUDIFONO|TORRE DE SONIDO|BARRA DE SONIDO|MICROFONO|EQUIPO DE SONIDO)"),
    ("Tecnología", "Accesorios", r"^(ANTENA|BASE KALLEY|BASE TV|SOPORTE|DVD|CONSOLA|CAMARA|RELOJ|SMARTWATCH)"),
]

MATERIALES = ["FLOR MORADO", "MICROCUERO", "CUERINA", "CUERO", "PRANNA", "CHENILLE", "LINO", "TELA",
              "MADERA", "RH", "MDF", "METALICO", "METALICA", "VIDRIO", "CRISTAL", "MIMBRE", "FIQUE",
              "POLIPROPI", "ALUMINIO", "ACERO"]
COLORES = ["WENGUE", "CARAMELO", "NIEBLA", "GALES", "ROVERE", "CENIZA", "DUNA", "NOGAL",
           "BLANCO", "BLANCA", "NEGRO", "NEGRA", "GRIS", "AZUL", "VERDE", "ROJO", "ROJA", "ROSA",
           "BEIGE", "CAFE", "MIEL", "PALO ROSA", "MOSTAZA", "VINOTINTO", "PLATA", "SILVER", "NATURAL"]
MARCAS = ["KALLEY", "LG", "SAMSUNG", "MIDEA", "HISENSE", "ELECTROLUX", "WHIRLPOOL", "MABE", "HACEB",
          "CHALLENGER", "IMUSA", "B&D", "BLACK+DECKER", "OSTER", "JBL", "SAMURAI", "UNIVERSAL", "XIAOMI",
          "MOTOROLA", "HONOR", "OPPO", "TECNO", "INFINIX", "LENOVO", "HP", "ASUS", "ACER", "PANASONIC",
          "SONY", "TCL", "CAIXUN", "MADERKIT", "ROMANCE", "SURCANO", "CASSATA", "SPRING", "NUBELANDIA",
          "STAR COLLECTION", "JLC", "INDUSEL", "ABBA", "ARTIC", "TV TALENT", "CARPET & HOME"]


def clasificar(nombre: str):
    n = sin_tildes(nombre.upper()).strip()
    for categoria, linea, patron in REGLAS:
        if re.search(patron, n):
            return categoria, linea
    return "Otros", None


def extraer(lista, nombre):
    n = " " + sin_tildes(nombre.upper()) + " "
    encontrados = [x for x in lista if re.search(r"[\s/(\-]" + re.escape(x) + r"[\s/)\-.,]", n)]
    return ", ".join(x.title() if len(x) > 3 else x for x in encontrados) or None


# Palabras que no identifican un modelo (sirven para cualquier mueble)
GENERICAS = set("""SALA SALAS EN L SOFA SOFAS CAMA CAMAS SOFACAMA COMEDOR COMEDORES FLOR MORADO PTS PUESTOS Y SILLAS SILLA BASE
MESA TV DE NOCHE ARMARIO ESCRITORIO MUEBLE COCINA AUXILIAR CENTRO COMPUTO ENTRET MODULOS MODULO PEQUENA PEQUENO GRANDE
IMPORTADO IMPORTADOS CON PARA LA EL TAPA MADERA VIDRIO GRISES GRIS NEGRO NEGRA BLANCO BLANCA NATURAL WENGUE CARAMELO
NIEBLA GALES ROVERE CENIZA DUNA SUP INF DER PRIME BIBLIO ESCRIT EXT INFANTIL NINA NINO FOTOS MT M CM PATA RH TELA""".split())


def _tokens(texto):
    t = re.sub(r"[^A-Z0-9 ]", " ", sin_tildes(texto.upper()))
    return {w for w in t.split() if w not in GENERICAS and not re.fullmatch(r"\d+([.]\d+)?M?", w) and len(w) > 2}


SALAS_LINEAS = {"Sala", "Sala en L", "Sala modular", "Sofá", "Sofacama", "Juego de sala", "Poltrona o sillón"}


def _mismo_tipo(linea_modelo, linea_producto):
    if linea_modelo in SALAS_LINEAS:
        return linea_producto in SALAS_LINEAS
    return linea_modelo is not None and linea_modelo == linea_producto


def cruzar_fotos(conn):
    """Carga el catálogo de fotos del Drive y le pone foto a un producto SOLO si su nombre trae el nombre
    propio del modelo (ROMA, KIOTO, ESCANDINAVA, KRONOS...) y es de la misma familia. Mejor sin foto que con una equivocada."""
    ruta = AQUI / "drive_modelos.csv"
    if not ruta.exists():
        return 0, 0
    modelos = [r for r in leer_csv(ruta) if r["carpeta"] != "LOGO" and "(fotos)" not in r["modelo"]]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fotos_catalogo")
        for m in modelos:
            cur.execute("INSERT INTO fotos_catalogo(carpeta, modelo, drive_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (m["carpeta"], m["modelo"], m["drive_id"]))
        productos = cur.execute("SELECT id, nombre, linea FROM productos WHERE activo").fetchall()
        cur.execute("UPDATE productos SET drive_id = NULL")
        info = [(m, _tokens(m["modelo"]), clasificar(m["modelo"])[1]) for m in modelos]
        n = 0
        for pid, nombre, linea in productos:
            tp = _tokens(nombre)
            mejor = None
            for m, tm, linea_m in info:
                if tm and tm <= tp and _mismo_tipo(linea_m, linea) and (mejor is None or len(tm) > len(mejor[0])):
                    mejor = (tm, m["drive_id"])
            if mejor:
                cur.execute("UPDATE productos SET drive_id = %s WHERE id = %s", (mejor[1], pid))
                n += 1
    conn.commit()
    return len(modelos), n


def leer_csv(ruta):
    if not ruta or not Path(ruta).exists():
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        muestra = f.read(4096)
        f.seek(0)
        # Excel en español guarda los CSV con punto y coma
        delim = ";" if muestra.count(";") > muestra.count(",") else ","
        return list(csv.DictReader(f, delimiter=delim))


def numero(v):
    v = (v or "").strip().replace("$", "").replace(".", "").replace(",", "").replace(" ", "")
    return int(v) if v.isdigit() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articulos", default=str(AQUI / "syscafe_articulos.csv"))
    ap.add_argument("--lista-precios", default=str(AQUI / "syscafe_precios.csv"))
    ap.add_argument("--ajustes", default=str(AQUI / "ajustes_decorer.csv"))
    ap.add_argument("--url", default=os.getenv("DECORER_ADMIN_URL",
                                               "postgresql://postgres:postgres@localhost:5432/decorer"))
    a = ap.parse_args()

    articulos = {r["codigo"].strip().zfill(5): r for r in leer_csv(a.articulos)}
    if not articulos:
        sys.exit(f"No encontré {a.articulos}. Primero corre: py importar\\leer_syscafe.py INVENTARIO.pdf")
    lista = {r["codigo"].strip().zfill(5): r for r in leer_csv(a.lista_precios)}
    manual = {r["codigo"].strip().zfill(5): r for r in leer_csv(a.ajustes)
              if (r.get("codigo") or "").strip()
              and any((r.get(k) or "").strip() for k in ("precio_venta", "existencias_reales", "stock_minimo"))}

    filas, sin_precio, placeholder = [], 0, 0
    # todos los códigos: los del inventario y los que solo están en la lista de precios (se piden por encargo)
    for cod in sorted(set(articulos) | set(lista)):
        inv, lp, m = articulos.get(cod), lista.get(cod), manual.get(cod, {})
        nombre = re.sub(r"\s+", " ", (inv or lp).get("nombre") or (inv or lp).get("detalle")).strip()
        if lp:   # la lista de precios trae el nombre completo; el inventario a veces lo corta
            completo = re.sub(r"\s+", " ", lp["detalle"]).strip()
            completo = re.sub(r"\b(\w+) \1$", r"\1", completo)      # "ARMONIA ARMONIA" -> "ARMONIA"
            if completo.replace(" ", "").startswith(nombre.replace(" ", "")) or not inv:
                nombre = completo
        cat, linea = clasificar(nombre)
        saldo = float(inv["unidades"]) if inv and inv.get("unidades") not in (None, "") else None
        precio = numero(m.get("precio_venta"))
        if precio is None and lp:
            precio = int(lp["precio"])
            if precio < 1000:          # en SysCafé hay precios de $1 o $10 de relleno: no son reales
                precio, placeholder = None, placeholder + 1
        if precio is None:
            sin_precio += 1
        conteo = numero(m.get("existencias_reales"))
        minimo = numero(m.get("stock_minimo"))
        filas.append(dict(
            sku=cod, nombre=nombre, categoria=cat, linea=linea,
            material=extraer(MATERIALES, nombre), color=extraer(COLORES, nombre), marca=extraer(MARCAS, nombre),
            precio=precio, saldo=saldo,
            existencias=conteo if conteo is not None else max(int(saldo or 0), 0),
            fuente="conteo_fisico" if conteo is not None else "syscafe",
            minimo=minimo if minimo is not None else 1,
            activo=linea not in ("Servicio", "Código interno")))

    with psycopg.connect(a.url) as conn:
        cats = dict(conn.execute("SELECT nombre, id FROM categorias").fetchall())
        with conn.cursor() as cur:
            cur.execute("SET LOCAL decorer.carga_masiva = 'on'")
            for f in filas:
                cur.execute("""
                    INSERT INTO productos(sku, codigo_syscafe, nombre, categoria_id, linea, material, color, marca, precio, activo)
                    VALUES (%(sku)s, %(sku)s, %(nombre)s, %(cat)s, %(linea)s, %(material)s, %(color)s, %(marca)s, %(precio)s, %(activo)s)
                    ON CONFLICT (sku) DO UPDATE SET
                        nombre = EXCLUDED.nombre, categoria_id = EXCLUDED.categoria_id, linea = EXCLUDED.linea,
                        material = EXCLUDED.material, color = EXCLUDED.color, marca = EXCLUDED.marca,
                        precio = coalesce(EXCLUDED.precio, productos.precio),
                        activo = EXCLUDED.activo
                    RETURNING id""", {**f, "cat": cats[f["categoria"]]})
                pid = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO inventario(producto_id, existencias, stock_minimo, existencias_syscafe, fuente_existencias)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (producto_id) DO UPDATE SET
                        existencias_syscafe = EXCLUDED.existencias_syscafe,
                        stock_minimo = EXCLUDED.stock_minimo,
                        -- un conteo físico manda; el saldo de SysCafé solo se usa si el agente aún no ha movido el producto
                        existencias = CASE WHEN EXCLUDED.fuente_existencias = 'conteo_fisico'
                                             OR inventario.fuente_existencias = 'syscafe'
                                           THEN EXCLUDED.existencias ELSE inventario.existencias END,
                        fuente_existencias = CASE WHEN EXCLUDED.fuente_existencias = 'conteo_fisico'
                                                  THEN 'conteo_fisico' ELSE inventario.fuente_existencias END""",
                            (pid, f["existencias"], f["minimo"], f["saldo"], f["fuente"]))
                if f["existencias"] > 0:
                    cur.execute("""
                        INSERT INTO movimientos_stock(producto_id, tipo, cantidad, existencias_antes, existencias_despues,
                                                      motivo, referencia, creado_por)
                        SELECT %s, 'ajuste', %s, 0, %s, %s, 'SYSCAFE-CARGA', 'importador'
                        WHERE NOT EXISTS (SELECT 1 FROM movimientos_stock WHERE producto_id = %s)""",
                                (pid, f["existencias"], f["existencias"],
                                 "Conteo físico" if f["fuente"] == "conteo_fisico" else "Saldo inicial SysCafé", pid))
        conn.commit()

        resumen = conn.execute("""
            SELECT c.nombre, count(*), count(*) FILTER (WHERE i.existencias > 0), count(*) FILTER (WHERE p.precio IS NOT NULL)
            FROM productos p JOIN categorias c ON c.id = p.categoria_id JOIN inventario i ON i.producto_id = p.id
            GROUP BY c.nombre ORDER BY count(*) DESC""").fetchall()
        neg = conn.execute("SELECT count(*), coalesce(sum(existencias_syscafe), 0) FROM inventario WHERE existencias_syscafe < 0").fetchone()
        n_fotos, con_foto = cruzar_fotos(conn)

    print(f"{len(filas)} artículos cargados: {len(articulos)} del inventario y "
          f"{len(set(lista) - set(articulos))} que solo están en la lista de precios")
    print(f"  Precios: {len(filas) - sin_precio} con precio, {sin_precio} sin precio "
          f"({placeholder} tenían un precio de relleno de menos de $1.000 en SysCafé)")
    print(f"  ajustes_decorer.csv: {len(manual)} filas con datos (un precio o conteo escrito ahí manda sobre SysCafé)\n")
    print(f"  {'Categoría':40} {'Artículos':>9} {'Con stock':>9} {'Con precio':>10}")
    for nombre, total, stock, precio in resumen:
        print(f"  {nombre:40} {total:>9} {stock:>9} {precio:>10}")
    print(f"\n  Fotos: {n_fotos} modelos del Drive en el catálogo de fotos; {con_foto} productos con su foto (cruce estricto)")
    print(f"  Descuadre SysCafé: {neg[0]} artículos con saldo negativo (suma {neg[1]:,.0f} unidades).")
    print("  Míralos con: SELECT * FROM v_descuadre_syscafe;")


if __name__ == "__main__":
    main()
