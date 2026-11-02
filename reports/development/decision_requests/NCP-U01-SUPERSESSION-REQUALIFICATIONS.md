# NCP-U01-SUPERSESSION-REQUALIFICATIONS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda l'unità `OCOR-DEV-REM-0047` (NCP-U01 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, branch `governed/ocor-dev-rem-0047-ncp-u01-c1-conformance`, head di
codice `dda0eff19132`, PRE-CAMPAIGN-GATE 46/47 con la sola deriva attesa). Aperta secondo il punto 6
(«Stop») di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`: le due riqualifiche con supersession che
`NCP-U01-RETAINED-C1-BUILDERS (2026-11-01)` punto 5 prescrive non si possono produrre conformi alle regole
che `REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)` punto 2 impone a una riqualifica qualificante,
senza modificare test che né il piano né le decisioni autorizzano a cambiare (quesito A); e le riqualifiche di
sola regressione di `0028`, `0031` e `0033` non superano il controllo della classe di regressione, perché i
record che superano non hanno `record_id` (quesito B). Implementatore: Claude Code (Anthropic), implementatore
di riserva del loop.

## Quesito A: riqualifiche con supersession di `0011` e `0032`

### Contesto

- `NCP-U01-RETAINED-C1-BUILDERS` punto 5 (file della decision request, riga 119): «Con supersession:
  `OCOR-DEV-0011` e `0032`, come nel piano. `0028` e `0033` non hanno riqualifica con supersession, perché i
  loro test non cambiano». Le altre riqualifiche (`0005`, `0028`, `0031`, `0033`, `0050`, `0082`) sono di sola
  regressione, nella classe non qualificante.
- `REM-0046-REGRESSION-REQUALIFICATION-RECORDS` punto 2 (riga 90 della decision request): una riqualifica con
  supersession «è invece qualificante e segue tutte le regole della condizione 1» del punto 3 di
  `NORMATIVE-CONFORMANCE-PLAN`. La condizione 1 è applicata da `scripts/validate_runtime_evidence.py`
  (`check_new_record`, righe 298-342) a ogni record nuovo che non è della classe di regressione:
  - servono `requirement_results` con il pacchetto di NFR-004 / LLD v1.1 §7.3 (riga 303);
  - ogni requisito deve essere fra i `requirement_ids` del task nel backlog (riga 321);
  - ogni requisito deve essere **dichiarato nel sorgente del test** del caso: funzione, decoratori o docstring
    del modulo; i legami dell'indice di tracciabilità inversa non valgono (riga 338);
  - un requisito con metodo di test (`AUTOMATED_TEST` o `MIXED`) senza test è rifiutato (riga 340).
- I due task:
  - `OCOR-DEV-0011` ha un solo requisito, `BR-003` (backlog, riga 2033; Register v1.1 riga 18, metodo
    «test/dimostrazione», quindi `MIXED`). `ocor-runtime/tests/tasks/test_ocor_dev_0011.py` (243 righe) non
    dichiara alcun requisito: non ha docstring di modulo e nessun identificativo `BR-`/`FR-`/`NFR-`.
  - `OCOR-DEV-0032` ha 18 requisiti (backlog, riga 4836). `ocor-runtime/tests/tasks/test_ocor_dev_0032.py`
    (263 righe) non ne dichiara alcuno. L'unico requisito con metodo non di test è `FR-022` («Ispezione
    automatizzata»), che il test di `0032` non riguarda.
  - Gli ultimi record (`reports/evidence/G1/OCOR-DEV-0011.requalified-rem0039.json`,
    `reports/evidence/G4/OCOR-DEV-0032.requalified.json`) sono record sigillati prima di REM-0046 con un caso
    `BR-003` generico; per il punto 3 condizione 2 non contano come evidenza per `OCOR-DEV-0067`.
- Un record qualificante di `0011` o `0032` conforme alla condizione 1 richiede quindi di dichiarare requisiti
  nei due moduli di test. Il piano (`plan_units.NCP-U01.existing_tests_to_realign_or_adapt`) elenca solo
  `test_ocor_dev_0028.py:81`, che `NCP-U01-RETAINED-C1-BUILDERS` punto 2 ha escluso; il punto 7 del programma
  vieta ogni altra modifica di test e il punto 6 («Stop») impone di fermarsi. È la stessa scelta che
  `REM-0046-REGRESSION-REQUALIFICATION-RECORDS` opzione 2 («dichiarare i requisiti nei test rieseguiti») ha
  posto e che il PO non ha scelto.
- Le modifiche di NCP-U01 che fanno derivare i due task sono `NCR-C1-009` in `c1/ports.py` (versione SemVer in
  `CompilerRequest`) per `0011` e `NCR-C1-008` in `c1/frontend.py` (`references` ordinato e senza duplicati)
  per `0032`. I test di `0011` e `0032` passano invariati all'head `dda0eff19132` (87 passed insieme agli altri
  consumer di C1). Il comportamento nuovo è qualificato dai test dell'unità
  `ocor-runtime/tests/tasks/test_ocor_dev_rem_0047.py::test_ncr_c1_008_conforms` e `::test_ncr_c1_009_conforms`,
  che dichiarano (con la docstring del modulo) fra gli altri `NFR-018` e `FR-040`.

### Opzioni del quesito A

A1. **Riqualifiche di `0011` e `0032` nella classe di regressione (raccomandata).** I record
   `.requalified-rem0047` di `0011` e `0032` hanno `requalification_kind: "regression"`,
   `qualifies_requirements: false`, nessun caso legato a requisiti e `supersedes` verso l'ultimo record del
   task, come quelli di `0005`, `0028`, `0031`, `0033`, `0050` e `0082`. I test non cambiano. L'evidenza dei
   requisiti di `0011` e `0032` resta quella della catena (oggi record sigillati esclusi per `0067`); la
   qualifica dei requisiti di C1 che NCP-U01 realizza viene dai casi dell'unità e dai task G6. Nessun effetto
   sull'head di codice.
A2. **Riqualifiche qualificanti con dichiarazione dei requisiti nei test.** Si aggiunge ai moduli
   `test_ocor_dev_0011.py` e `test_ocor_dev_0032.py` una docstring che dichiara i requisiti legati (con
   confronto dell'albero sintattico: stesse funzioni, asserzioni e parametrizzazioni); i record hanno casi con
   il pacchetto completo di NFR-004 per ogni requisito dichiarato, compresa l'evidenza del metodo per i
   requisiti `MIXED` (`BR-003` e gli altri). Cambia l'head di codice: nuova campagna, nuovo
   PRE-CAMPAIGN-GATE e riqualifica di ogni task il cui ultimo record ha fra gli input i due moduli.
A3. **Riqualifiche qualificanti legate ai test dell'unità.** Il record di `0032` lega solo i requisiti del task
   che i test di `test_ocor_dev_rem_0047.py` dichiarano (`FR-024`, `FR-040`, `FR-041`, `FR-042`, `FR-044`,
   `NFR-018`) ai casi di quel modulo; `0011` (`BR-003`, non dichiarato da alcun test) resta comunque di
   regressione. Lega l'evidenza di un task a test di un'altra unità, che non sono quelli del task.

**Raccomandazione**: opzione A1. È la lettura che non richiede modifiche di test non autorizzate né legami
artificiosi; non allenta nulla: i test di `0011` e `0032` sono rieseguiti sullo stack reale all'head della
campagna e il record attesta che reggono; non estende l'evidenza dei requisiti (punto 3 di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS`). Lascia invariato l'head di codice. Con A1 i due record superano `check_regression_record`: i record
che superano (`OCOR-DEV-0011-requalified-rem0039-95e89f7a16e5`, `OCOR-DEV-0032-requalified-b920411a8aa5`) hanno
`record_id`.

