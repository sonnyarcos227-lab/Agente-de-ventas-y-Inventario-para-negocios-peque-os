-- =====================================================================
--  DECORER · 04_reportes_y_seguridad.sql
--  Vistas de reportes para el dueño + usuario de base de datos del agente.
-- =====================================================================

-- Inventario con semáforo
CREATE VIEW v_inventario AS
SELECT p.id AS producto_id, p.sku, p.nombre, c.nombre AS categoria,
       i.existencias, i.stock_minimo, i.ubicacion,
       CASE WHEN i.existencias = 0 THEN 'agotado'
            WHEN i.existencias <= i.stock_minimo THEN 'bajo'
            ELSE 'ok' END AS estado,
       p.precio, i.existencias * p.costo AS valor_costo,
       pr.nombre AS proveedor, pr.tiempo_entrega_dias
FROM productos p
JOIN categorias c ON c.id = p.categoria_id
JOIN inventario i ON i.producto_id = p.id
LEFT JOIN proveedores pr ON pr.id = p.proveedor_id
WHERE p.activo;

-- Lo que hay que pedir al proveedor (sugiere llegar al doble del mínimo)
CREATE VIEW v_reabastecer AS
SELECT producto_id, sku, nombre, categoria, existencias, stock_minimo, estado, proveedor,
       tiempo_entrega_dias, greatest(stock_minimo * 2 - existencias, 1) AS cantidad_sugerida
FROM v_inventario v
WHERE estado <> 'ok'
  -- solo lo que de verdad se mueve: tenía saldo positivo en SysCafé o se vendió en los últimos 90 días
  -- (los artículos viejos agotados hace tiempo no son "por reabastecer")
  AND (EXISTS (SELECT 1 FROM inventario i WHERE i.producto_id = v.producto_id AND i.existencias_syscafe > 0)
       OR EXISTS (SELECT 1 FROM movimientos_stock m WHERE m.producto_id = v.producto_id
                  AND m.tipo IN ('salida','separado') AND m.creado_en > now() - interval '90 days'))
ORDER BY existencias, nombre;

-- Ventas válidas (sin anuladas) con su detalle
CREATE VIEW v_ventas_detalle AS
SELECT v.id AS venta_id, pe.codigo, v.vendida_en, (v.vendida_en AT TIME ZONE 'America/Bogota')::date AS dia,
       pe.canal, v.metodo_pago, v.registrada_por, cl.nombre AS cliente, cl.municipio,
       p.sku, p.nombre AS producto, c.nombre AS categoria, it.cantidad,
       it.precio_unitario, it.descuento_unitario, it.subtotal,
       it.cantidad * (it.precio_unitario - it.descuento_unitario - coalesce(p.costo, 0)) AS utilidad
FROM ventas v
JOIN pedidos pe ON pe.id = v.pedido_id
JOIN pedido_items it ON it.pedido_id = pe.id
JOIN productos p ON p.id = it.producto_id
JOIN categorias c ON c.id = p.categoria_id
LEFT JOIN clientes cl ON cl.id = pe.cliente_id
WHERE NOT v.anulada;

CREATE VIEW v_ventas_por_dia AS
SELECT (v.vendida_en AT TIME ZONE 'America/Bogota')::date AS dia,
       count(*) AS pedidos, sum(v.total) AS total_vendido, round(avg(v.total)) AS ticket_promedio
FROM ventas v WHERE NOT v.anulada
GROUP BY 1 ORDER BY 1;

CREATE VIEW v_productos_mas_vendidos AS
SELECT sku, producto, categoria, sum(cantidad) AS unidades, sum(subtotal) AS total_vendido,
       sum(utilidad) AS utilidad
FROM v_ventas_detalle GROUP BY sku, producto, categoria
ORDER BY unidades DESC, total_vendido DESC;

CREATE VIEW v_ventas_por_categoria AS
SELECT categoria, sum(cantidad) AS unidades, sum(subtotal) AS total_vendido, sum(utilidad) AS utilidad
FROM v_ventas_detalle GROUP BY categoria ORDER BY total_vendido DESC;

-- ¿Cuánto vende el agente por voz frente a texto y en tienda?
CREATE VIEW v_ventas_por_canal AS
SELECT pe.canal, count(*) AS pedidos, sum(v.total) AS total_vendido, round(avg(v.total)) AS ticket_promedio
FROM ventas v JOIN pedidos pe ON pe.id = v.pedido_id
WHERE NOT v.anulada GROUP BY pe.canal ORDER BY total_vendido DESC;

