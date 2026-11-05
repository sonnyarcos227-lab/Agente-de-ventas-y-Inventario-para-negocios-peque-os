"""
prueba_transacciones.py - Decorer
Comprueba que el inventario y el dinero estén protegidos. Las operaciones se hacen
con el MISMO usuario que usará el agente (agente_decorer); los abonos, con el del dueño.

Uso (con el contenedor pgvector encendido):
    py pruebas\\prueba_transacciones.py

Crea 4 artículos de prueba (códigos PRUEBA-*) y al final los desactiva,
así no aparecen en las búsquedas del agente.
"""

import os
import sys
import json
import time
import threading

import psycopg

if os.name == "nt":
    os.system("")   # activa los colores en la consola de Windows

HOST = os.getenv("DECORER_HOST", "localhost:5432")
ADMIN = os.getenv("DECORER_ADMIN_URL", f"postgresql://postgres:postgres@{HOST}/decorer")
AGENTE = os.getenv("DECORER_AGENTE_URL", f"postgresql://agente_decorer:decorer_agente_2026@{HOST}/decorer")
DUENO = os.getenv("DECORER_DUENO_URL", f"postgresql://dueno_decorer:decorer_dueno_2026@{HOST}/decorer")

OK, FALLA = "\033[92mOK\033[0m", "\033[91mFALLA\033[0m"
resultados = []

FIXTURES = [  # sku, nombre, precio, existencias, minimo
    ("PRUEBA-SOFA", "SOFA PRUEBA 3 PUESTOS", 1200000, 5, 1),
    ("PRUEBA-COJIN", "COJIN PRUEBA", 95000, 20, 2),
    ("PRUEBA-SILLON", "SILLON RECLINABLE PRUEBA", 1250000, 1, 1),
    ("PRUEBA-SINPRECIO", "MESA PRUEBA SIN PRECIO", None, 3, 1),
]


def check(nombre, condicion, detalle=""):
    resultados.append(bool(condicion))
    print(f"  [{OK if condicion else FALLA}] {nombre}" + (f"  ->  {detalle}" if detalle else ""))


