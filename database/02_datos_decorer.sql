-- =====================================================================
--  DECORER · 02_datos_decorer.sql
--  Tienda de muebles y decoración en Mocoa, Putumayo (datos ficticios).
--  Precios en pesos colombianos (COP) con IVA incluido.
-- =====================================================================

INSERT INTO parametros(clave, valor, descripcion) VALUES
 ('domicilio_mocoa',            30000,   'Domicilio dentro del casco urbano de Mocoa'),
 ('domicilio_gratis_desde',     1500000, 'Compras desde este valor tienen domicilio gratis en Mocoa'),
 ('domicilio_otros_municipios', 90000,   'Domicilio a otros municipios del Putumayo'),
 ('dias_entrega',               3,       'Días hábiles para entregar un pedido con domicilio');

INSERT INTO categorias(nombre, descripcion) VALUES
 ('Salas',      'Sofás, salas en L, poltronas, sillones y mesas de centro'),
 ('Comedores',  'Comedores, sillas y barras'),
 ('Alcobas',    'Camas, colchones, clósets, mesas de noche y cómodas'),
 ('Oficina',    'Escritorios, sillas de oficina y bibliotecas'),
 ('Exterior',   'Muebles para terraza, balcón y patio'),
 ('Decoración', 'Espejos, lámparas, tapetes, cuadros, cojines y cortinas');

INSERT INTO proveedores(nombre, nit, ciudad, telefono, correo, tiempo_entrega_dias) VALUES
 ('Muebles del Valle S.A.S.',      '900111222-1', 'Cali',   '602 555 0101', 'ventas@mueblesdelvalle.test', 8),
 ('Maderas y Diseño Nariño',       '900333444-5', 'Pasto',  '602 555 0202', 'pedidos@maderasnarino.test',  6),
 ('Colchones Sueño Real',          '900555666-2', 'Bogotá', '601 555 0303', 'comercial@suenoreal.test',    10),
 ('Deco Hogar Importaciones',      '900777888-3', 'Bogotá', '601 555 0404', 'b2b@decohogar.test',          12),
 ('Taller Artesanal del Putumayo', '900999000-7', 'Mocoa',  '608 555 0505', 'taller@artesanal.test',       4);

-- ---------------------------------------------------------------------
-- Catálogo + inventario inicial
-- ---------------------------------------------------------------------
CREATE TEMP TABLE _catalogo (
    sku TEXT, nombre TEXT, categoria TEXT, proveedor TEXT, descripcion TEXT,
    material TEXT, color TEXT, ancho NUMERIC, fondo NUMERIC, alto NUMERIC,
    precio NUMERIC, costo NUMERIC, garantia INT, armado BOOLEAN,
    existencias INT, minimo INT, ubicacion TEXT
);