-- Kardex legible
CREATE VIEW v_kardex AS
SELECT m.creado_en, p.sku, p.nombre, m.tipo, m.cantidad, m.existencias_antes,
       m.existencias_despues, m.motivo, m.referencia, m.creado_por
FROM movimientos_stock m JOIN productos p ON p.id = m.producto_id
ORDER BY m.creado_en DESC, m.id DESC;

-- Conciliación con SysCafé: artículos cuyo saldo en SysCafé es negativo
-- (se vendió más de lo que se registró como entrada). Es una alerta para el dueño.
CREATE VIEW v_descuadre_syscafe AS
SELECT p.sku AS codigo_syscafe, p.nombre, c.nombre AS categoria, i.existencias_syscafe,
       i.existencias AS existencias_agente, i.fuente_existencias
FROM inventario i JOIN productos p ON p.id = i.producto_id JOIN categorias c ON c.id = p.categoria_id
WHERE i.existencias_syscafe < 0
ORDER BY i.existencias_syscafe;

-- Separados vigentes con su saldo
CREATE VIEW v_separados AS
SELECT pe.codigo, cl.nombre AS cliente, cl.telefono, pe.total, pe.abonado, pe.total - pe.abonado AS saldo,
       pe.separado_hasta, pe.creado_en
FROM pedidos pe LEFT JOIN clientes cl ON cl.id = pe.cliente_id
WHERE pe.estado = 'separado' ORDER BY pe.separado_hasta NULLS LAST;

-- Pedidos que esperan a un asesor (crédito, domicilio por cotizar)
CREATE VIEW v_pendientes_asesor AS
SELECT pe.codigo, pe.estado, cl.nombre AS cliente, cl.telefono, pe.total, pe.solicita_credito,
       pe.domicilio_por_confirmar, pe.notas, pe.creado_en
FROM pedidos pe LEFT JOIN clientes cl ON cl.id = pe.cliente_id
WHERE pe.estado IN ('borrador','confirmado','separado')
  AND pe.total > 0                                    -- un carrito vacío no es un pendiente
  AND (pe.solicita_credito IS NOT NULL OR pe.domicilio_por_confirmar)
ORDER BY pe.creado_en;

-- Desempeño del agente (para la evaluación del proyecto)
CREATE VIEW v_desempeno_agente AS
SELECT (creado_en AT TIME ZONE 'America/Bogota')::date AS dia, count(*) AS turnos,
       round(100.0 * avg(ok::int), 1) AS pct_exito,
       round(avg(ms_stt)) AS ms_stt, round(avg(ms_llm)) AS ms_llm,
       round(avg(ms_herramientas)) AS ms_herramientas, round(avg(ms_tts)) AS ms_tts,
       round(avg(coalesce(ms_stt,0) + coalesce(ms_llm,0) + coalesce(ms_herramientas,0) + coalesce(ms_tts,0))) AS ms_total
FROM agente_trazas GROUP BY 1 ORDER BY 1;

-- Reporte de un período (lo puede pedir el dueño por voz: "¿cómo nos fue esta semana?")
CREATE FUNCTION fn_reporte_ventas(p_desde DATE, p_hasta DATE DEFAULT current_date) RETURNS JSON
LANGUAGE sql STABLE AS $$
    SELECT json_build_object(
        'desde', p_desde, 'hasta', p_hasta,
        'pedidos', (SELECT count(DISTINCT venta_id) FROM v_ventas_detalle WHERE dia BETWEEN p_desde AND p_hasta),
        'total_vendido', (SELECT coalesce(sum(subtotal), 0) FROM v_ventas_detalle WHERE dia BETWEEN p_desde AND p_hasta),
        'utilidad', (SELECT coalesce(sum(utilidad), 0) FROM v_ventas_detalle WHERE dia BETWEEN p_desde AND p_hasta),
        'top_productos', (SELECT json_agg(t) FROM (
             SELECT producto, sum(cantidad) AS unidades, sum(subtotal) AS total
             FROM v_ventas_detalle WHERE dia BETWEEN p_desde AND p_hasta
             GROUP BY producto ORDER BY unidades DESC, total DESC LIMIT 5) t),
        'por_canal', (SELECT json_agg(t) FROM (
             SELECT canal, count(DISTINCT venta_id) AS pedidos, sum(subtotal) AS total
             FROM v_ventas_detalle WHERE dia BETWEEN p_desde AND p_hasta GROUP BY canal) t),
        'por_forma_de_pago', (SELECT json_agg(t) FROM (
             SELECT metodo_pago, count(DISTINCT venta_id) AS pedidos, sum(subtotal) AS total
             FROM v_ventas_detalle WHERE dia BETWEEN p_desde AND p_hasta GROUP BY metodo_pago) t),
        'separados_vigentes', (SELECT count(*) FROM v_separados),
        'productos_por_reabastecer', (SELECT count(*) FROM v_reabastecer));