def uno(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def falla_con(conn, sql, params, contiene):
    try:
        conn.execute(sql, params)
        return False, "¡lo permitió!"
    except psycopg.Error as e:
        msg = (e.diag.message_primary or str(e)) if hasattr(e, "diag") else str(e)
        return contiene.lower() in msg.lower() or contiene.lower() in (e.diag.message_hint or "").lower(), msg


def preparar(admin):
    cat = uno(admin, "SELECT id FROM categorias WHERE nombre = 'Otros'")
    with admin.transaction():
        admin.execute("SET LOCAL decorer.carga_masiva = 'on'")
        for sku, nombre, precio, stock, minimo in FIXTURES:
            pid = uno(admin, """INSERT INTO productos(sku, nombre, categoria_id, precio, activo)
                                VALUES (%s, %s, %s, %s, true)
                                ON CONFLICT (sku) DO UPDATE SET precio = EXCLUDED.precio, activo = true
                                RETURNING id""", (sku, nombre, cat, precio))
            admin.execute("""INSERT INTO inventario(producto_id, existencias, stock_minimo, fuente_existencias)
                             VALUES (%s, %s, %s, 'conteo_fisico')
                             ON CONFLICT (producto_id) DO UPDATE SET existencias = EXCLUDED.existencias,
                                                                     stock_minimo = EXCLUDED.stock_minimo""",
                          (pid, stock, minimo))


def limpiar(admin):
    admin.execute("UPDATE productos SET activo = false WHERE sku LIKE 'PRUEBA-%'")


def main():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
        agente = psycopg.connect(AGENTE, autocommit=True)
        dueno = psycopg.connect(DUENO, autocommit=True)
    except psycopg.OperationalError as e:
        print("No se pudo conectar a PostgreSQL. ¿Está encendido Docker y el contenedor pgvector?\n", e)
        sys.exit(1)

    preparar(admin)
    pid = {sku: uno(admin, "SELECT id FROM productos WHERE sku = %s", (sku,)) for sku, *_ in FIXTURES}
    stock = lambda sku: uno(admin, "SELECT existencias FROM inventario WHERE producto_id = %s", (pid[sku],))
    cliente = uno(agente, "SELECT fn_registrar_cliente('9999000001', 'Cliente de Prueba', '3000000000', "
                          "'Calle 1', 'Mocoa', 'Centro', 'urbana')")
    cliente_rural = uno(agente, "SELECT fn_registrar_cliente('9999000002', 'Cliente Rural', NULL, "
                                "'Vereda', 'Mocoa', NULL, 'rural')")

    try:
        # 1 ─────────────────────────────────────────────────────────────
        print("\n1. Mínimo privilegio")
        ok, msg = falla_con(agente, "UPDATE inventario SET existencias = 999", (), "permission denied")
        check("El agente no puede hacer UPDATE directo al inventario", ok or "permiso" in msg.lower(), "permiso denegado")
        ok, msg = falla_con(agente, "DELETE FROM ventas", (), "permission denied")
        check("El agente no puede borrar ventas", ok or "permiso" in msg.lower(), "permiso denegado")
        ok, msg = falla_con(agente, "SELECT fn_entrada_inventario(%s, 100)", (pid["PRUEBA-SOFA"],), "permission denied")
        check("El agente no puede meter mercancía al inventario (solo el dueño)", ok or "permiso" in msg.lower())

        # 2 ─────────────────────────────────────────────────────────────
        print("\n2. Venta con domicilio gratis (desde $500.000 en Mocoa urbano)")
        antes = stock("PRUEBA-SOFA")
        ped = uno(agente, "SELECT fn_crear_pedido(%s, 'voz', true)", (cliente,))
        r = uno(agente, "SELECT fn_agregar_item(%s, %s, 1)", (ped, pid["PRUEBA-SOFA"]))
        print(f"     Resumen que leería el agente: {r['codigo']} -> 1 x {r['items'][0]['producto']} "
              f"| total ${r['total']:,} | domicilio ${r['domicilio']:,}")
        check("Domicilio gratis porque supera $500.000", r["domicilio"] == 0 and not r["domicilio_por_confirmar"])
        check("Antes de confirmar el inventario no cambia", stock("PRUEBA-SOFA") == antes)
        uno(agente, "SELECT fn_confirmar_pedido(%s, 'transferencia')", (ped,))
        check("Al confirmar se descuenta el inventario", stock("PRUEBA-SOFA") == antes - 1, f"{antes} -> {stock('PRUEBA-SOFA')}")
        check("Queda una venta registrada", uno(admin, "SELECT count(*) FROM ventas WHERE pedido_id = %s", (ped,)) == 1)

        print("\n3. Domicilio de menos de $500.000 o fuera de la zona urbana")
        ped2 = uno(agente, "SELECT fn_crear_pedido(%s, 'texto', true)", (cliente,))
        r = uno(agente, "SELECT fn_agregar_item(%s, %s, 2)", (ped2, pid["PRUEBA-COJIN"]))
        check("Compra de $190.000: el domicilio queda por confirmar con un asesor",
              r["domicilio_por_confirmar"], f"le faltan ${r['falta_para_domicilio_gratis']:,} para el domicilio gratis")
        ped3 = uno(agente, "SELECT fn_crear_pedido(%s, 'texto', true)", (cliente_rural,))
        r = uno(agente, "SELECT fn_agregar_item(%s, %s, 1)", (ped3, pid["PRUEBA-SOFA"]))
        check("Zona rural: domicilio por confirmar aunque supere $500.000", r["domicilio_por_confirmar"])

        # 4 ─────────────────────────────────────────────────────────────
        print("\n4. Reglas de venta")
        ok, msg = falla_con(agente, "SELECT fn_agregar_item(%s, %s, 1)", (ped2, pid["PRUEBA-SINPRECIO"]), "precio")
        check("No vende un artículo sin precio registrado", ok, msg)
        ok, msg = falla_con(agente, "SELECT fn_agregar_item(%s, %s, 50)", (ped2, pid["PRUEBA-SOFA"]), "Solo hay")
        check("No deja pedir más de lo que hay", ok, msg)
        ok, msg = falla_con(agente, "SELECT fn_confirmar_pedido(%s, 'transferencia')", (ped,), "ya está")
        check("No deja confirmar dos veces", ok, msg)
        ok, msg = falla_con(agente, "SELECT fn_confirmar_pedido(%s, 'tarjeta')", (ped2,), "no válida")
        check("Rechaza formas de pago que Decorer no recibe", ok, msg)

        print("\n5. Crédito (Sistecrédito, Addi, crédito personal)")
        ok, msg = falla_con(agente, "SELECT fn_confirmar_pedido(%s, 'addi')", (ped2,), "credito_requiere_asesor")
        check("El agente no cierra ventas a crédito: las aprueba la entidad", ok, msg)
        r = uno(agente, "SELECT fn_solicitar_credito(%s, 'sistecredito')", (ped2,))
        check("Deja la solicitud anotada para el asesor", r["solicita_credito"] == "sistecredito")
        check("Aparece en pendientes del asesor",
              uno(dueno, "SELECT count(*) FROM v_pendientes_asesor WHERE codigo = %s", (r["codigo"],)) == 1)

        # 6 ─────────────────────────────────────────────────────────────
        print("\n6. Separado")
        antes_coj = stock("PRUEBA-COJIN")
        ped4 = uno(agente, "SELECT fn_crear_pedido(%s, 'texto', false)", (cliente,))
        uno(agente, "SELECT fn_agregar_item(%s, %s, 4)", (ped4, pid["PRUEBA-COJIN"]))   # 380.000
        r = uno(agente, "SELECT fn_separar_pedido(%s, 100000, 'efectivo')", (ped4,))
        check("Separa con un abono y aparta el producto", r["estado"] == "separado" and stock("PRUEBA-COJIN") == antes_coj - 4,
              f"abonado ${r['abonado']:,}, saldo ${r['saldo']:,}")
        check("Todavía no cuenta como venta", uno(admin, "SELECT count(*) FROM ventas WHERE pedido_id = %s", (ped4,)) == 0)
        ok, msg = falla_con(dueno, "SELECT fn_registrar_abono(%s, 999999, 'efectivo')", (r["codigo"],), "supera")
        check("No acepta un abono mayor que el saldo", ok, msg)
        r = uno(dueno, "SELECT fn_registrar_abono(%s, 280000, 'transferencia')", (r["codigo"],))
        check("Con el último abono se registra la venta", r["estado"] == "confirmado"
              and uno(admin, "SELECT metodo_pago FROM ventas WHERE pedido_id = %s", (ped4,)) == "separado")

        # 7 ─────────────────────────────────────────────────────────────
        print("\n7. Concurrencia: dos clientes, UNA sola unidad del sillón")
        pedidos = {}
        for nombre in ("A", "B"):
            p = uno(agente, "SELECT fn_crear_pedido(%s, 'voz')", (cliente,))
            uno(agente, "SELECT fn_agregar_item(%s, %s, 1)", (p, pid["PRUEBA-SILLON"]))   # los dos ven 1 disponible
            pedidos[nombre] = p

        alertas = []
        oyente = psycopg.connect(DUENO, autocommit=True)   # como el panel del dueño
        oyente.execute("LISTEN stock_bajo")

        def escuchar():
            for n in oyente.notifies(timeout=6):
                alertas.append(json.loads(n.payload))
                break
        hilo = threading.Thread(target=escuchar)
        hilo.start()

        salida = {}

        def comprar(nombre, pausa):
            c = psycopg.connect(AGENTE)
            t0 = time.perf_counter()
            try:
                with c.transaction():
                    c.execute("SELECT fn_confirmar_pedido(%s, 'efectivo')", (pedidos[nombre],))
                    time.sleep(pausa)   # A "se demora" con la fila bloqueada
                salida[nombre] = ("vendido", time.perf_counter() - t0)
            except psycopg.errors.RaiseException as e:
                salida[nombre] = (e.diag.message_primary, time.perf_counter() - t0)
            finally:
                c.close()

        hA = threading.Thread(target=comprar, args=("A", 1.5))
        hB = threading.Thread(target=comprar, args=("B", 0))
        hA.start(); time.sleep(0.2); hB.start()
        hA.join(); hB.join(); hilo.join()
        for n in ("A", "B"):
            print(f"     Cliente {n}: {salida[n][0]}  ({salida[n][1]:.2f} s)")
        check("Solo UNO de los dos se lleva el sillón", sum(r[0] == "vendido" for r in salida.values()) == 1)
        check("B esperó a que A terminara (FOR UPDATE) en vez de leer un dato viejo", salida["B"][1] > 1.0,
              f"esperó {salida['B'][1]:.2f} s")
        check("El inventario nunca queda negativo", stock("PRUEBA-SILLON") == 0)
        check("Llegó la alerta al dueño en vivo (NOTIFY stock_bajo)", bool(alertas),
              (alertas[0]["producto"] + " " + alertas[0]["estado"]) if alertas else "")
        oyente.close()

        # 8 ─────────────────────────────────────────────────────────────
        print("\n8. Cambios y cancelaciones")
        codigo = uno(admin, "SELECT codigo FROM pedidos WHERE id = %s", (ped,))
        r = uno(agente, "SELECT fn_consultar_cambio(%s, %s)", (codigo, "9999000001"))
        check("Compra de hoy: aplica cambio inmediato (hasta 7 días)", r["aplica_cambio_inmediato"],
              f"{r['dias_transcurridos']} días, venta a distancia: {r['venta_a_distancia']}")
        check("Sin el documento correcto no muestra el pedido de otro cliente",
              uno(agente, "SELECT fn_estado_pedido(%s, %s)", (codigo, "123")) is None)
        ganador = "A" if salida["A"][0] == "vendido" else "B"
        uno(agente, "SELECT fn_cancelar_pedido(%s, 'Prueba automática')", (pedidos[ganador],))
        check("Cancelar devuelve la unidad del sillón", stock("PRUEBA-SILLON") == 1)
        uno(agente, "SELECT fn_cancelar_pedido(%s, 'Prueba automática')", (ped,))
        check("Cancelar la venta del punto 2 devuelve el sofá", stock("PRUEBA-SOFA") == antes)
        for p in (pedidos["B" if ganador == "A" else "A"], ped2, ped3, ped4):
            uno(agente, "SELECT fn_cancelar_pedido(%s, 'Prueba automática')", (p,))
    finally:
        limpiar(admin)
        for c in (admin, agente, dueno):
            c.close()

    print(f"\nResultado: {sum(resultados)}/{len(resultados)} pruebas correctas")
    sys.exit(0 if all(resultados) else 1)


if __name__ == "__main__":
    main()
