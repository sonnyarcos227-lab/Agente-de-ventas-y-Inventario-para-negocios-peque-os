-- =====================================================================
--  DECORER · Agente de ventas e inventario
--  01_esquema.sql  -  Datos transaccionales (PostgreSQL)
--
--  Regla de oro del proyecto:
--    El LLM NUNCA escribe SQL ni toca tablas. Solo llama funciones
--    fn_* que validan, calculan el dinero y protegen el inventario.
--    El usuario de la base del agente (agente_decorer) solo puede
--    ejecutar esas funciones y leer el catálogo.
--
--  Adaptado a cómo trabaja Decorer (Mocoa):
--    - los artículos vienen de SysCafé (codigo_syscafe)
--    - pagos: efectivo, transferencia, Sistecrédito, Addi, crédito personal
--    - sistema de separado con abonos
--    - domicilio en la zona urbana de Mocoa, gratis desde $500.000
--    - un artículo sin precio registrado no se vende por el agente:
--      lo confirma un asesor
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector (conocimiento, script 03)
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- búsqueda tolerante a errores ("sofa" ~ "sofá")
CREATE EXTENSION IF NOT EXISTS unaccent;   -- quitar tildes al buscar

-- ---------------------------------------------------------------------
-- Parámetros del negocio (el dinero se calcula aquí, no en el LLM).
-- valor NULL = dato que Decorer aún no ha confirmado: el agente lo deriva a un asesor.
-- ---------------------------------------------------------------------
CREATE TABLE parametros (
    clave       TEXT PRIMARY KEY,
    valor       NUMERIC,
    descripcion TEXT
);

-- ---------------------------------------------------------------------
-- Catálogo
-- ---------------------------------------------------------------------
CREATE TABLE categorias (
    id          SERIAL PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE,
    descripcion TEXT
);

CREATE TABLE proveedores (
    id                  SERIAL PRIMARY KEY,
    nombre              TEXT NOT NULL UNIQUE,
    nit                 TEXT UNIQUE,
    ciudad              TEXT,
    telefono            TEXT,
    correo              TEXT,
    tiempo_entrega_dias INTEGER CHECK (tiempo_entrega_dias > 0)
);