$$;

-- =====================================================================
--  SEGURIDAD: principio de mínimo privilegio
--
--  agente_decorer  -> el backend del agente (lo que habla con el cliente)
--      LEE el catálogo y EJECUTA las funciones de venta. No puede hacer
--      UPDATE/DELETE directo: aunque el LLM "alucine" una orden, la base la rechaza.
--      Tampoco puede registrar entradas de mercancía, recibir abonos ni ver reportes.
--  dueno_decorer   -> panel del dueño / asesor: además puede todo lo anterior.
-- =====================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agente_decorer') THEN
        CREATE ROLE agente_decorer LOGIN PASSWORD 'decorer_agente_2026';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dueno_decorer') THEN
        CREATE ROLE dueno_decorer LOGIN PASSWORD 'decorer_dueno_2026';
    END IF;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM agente_decorer, dueno_decorer;
GRANT USAGE ON SCHEMA public TO agente_decorer, dueno_decorer;
GRANT SELECT ON categorias, productos, inventario, promociones, parametros, conocimiento, fotos_catalogo
      TO agente_decorer;
GRANT SELECT, INSERT ON conversaciones, mensajes, agente_trazas TO agente_decorer;
GRANT UPDATE (cliente_id, pedido_id) ON conversaciones TO agente_decorer;   -- solo esas dos columnas
GRANT UPDATE (ms_tts) ON agente_trazas TO agente_decorer;                   -- el tiempo de la voz se anota al final
GRANT USAGE ON SEQUENCE mensajes_id_seq, agente_trazas_id_seq TO agente_decorer;
-- El dueño lee todo (reportes, clientes, kardex), pero tampoco escribe directo.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dueno_decorer;

-- Las funciones que modifican datos corren con los permisos del dueño del esquema
-- (SECURITY DEFINER): así solo se cambian datos A TRAVÉS de ellas.
DO $$
DECLARE f TEXT;
BEGIN
    FOREACH f IN ARRAY ARRAY[
        'fn_registrar_cliente(text,text,text,text,text,text,text)',
        'fn_crear_pedido(integer,text,boolean)',
        'fn_actualizar_pedido(integer,integer,boolean)',
        'fn_agregar_item(integer,integer,integer)',
        'fn_descontar_inventario(integer,text,text,text)',
        'fn_confirmar_pedido(integer,text,text)',
        'fn_solicitar_credito(integer,text)',
        'fn_separar_pedido(integer,numeric,text,text)',
        'fn_registrar_abono(text,numeric,text,text)',
        'fn_cancelar_pedido(integer,text)',
        'fn_marcar_entregado(text)',
        'fn_entrada_inventario(integer,integer,text,text)',
        'fn_recalcular_pedido(integer)',
        'fn_resumen_pedido(integer)',
        'fn_estado_pedido(text,text)',
        'fn_consultar_cambio(text,text)',
        'fn_reporte_ventas(date,date)']
    LOOP
        EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = public, pg_temp', f);
    END LOOP;
END $$;

-- Funciones internas o solo del dueño: nadie más las ejecuta.
REVOKE EXECUTE ON FUNCTION
    fn_descontar_inventario(integer,text,text,text), fn_recalcular_pedido(integer),
    fn_registrar_abono(text,numeric,text,text), fn_marcar_entregado(text),
    fn_entrada_inventario(integer,integer,text,text), fn_reporte_ventas(date,date)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    fn_registrar_abono(text,numeric,text,text), fn_marcar_entregado(text),
    fn_entrada_inventario(integer,integer,text,text), fn_reporte_ventas(date,date)
TO dueno_decorer;