INSERT INTO _catalogo VALUES
-- SALAS
('SAL-001','Sofá 3 puestos Amazonas','Salas','Muebles del Valle S.A.S.','Sofá recto de 3 puestos con tela antifluidos y cojines de espuma de alta densidad','Estructura en pino, tela antifluidos','Gris oxford',210,90,85,1890000,1150000,12,false,6,2,'Exhibición'),
('SAL-002','Sofá cama Putumayo','Salas','Muebles del Valle S.A.S.','Sofá que se abre en cama doble con mecanismo de clic-clac','Estructura metálica, tela lino','Beige',190,95,88,1450000,880000,12,false,4,2,'Exhibición'),
('SAL-003','Sala en L Mocoa','Salas','Muebles del Valle S.A.S.','Sala esquinera de 5 puestos con chaise longue reversible','Estructura en pino, tela antifluidos','Azul petróleo',280,180,85,3290000,2050000,12,true,3,1,'Bodega'),
('SAL-004','Poltrona Orito','Salas','Maderas y Diseño Nariño','Poltrona individual con patas de madera y espaldar alto','Madera de pino, tela chenille','Mostaza',75,80,95,690000,390000,6,false,7,2,'Exhibición'),
('SAL-005','Sillón reclinable Sibundoy','Salas','Muebles del Valle S.A.S.','Sillón reclinable con reposapiés y 3 posiciones','Cuero sintético','Café',90,95,102,1250000,760000,12,false,1,1,'Exhibición'),
('SAL-006','Mesa de centro Caquetá','Salas','Maderas y Diseño Nariño','Mesa de centro rectangular con entrepaño inferior','Madera flor morado','Natural',110,60,45,420000,230000,6,true,9,3,'Exhibición'),
('SAL-007','Puff tejido Cocha','Salas','Taller Artesanal del Putumayo','Puff redondo tejido a mano, sirve de asiento o reposapiés','Fibra natural tejida','Crudo',50,50,40,180000,85000,3,false,12,4,'Exhibición'),
-- COMEDORES
('COM-001','Comedor 4 puestos Villagarzón','Comedores','Maderas y Diseño Nariño','Mesa rectangular y 4 sillas tapizadas','Madera de pino, tela antifluidos','Nogal y gris',120,80,76,1590000,960000,12,true,5,2,'Exhibición'),
('COM-002','Comedor 6 puestos Mocoa','Comedores','Maderas y Diseño Nariño','Mesa de 6 puestos con sillas de espaldar en listones','Madera flor morado','Natural',180,90,76,2690000,1650000,12,true,3,1,'Bodega'),
('COM-003','Silla de comedor Mandur','Comedores','Muebles del Valle S.A.S.','Silla individual tapizada, apilable','Madera de pino, tela antifluidos','Gris claro',45,50,90,210000,110000,6,false,20,6,'Bodega'),
('COM-004','Barra auxiliar con 2 butacos','Comedores','Deco Hogar Importaciones','Barra de cocina con dos butacos altos','MDF y metal','Blanco y negro',100,40,105,890000,520000,6,true,2,2,'Bodega'),
-- ALCOBAS
('ALC-001','Cama doble Descanso 140x190','Alcobas','Maderas y Diseño Nariño','Cama doble con cabecero tapizado (no incluye colchón)','Madera de pino, cabecero en tela','Gris',150,200,110,1190000,700000,12,true,6,2,'Bodega'),
('ALC-002','Cama sencilla Nido 100x190','Alcobas','Maderas y Diseño Nariño','Cama sencilla con cajón inferior (no incluye colchón)','Madera de pino','Blanco',110,200,90,690000,400000,12,true,5,2,'Bodega'),
('ALC-003','Base cama queen 160x200','Alcobas','Colchones Sueño Real','Base cama en madera tapizada, sin cabecero','Madera y tela','Gris oscuro',160,200,30,980000,590000,12,false,4,2,'Bodega'),
('ALC-004','Colchón semiortopédico doble 140x190','Alcobas','Colchones Sueño Real','Colchón de espuma de alta densidad, firmeza media','Espuma HR, tela jacquard','Blanco',140,190,25,840000,500000,24,false,8,3,'Bodega'),
('ALC-005','Colchón resortado queen 160x200','Alcobas','Colchones Sueño Real','Colchón de resortes pocket con pillow top','Resortes pocket, espuma','Blanco',160,200,30,1290000,780000,36,false,4,2,'Bodega'),
('ALC-006','Clóset 3 puertas Galeras','Alcobas','Muebles del Valle S.A.S.','Clóset con 3 puertas, 2 cajones y tubo para colgar','MDF','Roble claro',135,55,200,1390000,820000,12,true,3,1,'Bodega'),
('ALC-007','Mesa de noche Luna','Alcobas','Maderas y Diseño Nariño','Mesa de noche con un cajón y un entrepaño','Madera de pino','Nogal',45,40,55,260000,140000,6,false,10,4,'Exhibición'),
('ALC-008','Cómoda 5 cajones','Alcobas','Muebles del Valle S.A.S.','Cómoda alta con 5 cajones de rieles metálicos','MDF','Blanco',80,45,115,690000,410000,12,true,3,2,'Bodega'),
('ALC-009','Tocador con espejo Alba','Alcobas','Deco Hogar Importaciones','Tocador con espejo, cajón y butaco','MDF y espejo','Blanco',90,40,140,590000,340000,6,true,0,1,'Bodega'),
-- OFICINA
('OFI-001','Escritorio en L Trabajo','Oficina','Muebles del Valle S.A.S.','Escritorio esquinero con pasacables y repisa','MDF y metal','Negro y roble',140,120,75,690000,400000,6,true,4,2,'Exhibición'),
('OFI-002','Silla ergonómica Malla Pro','Oficina','Deco Hogar Importaciones','Silla de oficina con soporte lumbar y brazos ajustables','Malla, nylon y metal','Negro',62,60,120,549000,300000,12,false,6,3,'Exhibición'),
('OFI-003','Biblioteca 5 entrepaños','Oficina','Muebles del Valle S.A.S.','Biblioteca alta abierta de 5 niveles','MDF','Roble claro',80,30,180,380000,210000,6,true,5,2,'Bodega'),
-- EXTERIOR
('EXT-001','Juego de terraza Yurayaco 4 puestos','Exterior','Deco Hogar Importaciones','Sofá doble, 2 sillas y mesa de centro para exterior','Mimbre sintético y aluminio','Café',160,70,80,1790000,1080000,12,false,2,1,'Bodega'),
('EXT-002','Hamaca tejida del Putumayo','Exterior','Taller Artesanal del Putumayo','Hamaca tejida a mano para 1 persona, con cuerdas','Algodón tejido','Multicolor',150,0,220,220000,110000,3,false,10,3,'Exhibición'),
('EXT-003','Mecedora en madera Chontaduro','Exterior','Taller Artesanal del Putumayo','Mecedora clásica en madera maciza','Madera maciza','Natural',60,85,100,390000,210000,6,false,4,2,'Exhibición'),
-- DECORACIÓN
('DEC-001','Espejo redondo 80 cm','Decoración','Deco Hogar Importaciones','Espejo de pared con marco delgado metálico','Vidrio y metal','Dorado',80,3,80,260000,140000,3,false,7,2,'Exhibición'),
('DEC-002','Lámpara de pie Arco','Decoración','Deco Hogar Importaciones','Lámpara de pie tipo arco con pantalla de tela','Metal y tela','Negro',40,120,190,290000,160000,6,true,5,2,'Exhibición'),
('DEC-003','Tapete 160x230 Selva','Decoración','Deco Hogar Importaciones','Tapete de pelo corto con diseño de hojas','Polipropileno','Verde y crema',160,230,1,350000,180000,3,false,6,2,'Bodega'),
('DEC-004','Cuadro canvas Paisaje amazónico','Decoración','Taller Artesanal del Putumayo','Cuadro en lienzo con paisaje del piedemonte amazónico','Lienzo y bastidor de madera','Verde',90,3,60,150000,70000,3,false,8,2,'Exhibición'),
('DEC-005','Juego de 2 cojines tejidos','Decoración','Taller Artesanal del Putumayo','Dos cojines decorativos de 45x45 con relleno','Algodón tejido','Terracota',45,45,15,95000,42000,3,false,15,5,'Exhibición'),
('DEC-006','Cortina blackout 2 paños','Decoración','Deco Hogar Importaciones','Cortina que bloquea la luz, 2 paños de 140x220','Poliéster blackout','Gris',280,0,220,220000,115000,3,false,9,3,'Bodega');

