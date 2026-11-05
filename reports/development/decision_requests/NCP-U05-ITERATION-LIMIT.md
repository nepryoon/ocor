# NCP-U05-ITERATION-LIMIT

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0052`
(NCP-U05 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, proiezioni C4; branch
`governed/ocor-dev-rem-0052-ncp-u05-c4-projections`, head di lavoro `3cf255bc4c77a41caf67a13bdc29edbb8a8a19c0`,
non candidato). Aperta secondo il punto 1 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` («Se un'unità supera il
doppio della stima, fermati e apri una decision request di livello normativo con lo stato del lavoro») e secondo
il punto 5 di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` per le divergenze nuove trovate dall'inventario dei
consumer. Implementatore: Claude Code (Anthropic), implementatore di riserva del loop, per tutte le iterazioni
dell'unità.

## Contesto

- La stima di NCP-U05 nel piano è 3 iterazioni (`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`,
  `plan_units.NCP-U05.estimate_iterations`); il doppio è 6. La sesta iterazione è finita senza candidato.
- Stato del lavoro al head `3cf255b`:
  - tutte e quattro le voci sono GREEN sullo stack reale: `NCR-C4-001` e `NCR-C4-003` (RED `0d22acc`, `67da95d`,
    GREEN `fb9e20a`), `NCR-C4-004` (RED `49b7616`, GREEN `5af48a9`), `NCR-C4-002` in tre parti, drift (RED
    `36cc66a`, GREEN `2547123`), Jena (RED `a0f52ae`, GREEN `7d5c4c1`) e SHACL (RED `7a39c51`, GREEN `437852a`,
    secondo `NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05)`, opzione 1). Ultima esecuzione di modulo dell'unità, dei
    consumer e del mission thread: 870 passati; i 2 falliti sono i casi Temporal dal vivo di
    `ocor-runtime/tests/tasks/test_ocor_dev_rem_0038.py`, con Temporal non avviato, identici alla base;
  - packaging: allowlist del validatore di piano (`218ff46`), bozza del record
    `reports/assurance/OCOR-DEV-REM-0052-RCCAD/OCOR-DEV-REM-0052.json`, README, voci `NCR-C4-001`–`004` da `OPEN`
    a `IN_REMEDIATION`, indice di tracciabilità inversa, richiesta decisa `NCP-U05-FUSEKI-SHACL-SERVICE` (`3cf255b`);
  - riqualifiche previste, tutte di sola regressione (confermate dal validatore della deriva dopo l'allowlist):
    `OCOR-DEV-0037`, `0038`, `0039` (test riallineati o adattati, nessun requisito legabile secondo
    `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`), `0073`, `0074`, `0075`, `0077`, `0078`, `0079`
    (`deploy/bootstrap/compose.yaml`), `0005`, `0050`, `0082` (allowlist).
- Resta da fare: l'attuazione della decisione sulla richiesta aperta `NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY`
  (il gate `scripts/validate_language_policy.py` rifiuta `deploy/bootstrap/fuseki/config.ttl`), le divergenze
  dell'inventario (quesiti B e C), PRE-CAMPAIGN-GATE, revisione preventiva con le eventuali correzioni, campagna
  completa con le 12 riqualifiche, verifica indipendente, sigillo, merge e state sync. Le iterazioni previste per
  questo residuo sono 4 senza cicli di riparazione (attuazione e quesito B; gate e revisione preventiva; campagna
  e candidato; integrazione), fino a 2 in più con i cicli di riparazione ammessi dopo una verifica `NO_GO`.
- Divergenze nuove dell'inventario dei consumer (punto 5 del programma: «le divergenze nuove si aggiungono come
  `OPEN`»):
  - `ocor-runtime/src/ocor_runtime/c4/object_projection.py` righe 97-103 (`_typed`): con TypeDB irraggiungibile
    la proiezione degli oggetti risponde `CONTROL_PLANE_UNAVAILABLE`. ADD v1.3 riga 3406 prescrive «Projection
    down: `PROJECTION_NOT_READY`» e la riga 1364 il contesto servito nel `Problem`. Lo fissa il test
    `test_object_projection_unreachable_is_typed` di `ocor-runtime/tests/tasks/test_ocor_dev_rem_0049.py`
    righe 1421-1425 (asserzione della riga 1425);
  - `ocor-runtime/src/ocor_runtime/c2/gateway.py` righe 379-380: il catch-all del Gateway trasforma in
    `CONTROL_PLANE_UNAVAILABLE` anche `TypeDBUnavailableError` (motivo `PROJECTION_NOT_READY`, con il watermark
    confermato nel ledger durevole) della porta del watermark, invece di costruire `PROJECTION_NOT_READY` con il
    contesto servito (ADD v1.3 righe 1364 e 3406).
  Requisiti: `NFR-024` (Register v1.1 riga 180) e
  `NFR-077` (riga 403), P0 PoC: per la regola di gravità del registro le due voci sono `HIGH` e richiedono un
  `plan_unit` (`reports/tests/test_normative_conformance_register.py` righe 281-299); una voce `OPEN` con
  `plan_unit` deve stare nel `resolves` di quell'unità (riga 359). Né `object_projection.py` né
  `c2/gateway.py` sono nel `code_paths` di NCP-U05, e il piano non autorizza per NCP-U05 riallineamenti di
  `test_ocor_dev_rem_0049.py`.
- Ambito di `BA-03`: il pianificatore di consistenza di C2 risponde `PROJECTION_NOT_READY` a un
  `EXACT_AT_COMMIT(Cn)` superato delle sei operazioni sugli oggetti (`test_ocor_dev_rem_0049.py` righe 391-393).
  ADD v1.3 riga 356 lega la sandbox di `BA-03` alle «query logiche nominate»; la riga 1366 prescrive
  `UNSUPPORTED_CAPABILITY` quando il ruolo ha disposizione `emulated` e l'emulazione non è disponibile; LLD v1.1 riga 369, oracolo di `BA-03`: «TypeDB exact-at-commit o `PROJECTION_NOT_READY`, mai
  downgrade». La norma non dice se le sei operazioni sugli oggetti siano query logiche nominate.

## Opzioni

### Opzioni del quesito A

A1. **Fino a sei iterazioni oltre la sesta (raccomandata).** Per `OCOR-DEV-REM-0052` sono autorizzate fino a sei
    iterazioni oltre la sesta, solo per il residuo descritto nel contesto e per quanto decidono i quesiti B e C:
    quattro per il ciclo senza riparazioni e due per i cicli di riparazione ammessi dopo una verifica `NO_GO`. Se
    finiscono senza merge, l'unità si ferma e apre una decision request di livello normativo con lo stato del
    lavoro, senza chiedere altre iterazioni. Effetto: l'unità arriva al merge con il lavoro già fatto; le unità
    successive di `plan_order` attendono fino ad allora.
A2. **Fino a tre iterazioni oltre la sesta.** Come A1, con tre iterazioni (come per `REM-0044-ITERATION-LIMIT`).
    Effetto: basta per il ciclo senza riparazioni solo se il quesito B non allarga l'ambito (B2 o B3); una
    verifica `NO_GO` porta di nuovo a questa richiesta.
A3. **Sospensione dell'unità.** NCP-U05 si ferma al head `3cf255b`, senza candidato; il branch resta. Le unità
    successive di `plan_order` che non dipendono da NCP-U05 partono (NCP-U07 dipende solo da NCP-U04). Effetto:
    le voci `NCR-C4-001`–`004` restano `OPEN` su `main` e i task G6 che esse bloccano restano bloccati; la ripresa
    di NCP-U05 richiede una nuova decisione.

### Opzioni del quesito B

B1. **Due voci nuove risolte da NCP-U05 (raccomandata).** Il registro riceve due voci `OPEN` di gravità `HIGH`,
    componente C4 e C2, con `plan_unit` `NCP-U05`, requisiti `NFR-024` e `NFR-077`, ancore normative ADD v1.3
    righe 1364 e 3406, e `blocks` uguale a quello di `NCR-C4-003`. `plan_units.NCP-U05.resolves`, i criteri e i
    test RED dell'unità le comprendono; `ocor-runtime/src/ocor_runtime/c4/object_projection.py` e
    `ocor-runtime/src/ocor_runtime/c2/gateway.py` entrano nel `code_paths` dell'unità. La proiezione degli oggetti
    irraggiungibile risponde `PROJECTION_NOT_READY`; il Gateway costruisce `PROJECTION_NOT_READY` con il contesto
    servito dal watermark confermato. È autorizzato il riallineamento (caso 1 del punto 5, con RED)
    dell'asserzione di `test_ocor_dev_rem_0049.py` riga 1425 da `CONTROL_PLANE_UNAVAILABLE` a
    `PROJECTION_NOT_READY`; le risposte malformate restano `CONTROL_PLANE_UNAVAILABLE` (righe 1406-1418
    invariate), come il guasto del backend del marking (`test_ncr_c2_006_backend_failure_is_a_typed_problem`, ADD v1.3 riga 174). Se il RED mostra altri
    test che fissano il vecchio esito, serve una nuova decision request. Effetto: le divergenze si chiudono
    nell'unità che ha introdotto il ledger del watermark da cui il contesto servito si costruisce; una sola
    riqualifica in più, di sola regressione, di `OCOR-DEV-0034`, il cui ultimo record di evidenza ha fra gli input
    `ocor-runtime/src/ocor_runtime/c2/gateway.py` (nessun ultimo record ha fra gli input `object_projection.py` o
    `test_ocor_dev_rem_0049.py`; calcolo con la selezione del record più recente di
    `scripts/validate_evidence_input_drift.py` su `main` `b3da83f`).
B2. **Due voci nuove assegnate a un'unità nuova.** Le stesse due voci entrano nel registro con `plan_unit`
    `NCP-U14`, un'unità nuova in coda a `plan_order` (dopo NCP-U12), con lo stesso ambito di B1. NCP-U05 non le
    tocca. Effetto: NCP-U05 resta nel suo `code_paths` e non riqualifica `OCOR-DEV-0034`; il piano approvato riceve un'unità in più e le due voci
    `HIGH` restano aperte fino ad allora, insieme ai task G6 che bloccano.
B3. **Nessuna voce nuova.** Le due divergenze restano un'osservazione del record dell'unità. Effetto: contrasta
    con il punto 5 del programma («le divergenze nuove si aggiungono come `OPEN`»); la qualifica G6 di `NFR-024` e
    `NFR-077` le troverebbe comunque.

### Opzioni del quesito C

C1. **Le sei operazioni sugli oggetti non sono query logiche nominate (raccomandata).** La sandbox di `BA-03`
    serve le query logiche nominate del port di proiezione TypeDB, come attuato in `NCR-C4-004`; per le sei
    operazioni sugli oggetti il pianificatore continua a rispondere `PROJECTION_NOT_READY` a un
    `EXACT_AT_COMMIT(Cn)` superato, che è uno dei due esiti dell'oracolo di LLD v1.1 riga 369, e non degrada mai.
    Il record dell'unità registra l'interpretazione. Effetto: nessun codice né test cambia.
C2. **Le sei operazioni sugli oggetti sono query logiche nominate.** Il registro riceve una voce `OPEN` nuova
    (C2, `FR-057`, ADD v1.3 righe 356 e 1366) con `plan_unit` `NCP-U05`: il pianificatore serve
    `EXACT_AT_COMMIT(Cn)` delle sei operazioni da una sandbox a Cn, o `UNSUPPORTED_CAPABILITY` se l'emulazione non
    è disponibile; è autorizzato il riallineamento di `test_ocor_dev_rem_0049.py` righe 391-393. Effetto: più
    lavoro in NCP-U05 (con A1 le sei iterazioni restano il limite), un nuovo percorso di sandbox in C2.

**Raccomandazione**: A1, B1 e C1. A1 porta al merge il lavoro già GREEN con un margine per i cicli di
riparazione e un limite fisso; B1 chiude le due divergenze nuove nel componente e con il ledger che le rende
risolvibili, con un solo riallineamento autorizzato; C1 segue la lettera di ADD v1.3 riga 356 («query logiche
nominate») e l'oracolo di LLD v1.1 riga 369, senza allargare l'emulazione a percorsi che la norma non nomina.

## Impatto e task bloccati

- Bloccati fino alla decisione: la prosecuzione di `OCOR-DEV-REM-0052` oltre la sesta iterazione e, di
  conseguenza, le unità successive di `plan_order` (NCP-U07, U08, U09, U10, U11, U12), che partono una alla volta
  dopo NCP-U05. Resta aperta, indipendente da questa, la richiesta `NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY`.
- Con B1 o C2 cambiano soltanto, oltre al codice dell'unità, le voci nuove e i campi `resolves`, criteri, test RED
  e `code_paths` di NCP-U05 nel registro e l'asserzione autorizzata di `test_ocor_dev_rem_0049.py`. Nessun limite,
  soglia, workflow, guard, contratto, schema o registro normativo cambia. Claim invariati: `E1=0`, `E2=0`,
  `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