## Quesito B: catena `supersedes` delle riqualifiche di sola regressione di `0028`, `0031` e `0033`

### Contesto

- `REM-0046-REGRESSION-REQUALIFICATION-RECORDS` punto 1: il record di regressione «ha `supersedes` verso il
  record precedente dello stesso task». `scripts/validate_runtime_evidence.py` (`check_regression_record`,
  righe 248-272) lo realizza così: `supersedes` uguale a `previous_record.record_id`, e il record in
  `previous_record.record_path` (con `record_sha256`) deve avere **lo stesso `record_id`** e lo stesso `task_id`.
- Gli ultimi record di `0028`, `0031` e `0033` (selezionati come fa `scripts/validate_evidence_input_drift.py`)
  sono i record originali sigillati `reports/evidence/G3/OCOR-DEV-0028.json`,
  `reports/evidence/G3/OCOR-DEV-0031.json` e `reports/evidence/G4/OCOR-DEV-0033.json`: non hanno `record_id` né
  `status`. Sono nel registro dei record sigillati
  (`reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json`, per percorso e sha256, `conforming: false`).
- Prova eseguita all'head `dda0eff19132` con il validatore invariato, su record sintetici fuori dal repository:
  per `0005`, `0050`, `0082`, `0011` e `0032` il controllo passa; per `0028`, `0031` e `0033` fallisce con
  «regression requalification record does not supersede a record: record_id mismatch», qualunque valore abbia
  `supersedes`. I record sigillati non si modificano.