INSERT INTO productos(sku, nombre, categoria_id, proveedor_id, descripcion_corta, material, color,
                      ancho_cm, fondo_cm, alto_cm, precio, costo, garantia_meses, requiere_armado)
SELECT k.sku, k.nombre, c.id, pr.id, k.descripcion, k.material, k.color,
       k.ancho, nullif(k.fondo, 0), k.alto, k.precio, k.costo, k.garantia, k.armado
FROM _catalogo k
JOIN categorias c   ON c.nombre = k.categoria
JOIN proveedores pr ON pr.nombre = k.proveedor;

INSERT INTO inventario(producto_id, existencias, stock_minimo, ubicacion)
SELECT p.id, k.existencias, k.minimo, k.ubicacion
FROM _catalogo k JOIN productos p ON p.sku = k.sku;

INSERT INTO movimientos_stock(producto_id, tipo, cantidad, existencias_antes, existencias_despues,
                              motivo, referencia, creado_en)
SELECT p.id, 'ajuste', k.existencias, 0, k.existencias, 'Inventario inicial', 'INV-INICIAL',
       now() - interval '35 days'
FROM _catalogo k JOIN productos p ON p.sku = k.sku
WHERE k.existencias > 0;

-- ---------------------------------------------------------------------
-- Promociones (una vigente por categoría, una por producto, una futura)
-- ---------------------------------------------------------------------
INSERT INTO promociones(nombre, porcentaje, categoria_id, producto_id, inicia, termina)
SELECT 'Mes del buen descanso: 15% en alcobas', 15, (SELECT id FROM categorias WHERE nombre = 'Alcobas'), NULL,
       date_trunc('month', current_date)::date, (date_trunc('month', current_date) + interval '1 month - 1 day')::date