CREATE TABLE productos (
    id                SERIAL PRIMARY KEY,
    sku               TEXT NOT NULL UNIQUE,          -- = código de SysCafé
    codigo_syscafe    TEXT UNIQUE,
    nombre            TEXT NOT NULL,
    categoria_id      INTEGER NOT NULL REFERENCES categorias(id),
    linea             TEXT,                          -- subtipo: sofacama, sala en L, colchón...
    proveedor_id      INTEGER REFERENCES proveedores(id),
    marca             TEXT,
    descripcion_corta TEXT,
    material          TEXT,
    color             TEXT,
    ancho_cm          NUMERIC(6,1),
    fondo_cm          NUMERIC(6,1),
    alto_cm           NUMERIC(6,1),
    precio            NUMERIC(12,0) CHECK (precio IS NULL OR precio > 0),   -- COP, precio final al público (Decorer no cobra IVA por ahora). NULL = por confirmar
    costo             NUMERIC(12,0) CHECK (costo >= 0),
    garantia_meses    INTEGER,                       -- NULL = la del fabricante (por ley, 12 meses si no la indica)
    requiere_armado   BOOLEAN NOT NULL DEFAULT false,
    activo            BOOLEAN NOT NULL DEFAULT true,
    drive_id          TEXT,                          -- foto en el Drive de publicidad
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_productos_categoria ON productos(categoria_id);
CREATE INDEX idx_productos_nombre_trgm ON productos USING gin (lower(nombre) gin_trgm_ops);

-- Inventario: una fila por producto. Solo lo cambian las funciones fn_*.
CREATE TABLE inventario (
    producto_id         INTEGER PRIMARY KEY REFERENCES productos(id),
    existencias         INTEGER NOT NULL DEFAULT 0 CHECK (existencias >= 0),  -- nunca negativo
    stock_minimo        INTEGER NOT NULL DEFAULT 1 CHECK (stock_minimo >= 0),
    ubicacion           TEXT NOT NULL DEFAULT 'Almacén',
    existencias_syscafe NUMERIC,            -- saldo tal como lo reporta SysCafé (puede ser negativo)
    fuente_existencias  TEXT NOT NULL DEFAULT 'syscafe' CHECK (fuente_existencias IN ('syscafe','conteo_fisico','sistema')),
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Kardex: cada unidad que entra o sale deja rastro.
CREATE TABLE movimientos_stock (
    id                  BIGSERIAL PRIMARY KEY,
    producto_id         INTEGER NOT NULL REFERENCES productos(id),
    tipo                TEXT NOT NULL CHECK (tipo IN ('entrada','salida','devolucion','ajuste','separado')),
    cantidad            INTEGER NOT NULL CHECK (cantidad <> 0),   -- + entra, - sale
    existencias_antes   INTEGER NOT NULL,
    existencias_despues INTEGER NOT NULL,
    motivo              TEXT,
    referencia          TEXT,          -- código de pedido o factura del proveedor
    creado_por          TEXT NOT NULL DEFAULT 'sistema',
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_mov_producto ON movimientos_stock(producto_id, creado_en);

CREATE TABLE alertas_stock (
    id           BIGSERIAL PRIMARY KEY,
    producto_id  INTEGER NOT NULL REFERENCES productos(id),
    existencias  INTEGER NOT NULL,
    stock_minimo INTEGER NOT NULL,
    atendida     BOOLEAN NOT NULL DEFAULT false,
    creada_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Promociones: el descuento se CALCULA aquí; el texto de las condiciones
-- se indexa en pgvector para que el agente las explique.
CREATE TABLE promociones (
    id           SERIAL PRIMARY KEY,
    nombre       TEXT NOT NULL,
    porcentaje   NUMERIC(5,2) NOT NULL CHECK (porcentaje > 0 AND porcentaje <= 50),
    categoria_id INTEGER REFERENCES categorias(id),
    producto_id  INTEGER REFERENCES productos(id),
    inicia       DATE NOT NULL,
    termina      DATE NOT NULL,
    activa       BOOLEAN NOT NULL DEFAULT true,
    CHECK (termina >= inicia),
    CHECK (categoria_id IS NOT NULL OR producto_id IS NOT NULL)
);

-- ---------------------------------------------------------------------
-- Clientes, pedidos, abonos y ventas
-- ---------------------------------------------------------------------
CREATE TABLE clientes (
    id        SERIAL PRIMARY KEY,
    documento TEXT UNIQUE,
    nombre    TEXT NOT NULL,
    telefono  TEXT,
    correo    TEXT,
    direccion TEXT,
    barrio    TEXT,
    municipio TEXT NOT NULL DEFAULT 'Mocoa',
    zona      TEXT NOT NULL DEFAULT 'urbana' CHECK (zona IN ('urbana','rural')),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

--  borrador ──(fn_confirmar_pedido)──> confirmado ──> entregado
--     │                                   ▲
--     └──(fn_separar_pedido)──> separado ─┘ (cuando los abonos completan el total)
--  cualquiera (menos entregado) ──(fn_cancelar_pedido)──> cancelado
CREATE TABLE pedidos (
    id                      SERIAL PRIMARY KEY,
    codigo                  TEXT UNIQUE,                 -- DEC-2611-0007 (lo pone un trigger)
    cliente_id              INTEGER REFERENCES clientes(id),
    canal                   TEXT NOT NULL DEFAULT 'texto' CHECK (canal IN ('texto','voz','presencial')),
    estado                  TEXT NOT NULL DEFAULT 'borrador'
                            CHECK (estado IN ('borrador','separado','confirmado','entregado','cancelado')),
    con_domicilio           BOOLEAN NOT NULL DEFAULT false,
    domicilio_por_confirmar BOOLEAN NOT NULL DEFAULT false,
    solicita_credito        TEXT CHECK (solicita_credito IN ('sistecredito','addi','credito_personal')),
    subtotal                NUMERIC(12,0) NOT NULL DEFAULT 0,
    descuento               NUMERIC(12,0) NOT NULL DEFAULT 0,
    domicilio               NUMERIC(12,0) NOT NULL DEFAULT 0,
    total                   NUMERIC(12,0) NOT NULL DEFAULT 0,
    abonado                 NUMERIC(12,0) NOT NULL DEFAULT 0,
    separado_hasta          DATE,
    notas                   TEXT,
    creado_en               TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmado_en           TIMESTAMPTZ,
    entregado_en            TIMESTAMPTZ,
    entrega_programada      DATE
);
CREATE INDEX idx_pedidos_estado ON pedidos(estado, creado_en);

CREATE TABLE pedido_items (
    id                 SERIAL PRIMARY KEY,
    pedido_id          INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    producto_id        INTEGER NOT NULL REFERENCES productos(id),
    cantidad           INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario    NUMERIC(12,0) NOT NULL,      -- precio de lista al momento del pedido
    descuento_unitario NUMERIC(12,0) NOT NULL DEFAULT 0,
    subtotal           NUMERIC(12,0) GENERATED ALWAYS AS (cantidad * (precio_unitario - descuento_unitario)) STORED,
    UNIQUE (pedido_id, producto_id)
);

-- Formas de pago de Decorer. Nequi, Daviplata y Bancolombia van como "transferencia".
CREATE TABLE abonos (
    id          BIGSERIAL PRIMARY KEY,
    pedido_id   INTEGER NOT NULL REFERENCES pedidos(id),
    valor       NUMERIC(12,0) NOT NULL CHECK (valor > 0),
    metodo_pago TEXT NOT NULL CHECK (metodo_pago IN ('efectivo','transferencia')),
    recibido_por TEXT NOT NULL DEFAULT 'asesor',
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ventas (
    id             SERIAL PRIMARY KEY,
    pedido_id      INTEGER NOT NULL UNIQUE REFERENCES pedidos(id),
    metodo_pago    TEXT NOT NULL CHECK (metodo_pago IN
                   ('efectivo','transferencia','sistecredito','addi','credito_personal','separado')),
    total          NUMERIC(12,0) NOT NULL,
    registrada_por TEXT NOT NULL DEFAULT 'agente',
    anulada        BOOLEAN NOT NULL DEFAULT false,
    vendida_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Conversación y trazabilidad (para la evaluación del agente)
-- ---------------------------------------------------------------------
CREATE TABLE conversaciones (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id  INTEGER REFERENCES clientes(id),
    pedido_id   INTEGER REFERENCES pedidos(id),     -- el "carrito" de esta conversación
    canal       TEXT NOT NULL DEFAULT 'texto',
    iniciada_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE mensajes (
    id              BIGSERIAL PRIMARY KEY,
    conversacion_id UUID NOT NULL REFERENCES conversaciones(id) ON DELETE CASCADE,
    rol             TEXT NOT NULL CHECK (rol IN ('usuario','agente','herramienta')),
    contenido       TEXT NOT NULL,
    audio_path      TEXT,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Una fila por turno: qué entendió, qué herramienta usó y cuánto tardó cada parte.
CREATE TABLE agente_trazas (
    id              BIGSERIAL PRIMARY KEY,
    conversacion_id UUID REFERENCES conversaciones(id) ON DELETE CASCADE,
    intencion       TEXT,            -- consultar_producto | crear_pedido | politica | derivar_asesor ...
    herramientas    JSONB,           -- [{nombre, argumentos, ok, resultado}]
    ok              BOOLEAN NOT NULL DEFAULT true,
    derivado_asesor BOOLEAN NOT NULL DEFAULT false,
    error           TEXT,
    modelo_llm      TEXT,
    ms_stt          INTEGER,
    ms_llm          INTEGER,
    ms_herramientas INTEGER,
    ms_tts          INTEGER,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
--  TRIGGERS
-- =====================================================================

-- Código legible del pedido: DEC-AAMM-0001
CREATE FUNCTION trg_codigo_pedido() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.codigo IS NULL THEN
        NEW.codigo := 'DEC-' || to_char(NEW.creado_en, 'YYMM') || '-' || lpad(NEW.id::text, 4, '0');
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER pedidos_codigo BEFORE INSERT ON pedidos
    FOR EACH ROW EXECUTE FUNCTION trg_codigo_pedido();

-- Alerta al dueño cuando un producto llega al stock mínimo y otra vez cuando se agota.
-- Además de guardar la alerta, avisa en vivo con NOTIFY: el panel del dueño
-- escucha el canal 'stock_bajo' (LISTEN) y la muestra sin recargar.
-- (Solo para cambios hechos por ventas o entradas; la carga inicial desde SysCafé no alerta.)
CREATE FUNCTION trg_alerta_stock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.existencias < OLD.existencias
       AND coalesce(current_setting('decorer.carga_masiva', true), '') <> 'on' AND (
          (NEW.existencias <= NEW.stock_minimo AND OLD.existencias > OLD.stock_minimo)
       OR (NEW.existencias = 0 AND OLD.existencias > 0)) THEN
        INSERT INTO alertas_stock(producto_id, existencias, stock_minimo)
        VALUES (NEW.producto_id, NEW.existencias, NEW.stock_minimo);
        PERFORM pg_notify('stock_bajo', json_build_object(
            'producto_id', NEW.producto_id,
            'producto', (SELECT nombre FROM productos WHERE id = NEW.producto_id),
            'existencias', NEW.existencias,
            'stock_minimo', NEW.stock_minimo,
            'estado', CASE WHEN NEW.existencias = 0 THEN 'agotado' ELSE 'bajo' END)::text);
    END IF;
    NEW.actualizado_en := now();
    RETURN NEW;
END $$;
CREATE TRIGGER inventario_alerta BEFORE UPDATE OF existencias ON inventario
    FOR EACH ROW EXECUTE FUNCTION trg_alerta_stock();

-- =====================================================================
--  FUNCIONES QUE USA EL AGENTE (sus "herramientas")
-- =====================================================================

CREATE FUNCTION fn_parametro(p_clave TEXT) RETURNS NUMERIC LANGUAGE sql STABLE AS $$
    SELECT valor FROM parametros WHERE clave = p_clave;
$$;

-- Precio con la mejor promoción vigente del día. Si el artículo no tiene precio
-- registrado, devuelve NULL (el agente dice que un asesor lo confirma).
CREATE FUNCTION fn_precio_vigente(p_producto_id INTEGER, p_fecha DATE DEFAULT current_date)
RETURNS TABLE (precio_lista NUMERIC, descuento_unitario NUMERIC, precio_final NUMERIC, promocion TEXT)
LANGUAGE sql STABLE AS $$
    SELECT p.precio,
           CASE WHEN p.precio IS NULL THEN NULL
                ELSE COALESCE(round(p.precio * best.porcentaje / 100, -2), 0) END,
           p.precio - COALESCE(round(p.precio * best.porcentaje / 100, -2), 0),
           CASE WHEN p.precio IS NULL THEN NULL ELSE best.nombre END
    FROM productos p
    LEFT JOIN LATERAL (
        SELECT pr.porcentaje, pr.nombre
        FROM promociones pr
        WHERE pr.activa AND p_fecha BETWEEN pr.inicia AND pr.termina
          AND (pr.producto_id = p.id OR pr.categoria_id = p.categoria_id)
        ORDER BY pr.porcentaje DESC
        LIMIT 1
    ) best ON true
    WHERE p.id = p_producto_id;
$$;

-- Búsqueda por nombre, categoría, línea, color o material, con filtros de precio.
-- Tolera tildes, plurales y errores ("colchom" -> colchón).
-- (La búsqueda por significado - "algo cómodo para ver tele" - va por pgvector.)
CREATE FUNCTION fn_buscar_productos(
    p_texto TEXT DEFAULT NULL, p_categoria TEXT DEFAULT NULL,
    p_precio_max NUMERIC DEFAULT NULL, p_solo_disponibles BOOLEAN DEFAULT false,
    p_limite INTEGER DEFAULT 8)
RETURNS TABLE (producto_id INTEGER, sku TEXT, nombre TEXT, categoria TEXT, linea TEXT, material TEXT,
               color TEXT, medidas TEXT, precio_lista NUMERIC, precio_final NUMERIC, promocion TEXT,
               precio_por_confirmar BOOLEAN, existencias INTEGER, disponible BOOLEAN)
LANGUAGE sql STABLE AS $$
    WITH q AS (
        SELECT unaccent(lower(trim(coalesce(p_texto, '')))) AS t
    ), candidatos AS (
        SELECT p.*, c.nombre AS cat_nombre, i.existencias AS stock,
               unaccent(lower(p.nombre || ' ' || c.nombre || ' ' || coalesce(p.linea,'') || ' ' ||
                              coalesce(p.material,'') || ' ' || coalesce(p.color,'') || ' ' ||
                              coalesce(p.marca,'') || ' ' || coalesce(p.descripcion_corta,''))) AS texto,
               unaccent(lower(p.nombre)) AS nombre_n
        FROM productos p
        JOIN categorias c ON c.id = p.categoria_id
        JOIN inventario i ON i.producto_id = p.id
        WHERE p.activo
          AND (p_categoria IS NULL OR unaccent(lower(c.nombre)) = unaccent(lower(p_categoria)))
          AND (NOT p_solo_disponibles OR i.existencias > 0)
    ), puntuados AS (
        SELECT k.*,
               -- 2 = están todas las palabras (en cualquier orden, sin tildes ni plurales); 1 = parecido
               CASE WHEN (SELECT t FROM q) = '' THEN 2
                    WHEN NOT EXISTS (
                        SELECT 1 FROM unnest(string_to_array((SELECT t FROM q), ' ')) AS w(palabra)
                        WHERE (length(w.palabra) > 2 OR w.palabra ~ '^[0-9]')
                          AND k.texto NOT LIKE '%' || rtrim(rtrim(w.palabra, 's'), 'e') || '%') THEN 2
                    WHEN word_similarity((SELECT t FROM q), k.nombre_n) > 0.6 THEN 1
                    ELSE 0 END AS nivel,
               similarity((SELECT t FROM q), k.nombre_n) AS parecido
        FROM candidatos k
    )
    SELECT x.id, x.sku, x.nombre, x.cat_nombre, x.linea, x.material, x.color,
           nullif(concat_ws(' x ', x.ancho_cm::float8 || ' cm ancho', x.fondo_cm::float8 || ' cm fondo',
                            x.alto_cm::float8 || ' cm alto'), ''),
           pv.precio_lista, pv.precio_final, pv.promocion, x.precio IS NULL,
           x.stock, x.stock > 0
    FROM puntuados x
    CROSS JOIN LATERAL fn_precio_vigente(x.id) pv
    WHERE x.nivel > 0
      AND (p_precio_max IS NULL OR pv.precio_final <= p_precio_max)
    ORDER BY x.nivel DESC, x.stock > 0 DESC, x.parecido DESC, x.precio IS NULL, pv.precio_final
    LIMIT p_limite;
$$;

-- Busca o registra al cliente por documento.
CREATE FUNCTION fn_registrar_cliente(p_documento TEXT, p_nombre TEXT, p_telefono TEXT DEFAULT NULL,
                                     p_direccion TEXT DEFAULT NULL, p_municipio TEXT DEFAULT 'Mocoa',
                                     p_barrio TEXT DEFAULT NULL, p_zona TEXT DEFAULT 'urbana')
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE v_id INTEGER;
BEGIN
    IF coalesce(trim(p_nombre), '') = '' THEN
        RAISE EXCEPTION 'Falta el nombre del cliente';
    END IF;
    INSERT INTO clientes(documento, nombre, telefono, direccion, municipio, barrio, zona)
    VALUES (nullif(trim(p_documento), ''), trim(p_nombre), p_telefono, p_direccion,
            coalesce(p_municipio, 'Mocoa'), p_barrio, coalesce(p_zona, 'urbana'))
    ON CONFLICT (documento) DO UPDATE
        SET nombre    = EXCLUDED.nombre,
            telefono  = coalesce(EXCLUDED.telefono, clientes.telefono),
            direccion = coalesce(EXCLUDED.direccion, clientes.direccion),
            barrio    = coalesce(EXCLUDED.barrio, clientes.barrio),
            municipio = EXCLUDED.municipio,
            zona      = EXCLUDED.zona
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- Recalcula subtotal, descuento, domicilio y total de un pedido.
-- Domicilio: gratis en la zona urbana de Mocoa desde $500.000.
-- Por debajo de ese valor, o fuera de la zona urbana, si Decorer no ha
-- registrado la tarifa, el pedido queda con "domicilio por confirmar".
CREATE FUNCTION fn_recalcular_pedido(p_pedido_id INTEGER) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    v_bruto NUMERIC; v_desc NUMERIC; v_dom NUMERIC := 0; v_por_confirmar BOOLEAN := false;
    v_con_dom BOOLEAN; v_municipio TEXT; v_zona TEXT; v_tarifa NUMERIC;
BEGIN
    SELECT coalesce(sum(cantidad * precio_unitario), 0), coalesce(sum(cantidad * descuento_unitario), 0)
      INTO v_bruto, v_desc FROM pedido_items WHERE pedido_id = p_pedido_id;

    SELECT pe.con_domicilio, coalesce(c.municipio, 'Mocoa'), coalesce(c.zona, 'urbana')
      INTO v_con_dom, v_municipio, v_zona
      FROM pedidos pe LEFT JOIN clientes c ON c.id = pe.cliente_id WHERE pe.id = p_pedido_id;

    IF v_con_dom THEN
        IF unaccent(lower(v_municipio)) = 'mocoa' AND v_zona = 'urbana' THEN
            IF (v_bruto - v_desc) >= fn_parametro('domicilio_gratis_desde') THEN
                v_dom := 0;
            ELSE
                v_tarifa := fn_parametro('domicilio_urbano_mocoa');
                IF v_tarifa IS NULL THEN v_por_confirmar := true; ELSE v_dom := v_tarifa; END IF;
            END IF;
        ELSE
            v_por_confirmar := true;     -- fuera de la zona urbana: lo coordina un asesor
        END IF;
    END IF;

    UPDATE pedidos SET subtotal = v_bruto, descuento = v_desc, domicilio = v_dom,
                       domicilio_por_confirmar = v_por_confirmar,
                       total = v_bruto - v_desc + v_dom
    WHERE id = p_pedido_id;
END $$;

-- Abre un pedido en borrador (el "carrito" de la conversación).
CREATE FUNCTION fn_crear_pedido(p_cliente_id INTEGER DEFAULT NULL, p_canal TEXT DEFAULT 'texto',
                                p_con_domicilio BOOLEAN DEFAULT false)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE v_id INTEGER;
BEGIN
    INSERT INTO pedidos(cliente_id, canal, con_domicilio)
    VALUES (p_cliente_id, p_canal, p_con_domicilio) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- Cambia datos del pedido en borrador (cliente o domicilio) y recalcula.
CREATE FUNCTION fn_actualizar_pedido(p_pedido_id INTEGER, p_cliente_id INTEGER DEFAULT NULL,
                                     p_con_domicilio BOOLEAN DEFAULT NULL)
RETURNS JSON LANGUAGE plpgsql AS $$
BEGIN
    UPDATE pedidos SET cliente_id = coalesce(p_cliente_id, cliente_id),
                       con_domicilio = coalesce(p_con_domicilio, con_domicilio)
     WHERE id = p_pedido_id AND estado = 'borrador';
    IF NOT FOUND THEN RAISE EXCEPTION 'El pedido % no existe o ya no está en borrador', p_pedido_id; END IF;
    PERFORM fn_recalcular_pedido(p_pedido_id);
    RETURN fn_resumen_pedido(p_pedido_id);
END $$;

-- Agrega (o cambia la cantidad de) un producto en un pedido en borrador.
-- p_cantidad = 0 quita el producto. Avisa si no hay stock suficiente HOY,
-- pero el descuento real del inventario solo pasa al confirmar o separar.
CREATE FUNCTION fn_agregar_item(p_pedido_id INTEGER, p_producto_id INTEGER, p_cantidad INTEGER)
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE
    v_estado TEXT; v_exist INTEGER; v_nombre TEXT; v_precio NUMERIC; pv RECORD;
BEGIN
    SELECT estado INTO v_estado FROM pedidos WHERE id = p_pedido_id;
    IF v_estado IS NULL THEN RAISE EXCEPTION 'El pedido % no existe', p_pedido_id; END IF;
    IF v_estado <> 'borrador' THEN
        RAISE EXCEPTION 'El pedido ya está %, no se puede modificar', v_estado;
    END IF;
    IF p_cantidad < 0 THEN RAISE EXCEPTION 'La cantidad no puede ser negativa'; END IF;

    SELECT p.nombre, p.precio, i.existencias INTO v_nombre, v_precio, v_exist
      FROM productos p JOIN inventario i ON i.producto_id = p.id
     WHERE p.id = p_producto_id AND p.activo;
    IF v_nombre IS NULL THEN RAISE EXCEPTION 'El producto % no existe o no está a la venta', p_producto_id; END IF;

    IF p_cantidad = 0 THEN
        DELETE FROM pedido_items WHERE pedido_id = p_pedido_id AND producto_id = p_producto_id;
    ELSE
        IF v_precio IS NULL THEN
            RAISE EXCEPTION '"%" no tiene precio registrado; un asesor confirma el precio', v_nombre
                USING HINT = 'precio_por_confirmar';
        END IF;
        IF p_cantidad > v_exist THEN
            RAISE EXCEPTION 'Solo hay % unidad(es) de "%"', v_exist, v_nombre
                USING HINT = 'stock_insuficiente';
        END IF;
        SELECT * INTO pv FROM fn_precio_vigente(p_producto_id);
        INSERT INTO pedido_items(pedido_id, producto_id, cantidad, precio_unitario, descuento_unitario)
        VALUES (p_pedido_id, p_producto_id, p_cantidad, pv.precio_lista, pv.descuento_unitario)
        ON CONFLICT (pedido_id, producto_id) DO UPDATE
            SET cantidad = EXCLUDED.cantidad,
                precio_unitario = EXCLUDED.precio_unitario,
                descuento_unitario = EXCLUDED.descuento_unitario;
    END IF;

    PERFORM fn_recalcular_pedido(p_pedido_id);
    RETURN fn_resumen_pedido(p_pedido_id);
END $$;

-- Resumen listo para que el agente lo lea en voz alta ANTES de confirmar.
CREATE FUNCTION fn_resumen_pedido(p_pedido_id INTEGER) RETURNS JSON LANGUAGE sql STABLE AS $$
    SELECT json_build_object(
        'pedido_id', pe.id, 'codigo', pe.codigo, 'estado', pe.estado, 'canal', pe.canal,
        'cliente', c.nombre,
        'items', coalesce((SELECT json_agg(json_build_object(
                    'producto_id', i.producto_id, 'producto', p.nombre, 'cantidad', i.cantidad,
                    'precio_unitario', i.precio_unitario, 'descuento_unitario', i.descuento_unitario,
                    'subtotal', i.subtotal) ORDER BY i.id)
                  FROM pedido_items i JOIN productos p ON p.id = i.producto_id
                  WHERE i.pedido_id = pe.id), '[]'::json),
        'subtotal', pe.subtotal, 'descuento', pe.descuento,
        'con_domicilio', pe.con_domicilio, 'domicilio', pe.domicilio,
        'domicilio_por_confirmar', pe.domicilio_por_confirmar,
        'falta_para_domicilio_gratis', CASE WHEN pe.con_domicilio AND pe.domicilio_por_confirmar
             THEN greatest(fn_parametro('domicilio_gratis_desde') - (pe.subtotal - pe.descuento), 0) END,
        'total', pe.total, 'abonado', pe.abonado, 'saldo', pe.total - pe.abonado,
        'separado_hasta', pe.separado_hasta, 'solicita_credito', pe.solicita_credito,
        'entrega_programada', pe.entrega_programada)
    FROM pedidos pe LEFT JOIN clientes c ON c.id = pe.cliente_id
    WHERE pe.id = p_pedido_id;
$$;

-- ---------------------------------------------------------------------
-- Descuento seguro del inventario (lo usan confirmar y separar).
--  1. Bloquea las filas de inventario de los productos del pedido, SIEMPRE en
--     el mismo orden (por producto_id) -> evita interbloqueos entre dos clientes.
--  2. Revisa existencias con el dato ya bloqueado (no con el que vio antes).
--  3. Descuenta y deja el kardex.
--  Quien la llama ya bloqueó el pedido y está dentro de la misma transacción.
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_descontar_inventario(p_pedido_id INTEGER, p_codigo TEXT, p_tipo TEXT, p_por TEXT)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE it RECORD; v_items INTEGER := 0;
BEGIN
    FOR it IN
        SELECT i.producto_id, i.cantidad, p.nombre, inv.existencias
        FROM pedido_items i
        JOIN productos  p   ON p.id = i.producto_id
        JOIN inventario inv ON inv.producto_id = i.producto_id
        WHERE i.pedido_id = p_pedido_id
        ORDER BY i.producto_id
        FOR UPDATE OF inv
    LOOP
        v_items := v_items + 1;
        IF it.existencias < it.cantidad THEN
            RAISE EXCEPTION 'Stock insuficiente de "%": quedan %, el pedido pide %',
                  it.nombre, it.existencias, it.cantidad USING HINT = 'stock_insuficiente';
        END IF;
        UPDATE inventario SET existencias = existencias - it.cantidad,
                              fuente_existencias = CASE WHEN fuente_existencias = 'syscafe' THEN 'sistema'
                                                        ELSE fuente_existencias END
         WHERE producto_id = it.producto_id;
        INSERT INTO movimientos_stock(producto_id, tipo, cantidad, existencias_antes,
                                      existencias_despues, motivo, referencia, creado_por)
        VALUES (it.producto_id, p_tipo, -it.cantidad, it.existencias, it.existencias - it.cantidad,
                CASE p_tipo WHEN 'separado' THEN 'Separado' ELSE 'Venta' END, p_codigo, p_por);
    END LOOP;
    IF v_items = 0 THEN RAISE EXCEPTION 'El pedido % está vacío', p_codigo; END IF;
    RETURN v_items;
END $$;

-- LA TRANSACCIÓN CLAVE: confirmar pedido = descontar inventario + registrar la venta.
-- Todo en UNA transacción: si algo falla, no queda nada a medias.
-- Las ventas a crédito (Sistecrédito, Addi, crédito personal) NO las cierra el agente:
-- las aprueba la entidad o la tienda, y un asesor las confirma.
CREATE FUNCTION fn_confirmar_pedido(p_pedido_id INTEGER, p_metodo_pago TEXT,
                                    p_registrada_por TEXT DEFAULT 'agente')
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE v_ped RECORD;
BEGIN
    IF p_metodo_pago NOT IN ('efectivo','transferencia','sistecredito','addi','credito_personal') THEN
        RAISE EXCEPTION 'Forma de pago no válida: %. Decorer recibe efectivo y transferencia, o crédito con Sistecrédito, Addi o crédito personal', p_metodo_pago;
    END IF;
    IF p_registrada_por = 'agente' AND p_metodo_pago IN ('sistecredito','addi','credito_personal') THEN
        RAISE EXCEPTION 'Las compras a crédito las aprueba la entidad; usa fn_solicitar_credito y un asesor termina la venta'
            USING HINT = 'credito_requiere_asesor';
    END IF;

    SELECT * INTO v_ped FROM pedidos WHERE id = p_pedido_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'El pedido % no existe', p_pedido_id; END IF;
    IF v_ped.estado <> 'borrador' THEN
        RAISE EXCEPTION 'El pedido % ya está %', v_ped.codigo, v_ped.estado;
    END IF;

    PERFORM fn_descontar_inventario(p_pedido_id, v_ped.codigo, 'salida', p_registrada_por);
    PERFORM fn_recalcular_pedido(p_pedido_id);
    UPDATE pedidos
       SET estado = 'confirmado', confirmado_en = now(), abonado = total,
           entrega_programada = CASE WHEN con_domicilio AND fn_parametro('dias_entrega') IS NOT NULL
               THEN current_date + fn_parametro('dias_entrega')::int END
     WHERE id = p_pedido_id;

    INSERT INTO ventas(pedido_id, metodo_pago, total, registrada_por)
    SELECT id, p_metodo_pago, total, p_registrada_por FROM pedidos WHERE id = p_pedido_id;

    RETURN fn_resumen_pedido(p_pedido_id);
END $$;

-- El cliente quiere pagar con crédito: queda anotado para el asesor (el pedido sigue en borrador).
CREATE FUNCTION fn_solicitar_credito(p_pedido_id INTEGER, p_entidad TEXT) RETURNS JSON LANGUAGE plpgsql AS $$
BEGIN
    IF p_entidad NOT IN ('sistecredito','addi','credito_personal') THEN
        RAISE EXCEPTION 'Entidad de crédito no válida: %', p_entidad;
    END IF;
    UPDATE pedidos SET solicita_credito = p_entidad,
                       notas = concat_ws(' | ', notas, 'Solicita crédito: ' || p_entidad)
     WHERE id = p_pedido_id AND estado = 'borrador';
    IF NOT FOUND THEN RAISE EXCEPTION 'El pedido % no existe o ya no está en borrador', p_pedido_id; END IF;
    RETURN fn_resumen_pedido(p_pedido_id);
END $$;

-- SEPARADO: el cliente deja un abono y el producto se aparta (sale del inventario disponible).
-- La venta se registra cuando los abonos completan el total.
CREATE FUNCTION fn_separar_pedido(p_pedido_id INTEGER, p_abono NUMERIC, p_metodo_pago TEXT,
                                  p_registrado_por TEXT DEFAULT 'agente')
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE v_ped RECORD; v_min_pct NUMERIC; v_plazo NUMERIC;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE id = p_pedido_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'El pedido % no existe', p_pedido_id; END IF;
    IF v_ped.estado <> 'borrador' THEN RAISE EXCEPTION 'El pedido % ya está %', v_ped.codigo, v_ped.estado; END IF;
    IF p_abono IS NULL OR p_abono <= 0 THEN RAISE EXCEPTION 'El abono debe ser mayor que cero'; END IF;
    IF p_abono >= v_ped.total THEN
        RAISE EXCEPTION 'El abono cubre todo el valor; mejor confirma la compra de contado';
    END IF;
    v_min_pct := fn_parametro('separado_abono_minimo_pct');
    IF v_min_pct IS NOT NULL AND p_abono < ceil(v_ped.total * v_min_pct / 100) THEN
        RAISE EXCEPTION 'Para separar se necesita un abono mínimo de $% (% %% del total)',
              to_char(ceil(v_ped.total * v_min_pct / 100), 'FM999G999G999'), v_min_pct;
    END IF;

    PERFORM fn_descontar_inventario(p_pedido_id, v_ped.codigo, 'separado', p_registrado_por);
    INSERT INTO abonos(pedido_id, valor, metodo_pago, recibido_por) VALUES (p_pedido_id, p_abono, p_metodo_pago, p_registrado_por);
    v_plazo := fn_parametro('separado_plazo_dias');
    UPDATE pedidos SET estado = 'separado', abonado = p_abono,
                       separado_hasta = CASE WHEN v_plazo IS NOT NULL THEN current_date + v_plazo::int END
     WHERE id = p_pedido_id;
    RETURN fn_resumen_pedido(p_pedido_id);
END $$;

-- Abono a un separado. Si completa el total, se registra la venta.
CREATE FUNCTION fn_registrar_abono(p_codigo TEXT, p_valor NUMERIC, p_metodo_pago TEXT,
                                   p_recibido_por TEXT DEFAULT 'asesor')
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE v_ped RECORD;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE upper(codigo) = upper(trim(p_codigo)) FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'No existe el pedido %', p_codigo; END IF;
    IF v_ped.estado <> 'separado' THEN RAISE EXCEPTION 'El pedido % no es un separado (está %)', v_ped.codigo, v_ped.estado; END IF;
    IF p_valor > v_ped.total - v_ped.abonado THEN
        RAISE EXCEPTION 'El abono ($%) supera el saldo ($%)', p_valor, v_ped.total - v_ped.abonado;
    END IF;
    INSERT INTO abonos(pedido_id, valor, metodo_pago, recibido_por) VALUES (v_ped.id, p_valor, p_metodo_pago, p_recibido_por);
    UPDATE pedidos SET abonado = abonado + p_valor WHERE id = v_ped.id;
    IF v_ped.abonado + p_valor = v_ped.total THEN
        UPDATE pedidos SET estado = 'confirmado', confirmado_en = now() WHERE id = v_ped.id;
        INSERT INTO ventas(pedido_id, metodo_pago, total, registrada_por)
        VALUES (v_ped.id, 'separado', v_ped.total, p_recibido_por);
    END IF;
    RETURN fn_resumen_pedido(v_ped.id);
END $$;

-- Cancela un pedido. Si ya había descontado inventario (confirmado o separado),
-- devuelve las unidades. Lo que pase con los abonos lo decide la tienda.
CREATE FUNCTION fn_cancelar_pedido(p_pedido_id INTEGER, p_motivo TEXT DEFAULT 'Solicitud del cliente')
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE v_ped RECORD; it RECORD;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE id = p_pedido_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'El pedido % no existe', p_pedido_id; END IF;
    IF v_ped.estado IN ('cancelado','entregado') THEN
        RAISE EXCEPTION 'El pedido % ya está % y no se puede cancelar', v_ped.codigo, v_ped.estado;
    END IF;

    IF v_ped.estado IN ('confirmado','separado') THEN
        FOR it IN
            SELECT i.producto_id, i.cantidad, inv.existencias
            FROM pedido_items i JOIN inventario inv ON inv.producto_id = i.producto_id
            WHERE i.pedido_id = p_pedido_id ORDER BY i.producto_id FOR UPDATE OF inv
        LOOP
            UPDATE inventario SET existencias = existencias + it.cantidad WHERE producto_id = it.producto_id;
            INSERT INTO movimientos_stock(producto_id, tipo, cantidad, existencias_antes,
                                          existencias_despues, motivo, referencia)
            VALUES (it.producto_id, 'devolucion', it.cantidad, it.existencias,
                    it.existencias + it.cantidad, p_motivo, v_ped.codigo);
        END LOOP;
        UPDATE ventas SET anulada = true WHERE pedido_id = p_pedido_id;
    END IF;

    UPDATE pedidos SET estado = 'cancelado',
                       notas = concat_ws(' | ', notas, 'Cancelado: ' || p_motivo ||
                               CASE WHEN v_ped.abonado > 0 THEN ' (abonos por $' || v_ped.abonado || ', revisar con la tienda)' ELSE '' END)
     WHERE id = p_pedido_id;
    RETURN fn_resumen_pedido(p_pedido_id);
END $$;

-- Entrega del pedido (la marca el asesor o el conductor).
CREATE FUNCTION fn_marcar_entregado(p_codigo TEXT) RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE v_id INTEGER;
BEGIN
    UPDATE pedidos SET estado = 'entregado', entregado_en = now()
     WHERE upper(codigo) = upper(trim(p_codigo)) AND estado = 'confirmado' RETURNING id INTO v_id;
    IF v_id IS NULL THEN RAISE EXCEPTION 'El pedido % no está confirmado (o no existe)', p_codigo; END IF;
    RETURN fn_resumen_pedido(v_id);
END $$;

-- ¿Aplica cambio inmediato? Política Decorer: hasta 7 días desde la entrega
-- (o desde la compra si se lo llevó de la tienda). Después, garantía con la marca,
-- que la tienda recibe y gestiona.
-- Pide el documento del cliente: los códigos son consecutivos y cualquiera podría adivinarlos.
CREATE FUNCTION fn_consultar_cambio(p_codigo TEXT, p_documento TEXT) RETURNS JSON LANGUAGE sql STABLE AS $$
    SELECT json_build_object(
        'codigo', pe.codigo, 'estado', pe.estado,
        'fecha_referencia', coalesce(pe.entregado_en, pe.confirmado_en)::date,
        'dias_transcurridos', current_date - coalesce(pe.entregado_en, pe.confirmado_en)::date,
        'aplica_cambio_inmediato', current_date - coalesce(pe.entregado_en, pe.confirmado_en)::date
                                   <= fn_parametro('dias_cambio_inmediato'),
        'venta_a_distancia', pe.canal IN ('texto','voz'),
        'productos', (SELECT json_agg(p.nombre) FROM pedido_items i JOIN productos p ON p.id = i.producto_id
                      WHERE i.pedido_id = pe.id))
    FROM pedidos pe JOIN clientes c ON c.id = pe.cliente_id
    WHERE upper(pe.codigo) = upper(trim(p_codigo)) AND c.documento = trim(p_documento)
      AND pe.estado IN ('confirmado','entregado');
$$;

-- Entrada de mercancía (factura del proveedor; en el paso 8 la leerá el agente desde una foto).
CREATE FUNCTION fn_entrada_inventario(p_producto_id INTEGER, p_cantidad INTEGER,
                                      p_referencia TEXT DEFAULT NULL, p_creado_por TEXT DEFAULT 'dueño')
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE v_antes INTEGER;
BEGIN
    IF p_cantidad <= 0 THEN RAISE EXCEPTION 'La cantidad de entrada debe ser mayor que cero'; END IF;
    SELECT existencias INTO v_antes FROM inventario WHERE producto_id = p_producto_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'El producto % no tiene inventario', p_producto_id; END IF;

    UPDATE inventario SET existencias = existencias + p_cantidad WHERE producto_id = p_producto_id;
    INSERT INTO movimientos_stock(producto_id, tipo, cantidad, existencias_antes, existencias_despues,
                                  motivo, referencia, creado_por)
    VALUES (p_producto_id, 'entrada', p_cantidad, v_antes, v_antes + p_cantidad,
            'Entrada de mercancía', p_referencia, p_creado_por);
    UPDATE alertas_stock SET atendida = true
     WHERE producto_id = p_producto_id AND NOT atendida
       AND v_antes + p_cantidad > (SELECT stock_minimo FROM inventario WHERE producto_id = p_producto_id);
    RETURN json_build_object('producto_id', p_producto_id, 'antes', v_antes, 'despues', v_antes + p_cantidad);
END $$;

-- Estado de un pedido por su código y el documento del cliente
-- ("¿cómo va mi pedido DEC-2611-0012?"). Sin el documento correcto no devuelve nada.
CREATE FUNCTION fn_estado_pedido(p_codigo TEXT, p_documento TEXT) RETURNS JSON LANGUAGE sql STABLE AS $$
    SELECT fn_resumen_pedido(pe.id) FROM pedidos pe JOIN clientes c ON c.id = pe.cliente_id
    WHERE upper(pe.codigo) = upper(trim(p_codigo)) AND c.documento = trim(p_documento);
$$;
