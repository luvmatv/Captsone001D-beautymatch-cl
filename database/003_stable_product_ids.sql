-- 003_stable_product_ids.sql
-- IDs estables: el pipeline actualiza fragrances/products en vez de recrearlos.
--
-- - fragrances se identifica por identity_key, la clave del pipeline (marca,
--   núcleo del nombre, género, edición), no por el nombre para mostrar, que
--   cambia según qué publicación se elige como referencia.
-- - products usa NULLS NOT DISTINCT (PostgreSQL 15+) para que el upsert también
--   encuentre la fila cuando concentration es NULL.
--
-- identity_key se calcula en Python, así que esta migración vacía el catálogo
-- canónico. Después de aplicarla hay que correr el pipeline:
--     python -m src.matching.pipeline
-- raw_listings y price_history no se borran.

BEGIN;

UPDATE raw_listings
SET product_id = NULL, matching_status = 'pending', match_confidence = NULL
WHERE product_id IS NOT NULL;
DELETE FROM products;
DELETE FROM fragrances;

ALTER TABLE fragrances
    ADD COLUMN identity_key TEXT NOT NULL,
    DROP CONSTRAINT fragrances_brand_name_gender_key,
    ADD CONSTRAINT fragrances_identity_key_key UNIQUE (identity_key);

ALTER TABLE products
    DROP CONSTRAINT products_fragrance_id_concentration_volume_ml_presentation_key,
    ADD CONSTRAINT products_fragrance_id_concentration_volume_ml_presentation_key
        UNIQUE NULLS NOT DISTINCT (fragrance_id, concentration, volume_ml, presentation);

COMMIT;