UNION ALL
SELECT 'Comedor Mocoa con 10% de descuento', 10, NULL, (SELECT id FROM productos WHERE sku = 'COM-002'),
       current_date - 5, current_date + 40
UNION ALL
SELECT 'Black Friday Decorer: 20% en decoración', 20, (SELECT id FROM categorias WHERE nombre = 'Decoración'), NULL,
       DATE '2026-11-27', DATE '2026-11-30';

-- ---------------------------------------------------------------------
-- Clientes (ficticios)
-- ---------------------------------------------------------------------
INSERT INTO clientes(documento, nombre, telefono, direccion, municipio) VALUES
 ('1124000101','Marcela Jojoa',      '3105550101','Barrio José Homero, calle 9 # 4-21',   'Mocoa'),
 ('1124000102','Andrés Chindoy',     '3125550102','Barrio Olímpico, carrera 6 # 12-40',   'Mocoa'),
 ('1124000103','Luz Dary Benavides', '3145550103','Barrio Kennedy, calle 15 # 7-08',      'Mocoa'),
 ('1124000104','Jhon Fredy Ortiz',   '3165550104','Vereda San Antonio, finca El Paraíso', 'Villagarzón'),
 ('1124000105','Paola Andrea Muñoz', '3185550105','Barrio Centro, carrera 5 # 8-15',      'Mocoa'),
 ('1124000106','Carlos Jamioy',      '3205550106','Barrio La Esmeralda, calle 2 # 3-30',  'Mocoa'),
 ('1124000107','Diana Rosero',       '3215550107','Barrio Las Américas, manzana C casa 4','Puerto Asís'),
 ('1124000108','Hotel Piedemonte',   '3005550108','Vía al Fin del Mundo km 2',            'Mocoa');

