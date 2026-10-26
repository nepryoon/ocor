# OCOR-DEV-0060-BA-SELECTED-COMPONENTS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda i componenti reali su cui
qualificare `BA-01`, `BA-05` e `BA-06` in `OCOR-DEV-0060`. Tocca il change control di
`BA-01` (`DEC-201`, ADD v1.3 Parte I §2.6) e la scelta fra candidati e fallback
documentati: è una questione normativa, non operativa. Autorità corrente: mandato
`CC-OCOR-DELIVERY-COMPLETION`, DEC-210/211, `QUEUE-TO-G6-ORDER (2026-10-14)`.

## Contesto

`OCOR-DEV-0060` chiede che «ogni caso BA giri sul componente reale selezionato» e
produca un risultato individuale firmato con l'hash del raw log. Tra i criteri
negativi: un risultato mock, skipped, unavailable o legacy `RBA` non soddisfa un
identificativo BA. Le condizioni di escalation del task comprendono «servizio reale
richiesto non disponibile» e «una modifica sostituirebbe l'architettura approvata».

Prima di scrivere test e codice ho fatto un inventario in sola lettura su `origin/main`
`330f58a`. Per ogni BA ho confrontato il componente dichiarato dalla baseline con lo
stack di bootstrap (`deploy/bootstrap/compose.yaml`) e con gli adapter presenti in
`ocor-runtime/src/`.

## Fatti dell'inventario

Baseline normativa:

- ADD v1.3 Parte I §2.6, righe `BA-01`–`BA-08`: TerminusDB (`BA-01`), TypeDB 3.x
  (`BA-02`, `BA-03`), Jena/TDB2 (`BA-04`), Temporal + PostgreSQL (`BA-05`), storage
  S3-compatible + PostgreSQL (`BA-06`), Kafka/Strimzi (`BA-07`), OPA, Keycloak,
  SPIFFE/SPIRE, OpenBao (`BA-08`). I fallback di `BA-02`–`BA-08` sono «sostituzioni
  confinate se preservano i contratti». `BA-01` ne è esclusa esplicitamente: è
  `ARCHITECTURAL_ALTERNATIVE_REQUIRING_CHANGE_CONTROL`, `NO-GO` finché failure
  analysis, nuova §2.3/§6.2 e authority non approvano una sola alternativa
  (`V12-AM-14`, `PROPOSED — AWAITING CHANGE CONTROL`).
- `DEC-201` (Decision Register v1.2): commit atomico di stato, revision, idempotency
  record e outbox; «nessun fallback implicito».
- LLD v1.1 §5.2 (configuration baseline dei CI): «PostgreSQL resta adapter di verifica
  dell'atomicità e non sostituisce implicitamente TerminusDB».
- LLD v1.1 §7.1: oracle per BA. `BA-05`: «Temporal/PostgreSQL esegue le 44
  transizioni, guardie, unknown e precedence». `BA-06`: «S3/PostgreSQL sigilla causal
  result, lineage, identify-or-abstain e isolation».

Stack e runtime:

| BA | Componente dichiarato | Nello stack di bootstrap | Adapter nel runtime | Esito |
|---|---|---|---|---|
| `BA-01` | TerminusDB | sì, immagine pinned per digest | nessuno; C3 usa `c3/adapters/postgres.py` (PostgreSQL) e `fallback/postgres_outbox.py`, docstring «ratified for BA-01» | componente dichiarato senza adapter; l'adapter reale è il fallback PostgreSQL |
| `BA-02` | TypeDB 3.x | sì | `c4/typedb_adapter.py` | eseguibile |
| `BA-03` | TypeDB 3.x | sì | `c4/typedb_adapter.py`, `c4/rebuild.py` | eseguibile |
| `BA-04` | Jena/TDB2 | sì (Fuseki 6.2.0, immagine governata) | `c4/jena_adapter.py` | eseguibile |
| `BA-05` | Temporal + PostgreSQL | **Temporal assente** | nessuno; `c6/engine.py` usa `AtomicOutboxStore`, implementazione **in memoria** di `c3_store.py` | nessun componente reale |
| `BA-06` | S3-compatible + PostgreSQL | **nessun object store** | nessuno; `c7/runtime.py` calcola e sigilla in processo, senza persistenza | nessun componente reale |
| `BA-07` | Kafka/Strimzi | sì, broker singolo `cp-kafka` pinned; nessuno schema registry esterno né operatore Strimzi | `c5/backbone.py`, `c5/operations.py` (registry, replay, DLQ e quarantine di 0041) | eseguibile, con il limite descritto sotto |
| `BA-08` | OPA, Keycloak, SPIRE, OpenBao | sì | `security/control_plane.py` (0048) | eseguibile |

- Né `pyproject.toml` né `uv.lock` né `ocor-runtime/src/` contengono un client
  Temporal, S3 o TerminusDB.
- Gli spike `OCOR-DEV-0015`/`0016` (G2) qualificano PostgreSQL come «selected
  PostgreSQL backend» di C3. Non esiste però una decisione registrata che selezioni
  PostgreSQL al posto di TerminusDB per `BA-01`: `DEC-201` vieta il fallback implicito
  e l'LLD lo ripete.
- I test di `ocor-runtime/tests/backend_assumptions/test_ba0*.py` usano in gran parte
  astrazioni in memoria. Il piano li classifica `COMPATIBILITY_ONLY`, e la CI li esegue
  nel job `backend-compatibility-not-ba-evidence`: non sono evidenza BA.

