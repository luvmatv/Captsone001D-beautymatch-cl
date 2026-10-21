-- 006_listing_images.sql
-- La imagen de cada publicación, tal como la muestra la tienda (URL https).
-- La guarda el loader en cada carga; si un día la tienda no la trae, se
-- conserva la última conocida. Maicao no la entrega en su listado: queda NULL.
-- La API la usa para la lista de productos y la ficha.

ALTER TABLE raw_listings ADD COLUMN image_url TEXT;

INSERT INTO schema_migrations (name) VALUES ('006_listing_images');
