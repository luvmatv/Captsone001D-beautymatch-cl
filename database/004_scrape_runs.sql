-- 004_scrape_runs.sql
-- Registro de las corridas diarias (python -m src.daily_run).
--
-- scrape_runs: una fila por corrida. Se crea al empezar (status 'running') y
-- se cierra al terminar; una fila que queda en 'running' sin finished_at es
-- una corrida interrumpida (por ejemplo, el computador se apagó).
--
-- scrape_run_stores: una fila por archivo de scrape tratado en la corrida:
-- el scrape del día de cada tienda y, si la base estuvo caída antes, los
-- archivos pendientes de días anteriores (is_backfill). Dice qué días hubo un
-- scrape completo de cada tienda: sin esto, "no hay precio del martes" no
-- distingue entre "la tienda lo sacó" y "el scraper falló".

BEGIN;

CREATE TYPE run_status AS ENUM ('running', 'ok', 'partial', 'failed');

CREATE TABLE scrape_runs (
    run_id           BIGSERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    status           run_status NOT NULL DEFAULT 'running',
    embeddings_added INTEGER,
    pipeline_stats   JSONB,        -- listings por estado, fragancias, productos
    errors           TEXT[] NOT NULL DEFAULT '{}',  -- fallas fuera de una tienda: embeddings, pipeline
    log_path         TEXT
);

CREATE TABLE scrape_run_stores (
    run_store_id         BIGSERIAL PRIMARY KEY,
    run_id               BIGINT NOT NULL REFERENCES scrape_runs(run_id) ON DELETE CASCADE,
    store                TEXT NOT NULL,   -- nombre, no FK: una tienda puede fallar antes de existir en stores
    file                 TEXT,            -- JSON en artifacts/raw/; NULL si el scraper no dejó archivo
    scraped_at           TIMESTAMPTZ,     -- = price_history.scraped_at de sus precios
    is_backfill          BOOLEAN NOT NULL DEFAULT false,
    -- ok: scrape completo y cargado. partial: se cargaron precios, pero el
    -- scrape no terminó limpio o trajo menos del 80 % del catálogo, así que no
    -- se desactivó nada. failed: no se cargó nada.
    status               run_status NOT NULL CHECK (status <> 'running'),
    stop_reason          TEXT,            -- catalog_exhausted, short_page, timeout, exit_code_1...
    products_scraped     INTEGER,
    listings_new         INTEGER,
    listings_updated     INTEGER,
    prices_added         INTEGER,
    listings_deactivated INTEGER,
    rows_skipped         INTEGER,         -- productos del JSON que no se pudieron convertir
    duration_seconds     NUMERIC(8, 1),   -- scrape + carga
    notes                TEXT[] NOT NULL DEFAULT '{}',
    error                TEXT
);

CREATE INDEX idx_scrape_run_stores_run ON scrape_run_stores(run_id);
CREATE INDEX idx_scrape_run_stores_store_time ON scrape_run_stores(store, scraped_at);

COMMIT;
