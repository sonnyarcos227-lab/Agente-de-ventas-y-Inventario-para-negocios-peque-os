"""
datos_demo.py - Llena la base con 2 semanas de ventas SIMULADAS para mostrar el panel del dueño.

    py pruebas\\datos_demo.py

OJO: es para la presentación. Las ventas usan clientes ficticios y DESCUENTAN el inventario real
cargado de SysCafé (así se ven alertas de stock de verdad). Para volver a los datos reales de
la tienda, corre otra vez setup_db.bat.

Las ventas se hacen con las MISMAS funciones del agente (fn_crear_pedido, fn_agregar_item,
fn_confirmar_pedido...), así el kardex, el inventario y los reportes quedan coherentes. Después
solo se cambia la fecha para repartirlas en los últimos 14 días.
"""
import os
import random
import sys

import psycopg
from psycopg.rows import dict_row

HOST = os.getenv("DECORER_HOST", "localhost:5432")
ADMIN = os.getenv("DECORER_ADMIN_URL", f"postgresql://postgres:postgres@{HOST}/decorer")
random.seed(14)

CLIENTES = [("1000000101", "Cliente Demo Uno", "3000000101", "Centro"),
            ("1000000102", "Cliente Demo Dos", "3000000102", "José Homero"),
            ("1000000103", "Cliente Demo Tres", "3000000103", "Kennedy"),
            ("1000000104", "Cliente Demo Cuatro", "3000000104", "Olímpico"),
            ("1000000105", "Cliente Demo Cinco", "3000000105", "Las Américas"),
            ("1000000106", "Cliente Demo Seis", "3000000106", "San Agustín")]


def main():
    try:
        c = psycopg.connect(ADMIN, autocommit=True, row_factory=dict_row)
    except psycopg.OperationalError as e:
        sys.exit(f"No se pudo conectar a PostgreSQL: {e}")
    if c.execute("SELECT count(*) AS n FROM pedidos WHERE notas LIKE '%%DEMO%%'").fetchone()["n"]:
        sys.exit("Ya hay datos de demostración. Corre setup_db.bat para empezar de cero.")

    # productos con precio y con más de 1 unidad (para que quede algo después de vender)
    disponibles = c.execute("""SELECT p.id, p.nombre, p.precio, i.existencias FROM productos p
                               JOIN inventario i ON i.producto_id = p.id
                               WHERE p.activo AND p.precio IS NOT NULL AND i.existencias > 0 AND p.sku NOT LIKE 'PRUEBA-%%'
                               ORDER BY i.existencias DESC, p.precio DESC""").fetchall()
    if len(disponibles) < 5:
        sys.exit("No hay suficientes productos con existencias y precio.")
    ids_cliente = [c.execute("SELECT fn_registrar_cliente(%s,%s,%s,'Calle demo','Mocoa',%s,'urbana') AS id",
                             (d, n, t, b)).fetchone()["id"] for d, n, t, b in CLIENTES]

    ventas, separados, creditos = 0, 0, 0
    for dias_atras in range(13, -1, -1):
        for _ in range(random.choice([0, 1, 1, 2, 2, 3])):
            stock = {p["id"]: c.execute("SELECT existencias FROM inventario WHERE producto_id = %s", (p["id"],)).fetchone()["existencias"]
                     for p in disponibles}
            con_stock = [p for p in disponibles if stock[p["id"]] > 0]
            if not con_stock:
                break
            canal = random.choices(["presencial", "texto", "voz"], [5, 3, 2])[0]
            ped = c.execute("SELECT fn_crear_pedido(%s, %s, %s) AS id",
                            (random.choice(ids_cliente), canal, random.random() < 0.6)).fetchone()["id"]
            for p in random.sample(con_stock, k=min(len(con_stock), random.choice([1, 1, 2]))):
                c.execute("SELECT fn_agregar_item(%s, %s, 1)", (ped, p["id"]))
            quien = "vendedor" if canal == "presencial" else "agente"
            c.execute("SELECT fn_confirmar_pedido(%s, %s, %s)",
                      (ped, random.choices(["efectivo", "transferencia", "sistecredito", "addi"], [4, 4, 1, 1])[0]
                       if quien == "vendedor" else random.choice(["efectivo", "transferencia"]), quien))
            momento = f"now() - interval '{dias_atras} days' - interval '{random.randint(0, 6)} hours'"
            c.execute(f"UPDATE pedidos SET notas = 'DEMO', creado_en = {momento}, confirmado_en = {momento} WHERE id = %s", (ped,))
            c.execute(f"UPDATE ventas SET vendida_en = {momento} WHERE pedido_id = %s", (ped,))
            c.execute(f"UPDATE movimientos_stock SET creado_en = {momento} "
                      "WHERE referencia = (SELECT codigo FROM pedidos WHERE id = %s)", (ped,))
            if dias_atras > 3 and random.random() < 0.7:
                c.execute("UPDATE pedidos SET estado = 'entregado', entregado_en = confirmado_en + interval '2 days' "
                          "WHERE id = %s AND con_domicilio", (ped,))
            ventas += 1

    # un separado y una solicitud de crédito pendiente, para que el panel muestre esas tablas
    caro = next((p for p in disponibles if p["precio"] > 800000 and
                 c.execute("SELECT existencias FROM inventario WHERE producto_id = %s", (p["id"],)).fetchone()["existencias"] > 0), None)
    if caro:
        ped = c.execute("SELECT fn_crear_pedido(%s, 'texto', true) AS id", (ids_cliente[2],)).fetchone()["id"]
        c.execute("SELECT fn_agregar_item(%s, %s, 1)", (ped, caro["id"]))
        c.execute("SELECT fn_separar_pedido(%s, %s, 'transferencia', 'agente')", (ped, int(caro["precio"]) // 3))
        c.execute("UPDATE pedidos SET notas = 'DEMO' WHERE id = %s", (ped,))
        separados += 1
    otro = next((p for p in disponibles if p["precio"] > 500000 and
                 c.execute("SELECT existencias FROM inventario WHERE producto_id = %s", (p["id"],)).fetchone()["existencias"] > 0), None)
    if otro:
        ped = c.execute("SELECT fn_crear_pedido(%s, 'voz', true) AS id", (ids_cliente[4],)).fetchone()["id"]
        c.execute("SELECT fn_agregar_item(%s, %s, 1)", (ped, otro["id"]))
        c.execute("SELECT fn_solicitar_credito(%s, 'addi')", (ped,))
        creditos += 1

    tot = c.execute("SELECT count(*) AS n, coalesce(sum(total), 0) AS t FROM ventas WHERE NOT anulada").fetchone()
    alertas = c.execute("SELECT count(*) AS n FROM alertas_stock WHERE NOT atendida").fetchone()["n"]
    print(f"Listo: {ventas} ventas de demostración en 14 días (total ${int(tot['t']):,}), "
          f"{separados} separado, {creditos} crédito pendiente, {alertas} alertas de stock.".replace(",", "."))
    print("Abre http://localhost:8010/dueno  (clave: la de CLAVE_DUENO en backend\\.env, por defecto decorer2026)")
    c.close()


if __name__ == "__main__":
    main()
