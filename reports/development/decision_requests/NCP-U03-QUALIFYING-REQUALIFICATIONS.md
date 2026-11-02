# NCP-U03-QUALIFYING-REQUALIFICATIONS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0049`
(NCP-U03 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, C2 Named Query Gateway; branch
`governed/ocor-dev-rem-0049-ncp-u03-c2-gateway`, head di codice `511091f`, dopo le correzioni della revisione
preventiva). Aperta secondo il punto 6 («Stop») di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`: cinque delle
sette riqualifiche che l'unità deve produrre come qualificanti non si possono produrre conformi alla condizione 1
del punto 3 di `NORMATIVE-CONFORMANCE-PLAN`, perché i task non hanno alcun requisito che i loro test possano
dichiarare e provare. Implementatore: Claude Code (Anthropic), implementatore di riserva del loop.

## Contesto

- `NCP-U01-SUPERSESSION-REQUALIFICATIONS (2026-11-02)` punto 4 (file
  `reports/development/decision_requests/NCP-U01-SUPERSESSION-REQUALIFICATIONS.md`, sezione della disposition):
  quando un'unità riallinea o adatta test di un task chiuso, «la riqualifica di quel task è qualificante e segue
  la condizione 1 del punto 3»; l'unità può aggiungere al modulo una docstring che dichiara «solo i requisiti
  del task che quei test esercitano davvero»; «un requisito del task che i test non esercitano non si dichiara».
  Il punto 3 della stessa decisione rende di sola regressione solo le riqualifiche di task i cui test l'unità
  non cambia.
- NCP-U03 riallinea o adatta, come prevedono il piano e il punto 5 di `NORMATIVE-CONFORMANCE-PLAN`, i test di
  sette task chiusi (elenco nel record dell'unità,
  `reports/assurance/OCOR-DEV-REM-0049-RCCAD/OCOR-DEV-REM-0049.json`, campo
  `existing_tests_realigned_or_adapted`): `ocor-runtime/tests/tasks/test_ocor_dev_0012.py`, `0017`, `0034`,
  `0035`, `0037`, `0039` e `ocor-runtime/tests/mission_thread/test_first_governed_slice.py` (task
  `OCOR-DEV-0031`). Le sette riqualifiche sono quindi qualificanti per il punto 4.
- La condizione 1 è applicata da `scripts/validate_runtime_evidence.py`, `check_new_record` (righe 308-352),
  a ogni record nuovo che non è della classe di regressione:
  - senza `requirement_results` il record è rifiutato (riga 313);
  - ogni requisito legato deve essere fra i `requirement_ids` del task nel backlog (riga 331);
  - ogni requisito deve essere dichiarato nel sorgente del test del caso: funzione, decoratori o docstring del
    modulo (riga 348);
  - un requisito con metodo misto o non di test richiede l'evidenza del suo metodo del Register (riga 352;
    `method_kind`, righe 142-155: ispezione, dimostrazione, benchmark o audit non sono provati da un caso di
    test automatico, NCP-S08).
- Requisiti dei sette task (`docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json`, voci alle righe 2165,
  2829, 4689, 5129, 5283, 5555, 5822) e metodo del Register
  (`ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md`):
  - `OCOR-DEV-0012`, `0017`, `0031`, `0035`, `0037`: un solo requisito, `BR-003` («Continuità end-to-end»,
    Register riga 18), metodo «test/dimostrazione», quindi misto. Nessun caso di test automatico prova la parte
    di dimostrazione, e i test di quei moduli (porte di C2, adapter TypeDB, pianificazione, mission thread) non
    producono un artefatto di dimostrazione. Un record qualificante di questi cinque task non ha alcun requisito
    legabile: senza casi è rifiutato alla riga 313.
  - `OCOR-DEV-0034`: 17 requisiti. Fra quelli con metodo di solo test, i test riallineati di
    `test_ocor_dev_0034.py` esercitano in parte `NFR-034` (Register riga 257: query arbitrarie ai backend
    «negati e auditati»; i test ne verificano il rifiuto, non l'audit, che è asserito dai test dell'unità) e
    `NFR-040` (Register riga 296: enforcement centrale e non-leakage; i test verificano il rifiuto per marking
    o clearance senza alcuna risposta). Gli altri requisiti non sono esercitati o hanno metodo misto o
    benchmark.
  - `OCOR-DEV-0039`: `BR-003`, `FR-019` (release Future), `FR-138`, `FR-148`, `NFR-024` (metodo «test,
    ispezione», misto). I test riallineati (rebuild, quarantena, deriva) non esercitano `FR-138` (mutazioni)
    né `FR-148` (release fence).
- I test dei sette moduli passano all'head `511091f` sullo stack reale (TypeDB, Fuseki, PostgreSQL). Il
  comportamento nuovo di C2 è qualificato dai test dell'unità in
  `ocor-runtime/tests/tasks/test_ocor_dev_rem_0049.py` (un test per voce risolta del registro, 122 casi), che
  nominano fra gli altri `FR-006`, `FR-007`, `FR-055`, `FR-057`, `FR-134`, `NFR-006`, `NFR-024`, `NFR-034`,
  `NFR-043`; i requisiti dei task restano qualificati dai task G6 (`OCOR-DEV-0060`, `0062`-`0067`).
- È lo stesso caso del quesito A di `NCP-U01-SUPERSESSION-REQUALIFICATIONS`, dove il PO ha scelto la classe di
  regressione (A1) per `0011` (solo `BR-003`) e `0032`; allora però i test dei due task non cambiavano, mentre
  qui cambiano per i riallineamenti autorizzati.

## Opzioni

1. **Sette riqualifiche nella classe di regressione (raccomandata).** I record `.requalified-rem0049` di
   `0012`, `0017`, `0031`, `0034`, `0035`, `0037` e `0039` hanno `requalification_kind: "regression"`,
   `qualifies_requirements: false`, nessun caso legato a requisiti e `supersedes` verso l'ultimo record del
   task, come quelli di `0005`, `0050` e `0082`. Ogni record elenca i test riallineati o adattati del task, con
   il confronto dell'albero sintattico. Nessuna docstring aggiunta, nessun test cambiato oltre ai riallineamenti
   già eseguiti: l'head di codice `511091f` resta quello della campagna. L'evidenza dei requisiti dei sette task
   resta quella della catena (`supersedes`); il comportamento nuovo è qualificato dai test dell'unità e i
   requisiti dai task G6. Vale solo per NCP-U03; il punto 4 di `NCP-U01-SUPERSESSION-REQUALIFICATIONS` resta in
   vigore per le altre unità.
2. **Riqualifica qualificante del solo `0034`, regressione per gli altri sei.** Si aggiunge a
   `ocor-runtime/tests/tasks/test_ocor_dev_0034.py` una docstring di modulo che dichiara `NFR-034` (Register
   riga 257) e `NFR-040` (Register riga 296), con il confronto dell'albero sintattico; il record di `0034` ha un
   caso per ciascuno dei due requisiti con il pacchetto completo di NFR-004 / LLD v1.1 §7.3, legato ai test che
   ne verificano il rifiuto. Gli altri sei record sono come nell'opzione 1. Cambia l'head di codice: nuovo
   PRE-CAMPAIGN-GATE e nuova campagna sull'head con la docstring. `NFR-034` resterebbe provato dal task solo
   per il rifiuto, non per l'audit.

**Raccomandazione**: opzione 1. Non richiede dichiarazioni di requisiti esercitati solo in parte né legami
artificiosi; non allenta nulla: i test dei sette task sono rieseguiti sullo stack reale all'head della campagna
e i record attestano che reggono; non estende l'evidenza dei requisiti (punto 3 di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS`). Lascia invariato l'head di codice, quindi la campagna su
`511091f` resta valida per il candidato.

## Impatto e lavoro bloccato

- Bloccati solo i record di riqualifica dei sette task, il completamento del record dell'unità, il candidato, la
  richiesta di verifica `REMEDIATION` e l'integrazione di `OCOR-DEV-REM-0049`. Le unità successive di
  `plan_order` (NCP-U04, U06, U05, U07-U12) partono solo dopo l'integrazione di NCP-U03.
- Con l'opzione 1 la campagna sull'head `511091f` è quella del candidato. Con l'opzione 2 serve una nuova
  campagna sull'head con la docstring.
- Iterazioni di NCP-U03: 2 su una stima di 4 (stop a 8, punto 1 di `NORMATIVE-CONFORMANCE-PLAN`).

Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