- `0028` e `0033` derivano per le docstring che `NCP-U01-RETAINED-C1-BUILDERS` punto 2 prescrive in
  `c1/compiler.py` e `c1/releases.py`; `0031` non deriva, ma il punto 5 lo nomina (lettura più restrittiva già
  registrata nel record dell'unità). Senza i tre record il validatore di deriva resta in FAIL e l'unità non si
  integra.
- Nessun record più recente di un task completato ha fra gli `inputs` `scripts/validate_runtime_evidence.py` o
  `reports/tests/test_runtime_evidence_validator.py`: una modifica dei due file non fa derivare altri task.

### Opzioni del quesito B

B1. **Identità del record sigillato senza `record_id` (raccomandata).** In `check_regression_record`, solo
   quando il record superato è un record sigillato riconosciuto dal registro per percorso e sha256 e non ha
   `record_id`, `supersedes` e `previous_record.record_id` devono essere uguali al percorso
   `previous_record.record_path`; restano obbligatori `record_sha256`, lo stesso `task_id` e ogni altra
   regola. Un record non sigillato senza `record_id`, o un percorso diverso, resta rifiutato. La modifica
   entra nel change set di NCP-U01 con RED/GREEN in `reports/tests/test_runtime_evidence_validator.py` (casi
   positivi e negativi: record sigillato senza `record_id` accettato con il percorso; percorso diverso,
   sha256 diverso, record non sigillato senza `record_id`, `task_id` diverso rifiutati) e con l'allowlist del
   piano invariata. Nessun altro cambio del validatore.
B2. **Nessuna riqualifica di `0028`, `0031` e `0033` in NCP-U01.** Le docstring di `compiler.py` e
   `releases.py` del punto 2 passano all'unità del ritiro (`NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT`), così
   `0028` e `0033` non derivano; `0031` non si riqualifica. Cambia il punto 2 della decisione del 2026-11-01.
B3. **Record di regressione con un campo d'identità aggiuntivo.** Il validatore accetta, per i soli record
   sigillati senza `record_id`, un'identità derivata (`<task_id>@sha256:<record_sha256>`) in `supersedes`.
   Equivalente a B1 per rigore, con un formato in più da documentare.

**Raccomandazione**: opzione B1. Mantiene il punto 2 della decisione del 2026-11-01, non tocca record
sigillati né test di altri task, non allenta il controllo (percorso e sha256 del record superato sono già
vincolanti e il registro limita l'eccezione ai record sigillati), non fa derivare altri task.

## Impatto e lavoro bloccato

- Bloccati solo i record di riqualifica di `0011`, `0032` (quesito A) e di `0028`, `0031`, `0033`
  (quesito B), quindi il candidato, la richiesta di verifica `REMEDIATION` e l'integrazione di
  `OCOR-DEV-REM-0047`. Le unità successive del piano partono solo dopo
  l'integrazione di NCP-U01 (ordine di `plan_order`).
- Ogni opzione del quesito B cambia l'head di codice (validatore con B1/B3, docstring con B2), e così A2:
  servono un nuovo PRE-CAMPAIGN-GATE e una nuova campagna sull'head che applica la decisione. La campagna
  eseguita in questa iterazione sull'head `dda0eff19132` resta un'esecuzione documentata della suite completa
  a quell'head, non l'evidenza del candidato.
- Iterazioni di NCP-U01: 6 su una stima di 4 (stop a 8, punto 1 di `NORMATIVE-CONFORMANCE-PLAN`).
  L'applicazione della decisione richiede almeno un'iterazione (RED/GREEN, gate, campagna, record) e una per
  l'integrazione dopo il verdetto: il PO può indicare se il limite resta 8.

Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.

## Disposition del Product Owner — 2026-11-02

Decisione normativa del PO `NCP-U01-SUPERSESSION-REQUALIFICATIONS (2026-11-02)`: opzioni A1 (riqualifiche di `OCOR-DEV-0011` e `0032` di sola regressione) e B1 (record sigillati senza `record_id` superati per percorso, con RED/GREEN del validatore), con le aggiunte dei punti 3–5 (A1 per tutte le unità del programma; riqualifica qualificante per i test cambiati di un task chiuso; limite di iterazioni di NCP-U01 portato a 10). Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. La richiesta decisa è il file al commit `ace1e55`, sha256 `fa9e06fc2039d4f720da5ee9dda1061e3ad418a18e79440af17f48c1f106f45f`. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U01-SUPERSESSION-REQUALIFICATIONS (2026-11-02) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita, sulla decision request `NCP-U01-SUPERSESSION-REQUALIFICATIONS` (`reports/development/decision_requests/NCP-U01-SUPERSESSION-REQUALIFICATIONS.md`, PR #444, commit `ace1e55`, sha256 `fa9e06fc2039d4f720da5ee9dda1061e3ad418a18e79440af17f48c1f106f45f`). Il PO sceglie le opzioni A1 e B1, con le aggiunte dei punti 3–5. Integra `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, `REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)` e `NCP-U01-RETAINED-C1-BUILDERS (2026-11-01)`. Nessun nuovo `DEC-*`. Restano invariati ADD, LLD, contratti, schemi, registri normativi e claim.

1. **Quesito A, opzione A1.** Le riqualifiche di `OCOR-DEV-0011` e `0032` in NCP-U01 sono di sola regressione, nella classe non qualificante di `REM-0046-REGRESSION-REQUALIFICATION-RECORDS`, come quelle di `0005`, `0028`, `0031`, `0033`, `0050` e `0082`. Sostituisce la frase «Con supersession: `OCOR-DEV-0011` e `0032`» del punto 5 di `NCP-U01-RETAINED-C1-BUILDERS`. I test di `0011` e `0032` non cambiano. Il comportamento nuovo di `NCR-C1-008` e `NCR-C1-009` è qualificato dai test dell'unità.
2. **Quesito B, opzione B1.** In `check_regression_record` di `scripts/validate_runtime_evidence.py`, solo quando il record superato è un record sigillato riconosciuto da `reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json` per percorso e sha256 e non ha `record_id`, `supersedes` e `previous_record.record_id` sono uguali a `previous_record.record_path`. Restano obbligatori `record_sha256`, lo stesso `task_id` e ogni altra regola. Un record non sigillato senza `record_id`, un percorso diverso o una sha256 diversa restano rifiutati. La modifica entra nel change set di NCP-U01 con RED/GREEN e con casi positivi e negativi in `reports/tests/test_runtime_evidence_validator.py`, solo per aggiunta. Nessun'altra modifica del validatore. Vale per ogni unità successiva.
3. **A1 per tutte le unità del programma.** La riqualifica di un task chiuso i cui test l'unità non cambia è sempre di sola regressione, nella classe non qualificante, anche dove il piano o una decisione la indicano «con supersession».
4. **Test cambiati di un task chiuso.** Quando un'unità riallinea o adatta test di un task chiuso secondo il punto 5 della decisione sul piano, la riqualifica di quel task è qualificante e segue la condizione 1 del punto 3. L'unità può aggiungere al modulo di quei test una docstring che dichiara solo i requisiti del task che quei test esercitano davvero, ciascuno con la sua ancora normativa. Il confronto dell'albero sintattico mostra, oltre alle modifiche autorizzate, solo quella docstring. Un requisito del task che i test non esercitano non si dichiara: resta senza evidenza qualificante dal task e lo qualificano i task G6.
5. **Limite di iterazioni di NCP-U01:** lo stop con decision request passa da 8 a 10 iterazioni.
6. **Registrazione.** Al primo state sync registra questa decisione come disposition nel file della decision request, secondo `AGENTS.md`, e nell'`ITERATION_LOG.md`. Se il validatore del piano non ammette il file in un change set di solo stato, il file entra in `main` con il change set di NCP-U01. Poi riprendi `OCOR-DEV-REM-0047`: modifica del validatore, nuovo PRE-CAMPAIGN-GATE, campagna sull'head che applica la decisione, record di riqualifica e richiesta di verifica.
