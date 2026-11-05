-- =====================================================================
--  DECORER · 02_parametros_decorer.sql
--  Reglas del negocio confirmadas por la tienda + categorías.
--  Los productos se cargan desde SysCafé con importar\cargar_inventario.py
-- =====================================================================

-- valor NULL = Decorer todavía no lo ha definido -> el agente deriva a un asesor
INSERT INTO parametros(clave, valor, descripcion) VALUES
 ('domicilio_gratis_desde',    500000, 'Domicilio gratis en la zona urbana de Mocoa para compras desde este valor'),
 ('domicilio_urbano_mocoa',    NULL,   'POR CONFIRMAR: costo del domicilio urbano en compras de menos de $500.000'),
 ('dias_entrega',              NULL,   'POR CONFIRMAR: días para entregar un pedido con domicilio'),
 ('dias_cambio_inmediato',     7,      'Hasta este número de días se hace cambio inmediato en la tienda'),
 ('dias_retracto',             5,      'Ley 1480 art. 47: días hábiles de retracto en ventas a distancia o financiadas por la tienda'),
 ('garantia_legal_meses',      12,     'Ley 1480 art. 8: garantía de un producto nuevo cuando el fabricante no indica otra'),
 ('separado_abono_minimo_pct', NULL,   'POR CONFIRMAR: porcentaje mínimo del abono para separar'),
 ('separado_plazo_dias',       NULL,   'POR CONFIRMAR: días que se guarda un producto separado');

-- Las mismas familias del Drive de publicidad de Decorer, más las de SysCafé.
INSERT INTO categorias(nombre, descripcion) VALUES
 ('Salas',                'Salas en L, modulares, sofás, sofacamas, poltronas, puffs, mesas de centro y de TV'),
 ('Comedores',            'Comedores de 4 y 6 puestos (flor morado, importados, RH), bases y barras'),
 ('Sillas',               'Sillas de comedor, sillas sueltas, butacos y sillas plásticas'),
 ('Camas y colchones',    'Camas, bases cama, somieres, cabeceros, colchones, colchonetas y espumas'),
 ('Alcobas',              'Tocadores, coquetas, nocheros y cómodas'),
 ('Armarios y muebles',   'Armarios, clósets, zapateros, alacenas, bibliotecas, buffets y muebles auxiliares (Maderkit y RH)'),
 ('Oficina',              'Escritorios, sillas de oficina y archivadores'),
 ('Lencería',             'Sábanas, edredones, almohadas, cobijas, protectores, cojines y toallas'),
 ('Decoración',           'Alfombras, tapetes, espejos, lámparas, cuadros, jarrones, plantas y cortinas'),
 ('Electrodomésticos',    'Neveras, congeladores, lavadoras, estufas, hornos, aires acondicionados y ventiladores'),
 ('Cocina y pequeños electrodomésticos', 'Licuadoras, freidoras, planchas, ollas, sartenes, vajillas y menaje'),
 ('Tecnología',           'Televisores, celulares, computadores, tablets, parlantes y accesorios'),
 ('Otros',                'Artículos que no entran en las demás familias');

-- Clientes de PRUEBA (ficticios a propósito: los datos reales de clientes no salen de la tienda)
INSERT INTO clientes(documento, nombre, telefono, direccion, barrio, municipio, zona) VALUES
 ('1000000001','Cliente Prueba Uno',   '3000000001','Calle 1 # 1-01','Centro',      'Mocoa',      'urbana'),
 ('1000000002','Cliente Prueba Dos',   '3000000002','Carrera 2 # 2-02','José Homero','Mocoa',      'urbana'),
 ('1000000003','Cliente Prueba Tres',  '3000000003','Vereda Las Palmeras','',       'Mocoa',      'rural'),
 ('1000000004','Cliente Prueba Cuatro','3000000004','Calle 4 # 4-04','Centro',      'Villagarzón','urbana');
