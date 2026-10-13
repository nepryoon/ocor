# OCOR-DEV-REM-0026-RCCAD — C5: deduplica e watermark durevoli e atomici, quota per tenant atomica

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`. Verifier: Grok 4.7 via Cursor CLI
  (processo, contesto e fornitore separati); Claude Code, implementatore di riserva, non verifica
  questo change set (`LOOP-ROLES`).
- **Fonte**: decisione del Product Owner `INFO-C` (2026-10-05) e audit del 2026-10-12 in
  `reports/development/decision_requests/INFO-C.md`, che ha registrato `OCOR-DEV-REM-0026` come primo
  identificativo libero (`EXECUTION_STATE` → `remediation_status.REM_0026_C5_DURABLE_ATOMIC_DEDUP_AND_QUOTA`).
  Dipendenza `OCOR-DEV-REM-0025` unita in `c0fe81d`.
- **Branch**: `governed/ocor-dev-rem-0026-c5-durable-atomic-dedup-quota`

## Ambito

| Osservazione (INFO-C, broker Kafka reale) | Correzione |
|---|---|
| R1 — dopo un riavvio (nuova istanza sullo stesso broker e topic) una `idempotency_key` già durevole viene ripubblicata | il topic è il journal durevole: prima della prima pubblicazione di un'istanza le chiavi di deduplica sono ricostruite da tutti i record del topic |
| R2 — dopo un riavvio una sequenza vecchia per l'aggregate è accettata | la stessa ricostruzione ripristina il watermark per `(governed_context_digest, aggregate_ref)` come massima sequenza registrata |
| K1 — due publish concorrenti dello stesso envelope scrivono due record | controllo di deduplica, scrittura Kafka e aggiornamento dello stato sotto un unico lock dell'istanza |
| K2 — sequenze 5 e 4 concorrenti accettate entrambe, watermark regredito a 4 | controllo di ordinamento e aggiornamento del watermark sotto lo stesso lock |
| Q1 — con quota 1 due publish concorrenti ammessi, contatore finale -1 | in `EventOperationsCoordinator` lettura, confronto e incremento del contatore per tenant sotto lock; decremento sotto lo stesso lock, solo dopo il proprio incremento |
| Esito sconosciuto della scrittura (ACK perso) | un `KafkaBackboneError` sulla scrittura invalida lo stato: la pubblicazione successiva lo ricostruisce dal journal, quindi il retry non duplica |
| Criterio fail-closed | record illeggibile nel journal, topic assente o risposta degli offset senza partizioni del topic: `KafkaBackboneError`, nessuna scrittura, nessun ripiego su stato vuoto |
| Controllo della classe | anche il contatore dei tentativi per evento (soglia `POISON`) è aggiornato sotto lock |

Scelta progettuale (LLD v1.1 §6 "deduplica durable"): nessun nuovo store né dipendenza; lo stato in
memoria è soltanto una cache del topic, ricostruita all'avvio dell'istanza e dopo ogni esito di
scrittura sconosciuto. L'atomicità vale per istanza: l'istanza è l'unico producer attivo del proprio
topic. Due istanze vive che pubblicano contemporaneamente sullo stesso topic non sono serializzate tra
loro: rischio residuo dichiarato nel record, fuori dai criteri di REM-0026.

## Vincoli rispettati

- Semantica di replay di C5 invariata (`INFO-A` opzione 1): replay nello stesso contesto no-op, nessun
  rilevamento "stessa chiave / payload diverso". Scoping per contesto di `OCOR-DEV-REM-0025` preservato
  anche nello stato ricostruito. Nessuna dichiarazione exactly-once end-to-end.
- `c5/backbone.py` e `c5/operations.py` cambiano, quindi `OCOR-DEV-0040` e `OCOR-DEV-0041` sono
  riqualificati; l'allowlist del validator di piano, input della riqualifica sigillata REM-0025 di
  `OCOR-DEV-0050`, cambia, quindi 0050 è riqualificato con ambito di sola regressione. Nessun record
  sigillato modificato; `test_ocor_dev_0040.py`, `test_ocor_dev_0041.py` e `test_ocor_dev_rem_0025.py`
  sono byte-identici.
- Nessun test escluso, saltato o indebolito. `E1=0`, `E2=0`, nessun requisito `Verified`; runtime
  conformance, PoC-GO e Production readiness invariati (`NOT_ESTABLISHED` / `NO-GO`). Nessuna modifica a
  `inputs/`.

## TDD

Casi scritti per primi (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0026.py`, commit `034e53d`) ed
eseguiti sul codice non corretto in un worktree separato con venv propria: 13 casi falliscono per il
difetto su asserzioni di comportamento, i 3 controlli positivi passano. Le concorrenze usano thread
reali con interleaving forzato da strumenti di osservazione (scrittura Kafka trattenuta, lettura del
contatore trattenuta), non dalla fortuna dei tempi. Un primo RED di una versione precedente dei test
(mai pubblicata) aveva uno strumento difettoso sul contatore: resta fuori dal repository come
diagnostico ed è descritto nel record. GREEN dopo la correzione (`8f7a680`). Prova di mutazione: 8
mutanti su 8 uccisi al commit della campagna; la prima prova (7 su 8) ha portato al caso aggiuntivo
`test_an_offsets_answer_naming_no_partition_of_the_topic_fails_closed` (`5e1935e`).

## Evidenza

- `OCOR-DEV-REM-0026.json` / `.log`: record della remediation, raw JSONL dell'intera campagna.
- `reports/evidence/G4/OCOR-DEV-0040.requalified-rem0026.json`,
  `reports/evidence/G4/OCOR-DEV-0041.requalified-rem0026.json` e
  `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0026.json` (con i rispettivi `.log`, byte-identici al
  raw della campagna): riqualifiche con `supersedes` esplicito; i manifest G4 e G5 puntano ai nuovi record.
- Controllo meccanico riproducibile: vedi `reproducible_check` nel record (non è verifica indipendente).
