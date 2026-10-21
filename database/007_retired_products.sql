-- 007_retired_products.sql
-- Los product_id que dejaron de existir, para que un enlace guardado no se
-- rompa. El pipeline borra un producto cuando ya no le queda ninguna
-- publicación (por ejemplo, porque resultó ser el mismo que otro); antes de
-- borrarlo lo anota aquí con el producto al que se fueron sus publicaciones.
-- La API responde 308 hacia ese producto (siguiendo la cadena si también se
-- retiró) y 410 si no hay destino.

CREATE TABLE retired_products (
    product_id     UUID PRIMARY KEY,
    replaced_by    UUID,         -- sin FK: el reemplazo también puede retirarse; la API sigue la cadena
    reason         TEXT NOT NULL CHECK (reason IN ('merged', 'no_listings')),
    canonical_name TEXT NOT NULL, -- el último nombre que tuvo, para diagnóstico
    retired_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_retired_products_replaced_by ON retired_products(replaced_by);

INSERT INTO schema_migrations (name) VALUES ('007_retired_products');
