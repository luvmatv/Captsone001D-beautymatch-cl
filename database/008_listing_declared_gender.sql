-- 008_listing_declared_gender.sql
-- El género que la tienda declara aparte del nombre (dperfumes: su atributo
-- "Género"). NULL = la tienda no lo declara. El matching lo trata como los
-- códigos (M)/(H) de Beauty Perfumes: da el género de la fragancia y manda un
-- par a revisión si contradice al otro lado, pero nunca veta ni acepta solo.
-- 'unisex' se guarda pero el matching no lo lee (como el (U) de Beauty Perfumes).

ALTER TABLE raw_listings ADD COLUMN declared_gender gender_type;

INSERT INTO schema_migrations (name) VALUES ('008_listing_declared_gender');
