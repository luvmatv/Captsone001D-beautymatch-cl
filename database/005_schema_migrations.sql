-- 005_schema_migrations.sql
-- Registro de las migraciones aplicadas a esta base. La corrida diaria, el
-- loader y el pipeline comparan los archivos database/NNN_*.sql del árbol de
-- trabajo con esta tabla antes de escribir, y se detienen con un mensaje si
-- falta alguna o si la tabla no se puede leer (src/schema_check.py).
--
-- Desde esta migración, cada archivo nuevo termina registrándose a sí mismo:
--     INSERT INTO schema_migrations (name) VALUES ('006_<nombre>');
-- Las 001 a 004 ya estaban aplicadas a mano; se registran aquí.

CREATE TABLE schema_migrations (
    name       TEXT PRIMARY KEY,           -- nombre del archivo sin ".sql"
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (name) VALUES
    ('001_initial_schema'),
    ('002_raw_listing_parsed_attributes'),
    ('003_stable_product_ids'),
    ('004_scrape_runs'),
    ('005_schema_migrations');
