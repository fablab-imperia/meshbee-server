-- ============================================
-- MIGRAZIONE: rimozione di schema non utilizzato
--   1. tabella `sensori`
--   2. viste `v_serie_temperatura`, `v_serie_umidita`, `v_serie_peso`
-- Esegui questo script se hai già il database attivo
-- e non vuoi perdere i dati esistenti.
--
-- È idempotente: rieseguirlo non fa danni (serve, se hai già applicato una
-- versione precedente di questo file che rimuoveva solo `sensori`).
-- ============================================

BEGIN;

-- --------------------------------------------
-- 1. Tabella `sensori`
-- --------------------------------------------
-- Residuo di un modello alternativo, mai adottato: un registro generico di
-- sensori per nodo, con calibrazione e soglie in `configurazione`.
-- L'implementazione ha preso un'altra strada:
--
--   * `letture` ha colonne fisse (temperatura, umidita, peso) + `dati_raw`,
--     non righe generiche (sensore, valore);
--   * l'identità del sensore vive su `arnie.id_sensore_fisico`, con la stessa
--     chiave naturale UNIQUE(id_nodo, id_sensore_fisico) di `sensori` — ma
--     senza alcuna foreign key fra le due: non sono mai state collegate;
--   * le soglie in `configurazione` servivano agli allarmi, rimossi da
--     migrate_v2.sql (tabella `allarmi`, trigger e funzione).
--
-- migrate_v2 ha ripulito gli allarmi ma ha dimenticato `sensori`. Nessuna riga
-- è mai stata inserita, nessuna query la legge, nessuna foreign key la
-- referenzia.
--
-- Gli indici idx_sensori_nodo e idx_sensori_attivo cadono con la tabella.

-- Salvaguardia: se per qualche motivo la tabella contiene dati, questa
-- migrazione va rivista prima di eseguirla, non applicata alla cieca.
DO $$
DECLARE
    righe BIGINT;
BEGIN
    IF to_regclass('public.sensori') IS NULL THEN
        RAISE NOTICE 'Tabella sensori già assente, niente da fare.';
        RETURN;
    END IF;

    EXECUTE 'SELECT count(*) FROM sensori' INTO righe;
    IF righe > 0 THEN
        RAISE EXCEPTION
            'La tabella sensori contiene % righe: verifica prima di rimuoverla.', righe;
    END IF;
END
$$;

DROP TABLE IF EXISTS sensori;

-- --------------------------------------------
-- 2. Viste `v_serie_*`
-- --------------------------------------------
-- Definite in init.sql ma mai interrogate: gli endpoint delle serie storiche
-- (`/api/user/arnie/{id}/letture/{temperatura|umidita|peso}`) usano una query
-- parametrica in `meshbee_core/repository/letture.py::series`.
--
-- Non è una svista da correggere adottando le viste: la query è quasi tutta
-- parametri (id_arnia, intervallo di date, LIMIT) e una vista non ne accetta,
-- quindi il chiamante dovrebbe comunque scriverli. In più le viste fanno JOIN
-- su `arnie` per `nome_arnia`, che le risposte non contengono
-- (SerieTemperaturaResponse = {timestamp, temperatura}), e hanno un ORDER BY
-- interno inutile una volta filtrato su una sola arnia.
--
-- Si rimuovono perché inducono in errore: chi le vede assume che gli endpoint
-- le usino. La query parametrica resta l'unica implementazione.
--
-- NB: `v_arnie_stato` è usata (repository/arnie.py) e non va toccata.
-- `v_letture_recenti` è anch'essa inutilizzata ma resta: vedi discussione.

DROP VIEW IF EXISTS v_serie_temperatura;
DROP VIEW IF EXISTS v_serie_umidita;
DROP VIEW IF EXISTS v_serie_peso;

COMMIT;

-- Verifica: non deve restituire alcuna riga
SELECT 'tabella: ' || tablename AS residuo FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'sensori'
UNION ALL
SELECT 'vista: ' || viewname FROM pg_views
WHERE schemaname = 'public' AND viewname IN
    ('v_serie_temperatura', 'v_serie_umidita', 'v_serie_peso');
