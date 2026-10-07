-- ============================================
-- MIGRATION: node battery voltage
--   1. column `letture.batteria` + CHECK `valid_batteria` (0 to 5 V)
--   2. column `ultima_batteria` appended to `v_arnie_stato`
-- Run this script if the database is already live and you don't want to
-- lose the existing data.
--
-- Idempotent: running it twice does no harm.
-- ============================================

BEGIN;

-- --------------------------------------------
-- 1. Column `letture.batteria`
-- --------------------------------------------
-- The ESP32 node reports its battery voltage as the payload key `bat`;
-- meshbee_core/services/ingest.py renames it to `batteria`. Nullable: older
-- firmware doesn't send it, and a node on mains power never will.
--
-- The range is also declared in mqtt_handler/contract.py
-- (BATTERIA_MIN/MAX), meshbee_core/schemas.py (LetturaBase) and init.sql;
-- tests/integration/core/test_schemas.py checks they agree.

ALTER TABLE letture
    ADD COLUMN IF NOT EXISTS batteria DECIMAL(4,3);

ALTER TABLE letture
    DROP CONSTRAINT IF EXISTS valid_batteria;

ALTER TABLE letture
    ADD CONSTRAINT valid_batteria
        CHECK (batteria IS NULL OR (batteria >= 0 AND batteria <= 5));

-- --------------------------------------------
-- 2. View `v_arnie_stato`
-- --------------------------------------------
-- Same definition as init.sql. `ultima_batteria` goes last because
-- CREATE OR REPLACE VIEW may only append columns, not reorder them.

CREATE OR REPLACE VIEW v_arnie_stato AS
SELECT 
    a.id_arnia,
    a.id_nodo,
    a.id_sensore_fisico,
    a.nome_arnia,
    n.nome_nodo,
    a.posizione,
    a.latitudine,
    a.longitudine,
    a.data_installazione,
    a.data_rimozione,
    a.attiva,
    a.metadati,
    (SELECT temperatura FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultima_temperatura,
    (SELECT umidita   FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultima_umidita,
    (SELECT peso      FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultimo_peso,
    (SELECT timestamp FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultimo_aggiornamento,
    (SELECT batteria  FROM letture WHERE id_arnia = a.id_arnia ORDER BY timestamp DESC LIMIT 1) as ultima_batteria
FROM arnie a
LEFT JOIN nodi n ON a.id_nodo = n.id_nodo;

COMMIT;

-- Check: must return no rows
SELECT 'missing column: letture.batteria' AS residuo
WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'letture' AND column_name = 'batteria')
UNION ALL
SELECT 'missing constraint: valid_batteria'
WHERE NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'valid_batteria')
UNION ALL
SELECT 'missing view column: v_arnie_stato.ultima_batteria'
WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'v_arnie_stato' AND column_name = 'ultima_batteria');
