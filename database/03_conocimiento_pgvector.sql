-- =====================================================================
--  DECORER · 03_conocimiento_pgvector.sql
--  Conocimiento del agente (búsqueda semántica con pgvector).
--
--  Aquí NO van precios ni existencias (esos siempre salen de SQL).
--  Aquí va lo que se pregunta "con palabras":
--    - fichas de producto  ("¿ese sofá aguanta mascotas?")
--    - políticas           ("¿puedo devolver un colchón?")
--    - promociones         ("¿qué condiciones tiene el Black Friday?")
--    - preguntas frecuentes, cuidados y garantías
--
--  Vectores: EmbeddingGemma 2 -> 768 dimensiones (como en Archivo Vivo).
-- =====================================================================

CREATE TABLE conocimiento (
    id          BIGSERIAL PRIMARY KEY,
    fuente      TEXT NOT NULL,                 -- archivo de origen (politicas.md, catalogo.pdf...)
    tipo        TEXT NOT NULL CHECK (tipo IN
                ('ficha_producto','politica','promocion','faq','cuidado','garantia','catalogo_proveedor')),
    producto_id INTEGER REFERENCES productos(id) ON DELETE CASCADE,   -- enlaza la ficha con SQL
    titulo      TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    contenido   TEXT NOT NULL,
    metadatos   JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding   vector(768) NOT NULL,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fuente, chunk_index)
);

-- Índice HNSW con distancia coseno (el mismo de Archivo Vivo)
CREATE INDEX idx_conocimiento_hnsw ON conocimiento USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_conocimiento_tipo ON conocimiento (tipo);
CREATE INDEX idx_conocimiento_producto ON conocimiento (producto_id);

-- Búsqueda semántica. El backend manda el vector de la pregunta
-- (prefijo "task: search result | query: ...") y opcionalmente filtra por tipo.
-- Devuelve el producto enlazado para que el agente pueda consultar su precio en SQL.
CREATE FUNCTION fn_buscar_conocimiento(p_embedding vector(768), p_tipo TEXT DEFAULT NULL,
                                       p_limite INTEGER DEFAULT 5, p_umbral REAL DEFAULT 0.35)
RETURNS TABLE (id BIGINT, fuente TEXT, tipo TEXT, titulo TEXT, contenido TEXT,
               producto_id INTEGER, sku TEXT, similitud REAL)
LANGUAGE sql STABLE AS $$
    SELECT k.id, k.fuente, k.tipo, k.titulo, k.contenido, k.producto_id, p.sku,
           (1 - (k.embedding <=> p_embedding))::real AS similitud
    FROM conocimiento k
    LEFT JOIN productos p ON p.id = k.producto_id
    WHERE (p_tipo IS NULL OR k.tipo = p_tipo)
      AND 1 - (k.embedding <=> p_embedding) >= p_umbral
    ORDER BY k.embedding <=> p_embedding
    LIMIT p_limite;
$$;

-- Respaldo sin embeddings: si llama.cpp está apagado, el agente igual encuentra la política
-- con búsqueda de texto completo en español (y por parecido si no hay coincidencia exacta).
CREATE FUNCTION fn_buscar_conocimiento_texto(p_pregunta TEXT, p_tipo TEXT DEFAULT NULL, p_limite INTEGER DEFAULT 3)
RETURNS TABLE (id BIGINT, fuente TEXT, tipo TEXT, titulo TEXT, contenido TEXT, puntaje REAL)
LANGUAGE sql STABLE AS $$
    WITH q AS (SELECT websearch_to_tsquery('spanish', unaccent(p_pregunta)) AS tq,
                      unaccent(lower(p_pregunta)) AS t)
    SELECT k.id, k.fuente, k.tipo, k.titulo, k.contenido,
           (ts_rank(to_tsvector('spanish', unaccent(k.titulo || ' ' || k.contenido)), q.tq)
            + similarity(unaccent(lower(k.titulo)), q.t))::real AS puntaje
    FROM conocimiento k, q
    WHERE (p_tipo IS NULL OR k.tipo = p_tipo)
    ORDER BY puntaje DESC
    LIMIT p_limite;
$$;

-- Fotos del Drive de publicidad de Decorer (las carga importar\cargar_inventario.py desde drive_modelos.csv).
-- productos.drive_id guarda la foto de un producto solo cuando el cruce es seguro.
CREATE TABLE fotos_catalogo (
    id       SERIAL PRIMARY KEY,
    carpeta  TEXT NOT NULL,
    modelo   TEXT NOT NULL,
    drive_id TEXT NOT NULL UNIQUE
);
