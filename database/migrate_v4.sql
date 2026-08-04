-- ============================================
-- MIGRAZIONE: rimozione della tabella sensori
-- Esegui questo script se hai già il database attivo
-- e non vuoi perdere i dati esistenti
-- ============================================
--
-- `sensori` è il residuo di un modello alternativo, mai adottato: un registro
-- generico di sensori per nodo, con calibrazione e soglie in `configurazione`.
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
-- migrate_v2 ha ripulito gli allarmi ma ha dimenticato `sensori`. Nessuna
-- riga è mai stata inserita, nessuna query la legge, nessuna foreign key la
-- referenzia: si rimuove per non lasciare in giro uno schema che invita a
-- ricostruire per sbaglio il modello abbandonato.
--
-- Gli indici idx_sensori_nodo e idx_sensori_attivo cadono con la tabella.

BEGIN;

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

COMMIT;

-- Verifica: non deve restituire alcuna riga
SELECT tablename FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'sensori';