Conseguenza: per `BA-05` e `BA-06` non esiste un componente reale su cui eseguire. Per
`BA-01` l'unico adapter reale è un fallback che la baseline non ha ancora approvato.
Le tre strade possibili (qualificare un fallback, introdurre un candidato oggi assente,
oppure rinviare) cambiano la tecnologia o l'alternativa architetturale sottoposta a
evidenza. Questa scelta è riservata al PO e, per `BA-01`, all'authority di change
control. Il loop non la prende d'iniziativa.

## Opzioni

1. **Change control esplicito sui fallback documentati, poi una remediation di persistenza, poi `0060`.**
   - Il PO, con l'authority richiesta, decide per `BA-01` l'alternativa «stato su
     RDBMS»: l'outbox transazionale PostgreSQL già implementata e qualificata negli spike
     0015/0016 e usata dal servizio C3 (`c3/service.py` su `PostgresC3Adapter`). Per `BA-05` attiva il fallback di §2.6, cioè una FSM
     proprietaria su PostgreSQL con outbox e lease. Per `BA-06` attiva l'object lock
     applicativo con digest verificato a ogni lettura, su PostgreSQL.
   - Una remediation governata (primo `OCOR-DEV-REM-*` libero) aggiunge, dietro i port
     esistenti, la persistenza PostgreSQL dello stato di workflow C6 e dei risultati
     sigillati C7, con RED/GREEN sul backend reale e le riqualifiche dovute.
   - Poi `0060` qualifica tutti gli otto BA. Ogni risultato nomina il componente reale e
     lo stato di fallback; TerminusDB, Temporal e S3 restano `Candidate Implementation`
     non qualificati.
   - Impatto: nessuna nuova dipendenza esterna né nuova immagine; superficie air-gap
     invariata. Rimangono aperti la verifica di licenza e benchmark di Temporal
     (`DEP-011`) e i rischi elencati nella colonna d'impatto (`RSK-013`, `RSK-019`,
     `RSK-023`, `RSK-054`, `RSK-028`).
2. **Provisioning dei candidati dichiarati, poi `0060`.**
   - Change set governati separati aggiungono allo stack di bootstrap e alla CI, pinned
     per digest:
     - un server Temporal con il suo PostgreSQL;
     - un object store S3-compatible strict-OSS, il cui prodotto lo sceglie il PO;
     - gli adapter runtime TerminusDB per C3, Temporal per C6 e S3 per C7, dietro i
       port esistenti, con le nuove dipendenze Python nei lock di toolchain e
       qualificazione e l'inventario licenze (`NFR-073`).
   - `BA-01` richiede comunque il change control: anche con l'adapter TerminusDB la
     baseline la classifica `NO-GO` finché un'alternativa non è approvata.
   - Impatto: nuove immagini e dipendenze, più memoria per stack sull'host (oggi 32 GB
     con agenti attivi), CI più lunga (tetto di 30 minuti per job su `main`), nuove
     riqualifiche dei task con input toccati.
3. **Esecuzione parziale ora, decisione rinviata.**
   - `0060` implementa ed esegue subito `BA-02`, `BA-03`, `BA-04`, `BA-07` e `BA-08`
     sui componenti presenti, con risultati individuali firmati.
   - `BA-01`, `BA-05` e `BA-06` vengono registrati `NOT_EXECUTED` per componente
     indisponibile. Il task non entra in `completed_evidence_tasks`, e
     `0065`–`0069` restano bloccati finché il PO non sceglie fra l'opzione 1 e
     l'opzione 2.
   - Impatto: anticipa lavoro utile, ma lascia aperta la questione di fondo e costringe
     a una seconda campagna e a una seconda verifica di `0060`.

## Raccomandazione

Opzione 1. È la strada che la baseline già prevede come alternativa documentata. Usa
l'unico adapter `BA-01` reale già costruito e qualificato negli spike. Non introduce
tecnologie né dipendenze nuove nel bundle air-gapped. Rende esplicito, e quindi non
implicito ai sensi di `DEC-201` e dell'LLD, ciò che il runtime fa oggi.

## Note dell'implementatore, valide per ogni opzione

Sono interpretazioni fail-closed senza impatto semantico. Il PO può correggerle.

- **`BA-07`.** Il caso gira sul broker Kafka pinned dello stack e sul registry di C5
  (0041). Il record dichiara come limite l'assenza dell'operatore Strimzi e di uno
  schema registry esterno. La parte licenze di `BA-07` resta legata a `OI-028` e non
  viene dichiarata chiusa.
- **Firma dei risultati.** Ogni risultato BA è firmato con una chiave generata
  localmente fuori da Git. La chiave pubblica e l'algoritmo stanno nel record, così il
  verifier può controllare la firma. È una scelta di tooling entro DEC-211.
- **Requisiti.** Il task elenca solo `BR-003`, mentre le prescrizioni G6 vietano di
  legare i casi qualificanti a un requisito generico. Ogni caso viene quindi legato ai
  requisiti specifici di `OCOR_TRACEABILITY_PLAN.csv` per il componente e
  l'oracle §7.1.

## Impatto e prossima azione

- Task bloccati: `OCOR-DEV-0060`. A valle restano bloccati per dipendenza i task già
  dipendenti da 0060: `0065`, `0066`, `0067`, `0068` e `0069`.
- Non bloccati: `OCOR-DEV-0061`, `0062`, `0063` e `0064`. Il loop prosegue con
  `OCOR-DEV-0061`, il numero più basso del ready set.
- Nessun codice, test, harness, workflow, record di evidenza o allowlist modificato.
  Nessun nuovo `DEC-*`. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
  PoC/Production `NO-GO` invariati.
