-- 002_raw_listing_parsed_attributes.sql
-- Atributos que el script de carga extrae de cada publicación, antes del
-- matching. Quedan en raw_listings para que el matching los compare sin volver
-- a parsear raw_name; products sigue siendo la versión canónica.

ALTER TABLE raw_listings
    -- NULL = la tienda no la informa (igual que products.concentration)
    ADD COLUMN parsed_concentration concentration_type,
    ADD COLUMN parsed_volume_ml     INTEGER CHECK (parsed_volume_ml > 0);
