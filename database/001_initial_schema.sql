-- 001_initial_schema.sql
-- Esquema inicial de BeautyMatch CL (PostgreSQL + pgvector).
-- Embeddings: vector(768).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

-- Enums
CREATE TYPE gender_type AS ENUM ('male', 'female', 'unisex');

CREATE TYPE concentration_type AS ENUM (
    'edp', 'edt', 'parfum', 'cologne', 'eau_fraiche', 'other'
);

CREATE TYPE presentation_type AS ENUM (
    'full_bottle', 'tester', 'travel_set', 'miniature', 'refill'
);

CREATE TYPE matching_status AS ENUM (
    'pending', 'matched', 'new_product', 'rejected'
);

-- mantiene updated_at al día en cada UPDATE
CREATE FUNCTION set_updated_at() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- stores: tiendas scrapeadas
CREATE TABLE stores (
    store_id    SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    base_url    TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- fragrances: identidad del perfume, independiente de la presentación
CREATE TABLE fragrances (
    fragrance_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand         TEXT NOT NULL,
    name          TEXT NOT NULL,
    gender        gender_type NOT NULL DEFAULT 'unisex',
    embedding     VECTOR(768),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brand, name, gender)
);

CREATE INDEX idx_fragrances_embedding
    ON fragrances USING hnsw (embedding vector_cosine_ops);

CREATE TRIGGER trg_fragrances_updated_at
    BEFORE UPDATE ON fragrances
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- products: versión vendible y comparable de una fragancia
-- (mismo perfume + misma concentración + mismo volumen + misma presentación)
CREATE TABLE products (
    product_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fragrance_id   UUID NOT NULL REFERENCES fragrances(fragrance_id),
    concentration  concentration_type, -- NULL = no informado; 'other' = tipo real infrecuente
    volume_ml      INTEGER NOT NULL CHECK (volume_ml > 0),
    presentation   presentation_type NOT NULL DEFAULT 'full_bottle',
    canonical_name TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fragrance_id, concentration, volume_ml, presentation)
);

CREATE INDEX idx_products_fragrance ON products(fragrance_id);

CREATE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- raw_listings: lo scrapeado tal cual, antes/después del matching
CREATE TABLE raw_listings (
    raw_listing_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         INTEGER NOT NULL REFERENCES stores(store_id),
    product_id       UUID REFERENCES products(product_id), -- null hasta matchear
    store_sku        TEXT,
    listing_url      TEXT NOT NULL,
    raw_name         TEXT NOT NULL,
    raw_brand        TEXT,
    raw_description  TEXT,
    embedding        VECTOR(768),
    matching_status  matching_status NOT NULL DEFAULT 'pending',
    match_confidence NUMERIC(4,3),
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active        BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (store_id, listing_url)
);

CREATE INDEX idx_raw_listings_embedding
    ON raw_listings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_raw_listings_product ON raw_listings(product_id);
CREATE INDEX idx_raw_listings_status ON raw_listings(matching_status);

-- price_history: una fila por cada scrape
CREATE TABLE price_history (
    price_history_id BIGSERIAL PRIMARY KEY,
    raw_listing_id    UUID NOT NULL REFERENCES raw_listings(raw_listing_id),
    price        NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    list_price   NUMERIC(10,2), -- precio "antes del descuento" mostrado por la tienda
    currency     CHAR(3) NOT NULL DEFAULT 'CLP',
    is_available BOOLEAN NOT NULL DEFAULT true,
    scraped_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_price_history_listing_time
    ON price_history(raw_listing_id, scraped_at DESC);

-- vista de ayuda: último precio activo por publicación
CREATE VIEW current_prices AS
SELECT DISTINCT ON (rl.raw_listing_id)
    rl.raw_listing_id,
    rl.product_id,
    rl.store_id,
    ph.price,
    ph.list_price,
    ph.currency,
    ph.is_available,
    ph.scraped_at
FROM raw_listings rl
JOIN price_history ph ON ph.raw_listing_id = rl.raw_listing_id
WHERE rl.is_active = true
ORDER BY rl.raw_listing_id, ph.scraped_at DESC;
