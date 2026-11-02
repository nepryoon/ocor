# NCP-U01-SUPERSESSION-REQUALIFICATIONS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda l'unità `OCOR-DEV-REM-0047` (NCP-U01 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, branch `governed/ocor-dev-rem-0047-ncp-u01-c1-conformance`, head di
codice `dda0eff19132`, PRE-CAMPAIGN-GATE 46/47 con la sola deriva attesa). Aperta secondo il punto 6
(«Stop») di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`: le due riqualifiche con supersession che
`NCP-U01-RETAINED-C1-BUILDERS (2026-11-01)` punto 5 prescrive non si possono produrre conformi alle regole
che `REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)` punto 2 impone a una riqualifica qualificante,
senza modificare test che né il piano né le decisioni autorizzano a cambiare. Implementatore: Claude Code
(Anthropic), implementatore di riserva del loop.

## Contesto

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

## Opzioni

1. **Riqualifiche di `0011` e `0032` nella classe di regressione (raccomandata).** I record
   `.requalified-rem0047` di `0011` e `0032` hanno `requalification_kind: "regression"`,
   `qualifies_requirements: false`, nessun caso legato a requisiti e `supersedes` verso l'ultimo record del
   task, come quelli di `0005`, `0028`, `0031`, `0033`, `0050` e `0082`. I test non cambiano. L'evidenza dei
   requisiti di `0011` e `0032` resta quella della catena (oggi record sigillati esclusi per `0067`); la
   qualifica dei requisiti di C1 che NCP-U01 realizza viene dai casi dell'unità e dai task G6. Nessun effetto
   sull'head di codice: la campagna in corso su `dda0eff19132` resta valida.
2. **Riqualifiche qualificanti con dichiarazione dei requisiti nei test.** Si aggiunge ai moduli
   `test_ocor_dev_0011.py` e `test_ocor_dev_0032.py` una docstring che dichiara i requisiti legati (con
   confronto dell'albero sintattico: stesse funzioni, asserzioni e parametrizzazioni); i record hanno casi con
   il pacchetto completo di NFR-004 per ogni requisito dichiarato, compresa l'evidenza del metodo per i
   requisiti `MIXED` (`BR-003` e gli altri). Cambia l'head di codice: nuova campagna, nuovo
   PRE-CAMPAIGN-GATE e riqualifica di ogni task il cui ultimo record ha fra gli input i due moduli.
3. **Riqualifiche qualificanti legate ai test dell'unità.** Il record di `0032` lega solo i requisiti del task
   che i test di `test_ocor_dev_rem_0047.py` dichiarano (`FR-024`, `FR-040`, `FR-041`, `FR-042`, `FR-044`,
   `NFR-018`) ai casi di quel modulo; `0011` (`BR-003`, non dichiarato da alcun test) resta comunque di
   regressione. Lega l'evidenza di un task a test di un'altra unità, che non sono quelli del task.

**Raccomandazione**: opzione 1. È la lettura che non richiede modifiche di test non autorizzate né legami
artificiosi; non allenta nulla: i test di `0011` e `0032` sono rieseguiti sullo stack reale all'head della
campagna e il record attesta che reggono; non estende l'evidenza dei requisiti (punto 3 di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS`). Lascia invariato l'head di codice.

## Impatto e lavoro bloccato

- Bloccati solo i record di riqualifica di `0011` e `0032`, quindi il candidato, la richiesta di verifica
  `REMEDIATION` e l'integrazione di `OCOR-DEV-REM-0047`. Le unità successive del piano partono solo dopo
  l'integrazione di NCP-U01 (ordine di `plan_order`).
- Non bloccati: la campagna di qualifica sull'head `dda0eff19132` (in corso), le riqualifiche di sola
  regressione di `0005`, `0028`, `0031`, `0033`, `0050`, `0082` e il completamento del record dell'unità,
  comuni alle opzioni 1 e 3 (con l'opzione 2 vanno rifatti sul nuovo head).
- Iterazioni di NCP-U01: 6 su una stima di 4 (stop a 8, punto 1 di `NORMATIVE-CONFORMANCE-PLAN`).

Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