-- ---------------------------------------------------------------------
-- Historial de ventas de las últimas 4 semanas.
-- Se crea con las MISMAS funciones que usará el agente, así el kardex,
-- las ventas y el inventario quedan consistentes. Luego se mueve la fecha.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    o RECORD; v_ped INTEGER; v_codigo TEXT; v_fecha TIMESTAMPTZ; item TEXT; v_sku TEXT; v_cant INT;
BEGIN
    FOR o IN SELECT * FROM (VALUES
        -- días atrás, documento cliente, canal, domicilio, pago, 'SKU:cantidad,...'
        (27,'1124000101','presencial',true ,'tarjeta',      'SAL-001:1,SAL-006:1'),
        (26,'1124000102','texto',     false,'nequi',        'DEC-005:2,DEC-004:1'),
        (24,'1124000108','presencial',true ,'transferencia','ALC-004:2,ALC-007:2,DEC-006:2'),
        (23,'1124000103','voz',       true ,'efectivo',     'COM-001:1'),
        (21,'1124000105','texto',     false,'daviplata',    'OFI-002:1'),
        (20,'1124000104','presencial',true ,'efectivo',     'EXT-002:2,EXT-003:1'),
        (18,'1124000106','voz',       false,'nequi',        'SAL-007:2'),
        (17,'1124000107','texto',     true ,'transferencia','ALC-002:1,ALC-004:1'),
        (15,'1124000101','texto',     false,'tarjeta',      'DEC-001:1,DEC-002:1'),
        (14,'1124000108','presencial',true ,'transferencia','COM-003:6,SAL-004:2'),
        (12,'1124000102','voz',       true ,'efectivo',     'SAL-002:1'),
        (11,'1124000103','texto',     false,'nequi',        'DEC-003:1,DEC-005:1'),
        (9 ,'1124000105','presencial',true ,'tarjeta',      'ALC-001:1,ALC-004:1,ALC-007:1'),
        (8 ,'1124000106','texto',     false,'daviplata',    'OFI-003:1'),
        (6 ,'1124000104','voz',       true ,'efectivo',     'COM-004:1'),
        (5 ,'1124000101','texto',     false,'nequi',        'SAL-007:1,DEC-004:1'),
        (4 ,'1124000107','presencial',true ,'tarjeta',      'ALC-006:1'),
        (3 ,'1124000102','voz',       false,'efectivo',     'EXT-002:1'),
        (2 ,'1124000103','texto',     true ,'transferencia','SAL-001:1'),
        (1 ,'1124000105','voz',       false,'nequi',        'DEC-001:1,DEC-005:1')
    ) AS t(dias, documento, canal, domicilio, pago, items)
    LOOP
        v_fecha := date_trunc('day', now()) - make_interval(days => o.dias) + interval '10 hours'
                   + make_interval(mins => (o.dias * 37) % 480);
        INSERT INTO pedidos(cliente_id, canal, con_domicilio, creado_en)
        VALUES ((SELECT id FROM clientes WHERE documento = o.documento), o.canal, o.domicilio, v_fecha)
        RETURNING id, codigo INTO v_ped, v_codigo;

        FOREACH item IN ARRAY string_to_array(o.items, ',') LOOP
            v_sku  := split_part(item, ':', 1);
            v_cant := split_part(item, ':', 2)::int;
            PERFORM fn_agregar_item(v_ped, (SELECT id FROM productos WHERE sku = v_sku), v_cant);
        END LOOP;

        PERFORM fn_confirmar_pedido(v_ped, o.pago,
                                    CASE WHEN o.canal = 'presencial' THEN 'vendedor' ELSE 'agente' END);

        UPDATE pedidos SET confirmado_en = v_fecha + interval '12 minutes',
                           entrega_programada = CASE WHEN con_domicilio THEN (v_fecha + interval '3 days')::date END,
                           estado = CASE WHEN o.dias > 3 AND con_domicilio THEN 'entregado' ELSE estado END
         WHERE id = v_ped;
        UPDATE ventas SET vendida_en = v_fecha + interval '12 minutes' WHERE pedido_id = v_ped;
        UPDATE movimientos_stock SET creado_en = v_fecha + interval '12 minutes' WHERE referencia = v_codigo;
    END LOOP;

    UPDATE alertas_stock SET creada_en = now() - interval '2 days' WHERE creada_en > now() - interval '1 minute';
END $$;

-- Un pedido cancelado (para probar que el stock regresa)
DO $$
DECLARE v_ped INTEGER;
BEGIN
    v_ped := fn_crear_pedido((SELECT id FROM clientes WHERE documento = '1124000106'), 'texto', false);
    PERFORM fn_agregar_item(v_ped, (SELECT id FROM productos WHERE sku = 'DEC-002'), 1);
    PERFORM fn_confirmar_pedido(v_ped, 'nequi');
    PERFORM fn_cancelar_pedido(v_ped, 'El cliente cambió de opinión');
END $$;

DROP TABLE _catalogo;
