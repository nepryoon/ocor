# NCP-U06-0004-REGRESSION-MANIFEST-VALIDATION

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0051`
(NCP-U06 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, backbone C5; branch
`governed/ocor-dev-rem-0051-ncp-u06-c5-backbone`, head sigillato `f3016143774d374e038fa517e1fa110e8255d75e`,
PR #480). Aperta secondo il punto 5 di `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`, che rende obbligatoria
una decision request «per modificare un validatore», e secondo il paragrafo 5 punto 8 di
`CC-OCOR-DELIVERY-COMPLETION` (fallimento reale di un check obbligatorio sull'HEAD esatto). Implementatore:
Claude Code (Anthropic), implementatore di riserva del loop.

## Contesto

- NCP-U06 attua il punto 7 delle dipendenze (confluent-kafka, dowhy, hypothesis: 46 pacchetti aggiunti in
  `ocor-runtime/uv.lock`, più `ocor-runtime/pyproject.toml`). Per questo i record più recenti di 19 task chiusi
  derivano su `uv.lock`/`pyproject.toml`, fra cui `OCOR-DEV-0004`. Secondo `REM-0046-REGRESSION-REQUALIFICATION-RECORDS
  (2026-10-30)` punti 1-2 e `NCP-U01-SUPERSESSION-REQUALIFICATIONS (2026-11-02)` (A1) la riqualifica di
  `OCOR-DEV-0004` è di sola regressione: `reports/evidence/G0/OCOR-DEV-0004.requalified-rem0051.json` ha
  `requalification_kind: "regression"`, `qualifies_requirements: false`, nessun `requirement_results`, nessuna
  riga del ledger di `reports/evidence/G0/MANIFEST.json` che lo nomina, e `supersedes`
  `OCOR-DEV-0004-requalified-rem0039-95e89f7a16e5` (record sigillato
  `reports/evidence/G0/OCOR-DEV-0004.requalified-rem0039.json`). Per la convenzione dei MANIFEST la nuova coppia
  di artefatti di `OCOR-DEV-0004` è inserita per prima (`reports/evidence/G0/MANIFEST.json` righe 23-32 all'head
  sigillato), davanti a quella di `rem0039` (righe 203-212) e a quella del primo `.requalified` (righe 393-402).
  L'unica riga del ledger di `OCOR-DEV-0004` (righe 508-516) resta legata al record di `rem0039`.
- Il verdetto indipendente `OCOR-DEV-REM-0051-18516d76f12c-0` è `GO_FOR_EVIDENCE_SEAL` senza finding; la
  validazione `scripts/validate_runtime_evidence.py --task OCOR-DEV-0004 --non-skipped --manifest
  reports/evidence/G0/MANIFEST.json` passa (applica `check_regression_record`, righe 248-281), come
  `scripts/validate_evidence_input_drift.py` (drift 0).
- Il job obbligatorio `evidence` di `.github/workflows/ocor-poc-ci.yml` (step «Reject missing, skipped or
  non-content-addressed evidence», righe 148-158) esegue anche
  `ocor-runtime/tools/evidence_manifest.py validate --task OCOR-DEV-0004 --non-skipped --manifest
  reports/evidence/G0/MANIFEST.json` (righe 157-158). `validate_manifest` (`ocor-runtime/tools/evidence_manifest.py`
  righe 198-254) prende il primo artefatto del task (riga 204), esige il campo `requirement_results` (righe
  224-229), almeno un caso (`_normalise_cases`, righe 62-64), `len(commands) == len(requirement_results)` (righe
  234-236) e righe del ledger che puntano proprio a quel record (righe 242-253). Il validatore è anteriore a
  REM-0046 e non conosce la classe di regressione.
- Esito sulla PR #480, HEAD esatto `f301614` (run 41785980610): `evidence` fallisce con
  `FAIL: evidence fields missing: requirement_results`, e di conseguenza `mandatory-gates`. Riproduzione locale
  deterministica sullo stesso HEAD: stesso messaggio, exit 1; la validazione per task di
  `validate_runtime_evidence.py` di `OCOR-DEV-0001`-`0006` passa.
- I due vincoli non sono soddisfacibili insieme da un record di sola regressione di `OCOR-DEV-0004` posto per
  primo: REM-0046 punto 1 vieta `requirement_results` e righe del ledger, `evidence_manifest.py validate` li
  esige. Nessuna unità dopo REM-0046 aveva ancora riqualificato `OCOR-DEV-0004`; il conflitto emerge ora per la
  prima volta. Il record sigillato non si modifica (si supersede).

## Opzioni

1. **Classe di regressione in `evidence_manifest.py validate` (raccomandata).** NCP-U06 estende il proprio
   ambito a `ocor-runtime/tools/evidence_manifest.py` (solo `validate_manifest`) con un ciclo di riparazione
   (RED, GREEN, nuova verifica indipendente). Quando il primo artefatto del task è un record con
   `requalification_kind: "regression"`, il validatore gli applica i controlli che non riguardano i requisiti
   (digest del record e del raw log, campi obbligatori tranne `requirement_results`, comandi tutti `PASS`,
   `result` `PASS`, nessun `requirement_results`, nessuna riga del ledger che lo nomina,
   `qualifies_requirements` esattamente `false`, `supersedes` uguale a `previous_record.record_id` e record
   superato dello stesso task con il digest dichiarato), poi segue la catena `supersedes` fino all'ultimo
   record non di regressione e gli applica senza modifiche tutti i controlli attuali, compresi cardinalità e
   percorsi del ledger (REM-0046 punto 3: l'evidenza dei requisiti resta quella dell'ultimo record
   qualificante). Un record non di regressione si valida esattamente come oggi. Casi positivi e negativi per
   ogni ramo in un nuovo file di test sotto `reports/tests/`, indicizzato nella tracciabilità inversa.
   Workflow, MANIFEST e record sigillati invariati. Effetto: `evidence_manifest.py` è un input di
   `OCOR-DEV-0004`, quindi il ciclo produce una nuova riqualifica di sola regressione di `OCOR-DEV-0004`
   (`.requalified-rem0051-r1`, `supersedes` verso il record sigillato `rem0051`) con nuovo record dell'unità
   del ciclo 1; una o due iterazioni in più per NCP-U06 (7 usate su stima 6, stop a 12).
2. **Ordine degli artefatti nel MANIFEST G0.** Nel ciclo di riparazione la coppia di artefatti
   `OCOR-DEV-0004.requalified-rem0051.*` si sposta dopo quella di `rem0039` in
   `reports/evidence/G0/MANIFEST.json`, senza altro cambiamento: `evidence_manifest.py validate` e
   `validate_runtime_evidence.py --task OCOR-DEV-0004` validano di nuovo il record qualificante di `rem0039`,
   mentre la catena `supersedes` (usata da `validate_evidence_input_drift.py` e da
   `--requirement-evidence`) continua a indicare `rem0051` come record più recente. Effetto: nessun codice
   cambia, ma il controllo per task di CI non valida più il record più recente di `OCOR-DEV-0004`, contro la
   convenzione «nuovi artefatti per primi» seguita da tutte le unità; la stessa deroga servirebbe a ogni
   futura riqualifica di regressione di `OCOR-DEV-0004`.
3. **Step del workflow.** Nel ciclo di riparazione le righe 157-158 di `.github/workflows/ocor-poc-ci.yml` si
   sostituiscono con una validazione di `OCOR-DEV-0004` che usa `scripts/validate_runtime_evidence.py`
   (che conosce la classe di regressione) per il record più recente e `evidence_manifest.py validate` per
   l'ultimo record qualificante, indicato esplicitamente. Effetto: cambia un workflow obbligatorio e la sua
   baseline di byte del guard di campagna; `evidence_manifest.py` resta ignaro della classe di regressione,
   per cui chiunque lo invochi sul MANIFEST attuale continua a fallire.

**Raccomandazione**: opzione 1. Attua nel secondo validatore di evidenza la stessa regola che REM-0046 punto 1
ha già introdotto in `validate_runtime_evidence.py`, senza allentare nulla: il ledger dei requisiti resta
validato per intero sull'ultimo record qualificante (REM-0046 punto 3) e il record di regressione riceve tutti i
controlli che non riguardano i requisiti. L'opzione 2 lascia il record più recente fuori dal controllo per
task e si ripeterebbe a ogni riqualifica; l'opzione 3 tocca un workflow obbligatorio e lascia il validatore
incoerente con la classe di regressione.

## Impatto e lavoro bloccato

- Bloccati: il merge della PR #480 e quindi l'integrazione di `OCOR-DEV-REM-0051` (NCP-U06): risoluzione di
  `NCR-C5-001`, `NCR-C5-002` e `NCR-C5-003` e ingresso in `main` del punto 7 delle dipendenze.
- Non bloccati: il branch sigillato e la PR #480 restano invariati; il verdetto `GO_FOR_EVIDENCE_SEAL` e il
  sigillo restano registrati. NCP-U05 (dipende solo da NCP-U03, già su `main`) è eseguibile, ma `plan_order`
  esegue un'unità alla volta.
- Iterazioni di NCP-U06: 7 su una stima di 6 (stop a 12, punto 1 di `NORMATIVE-CONFORMANCE-PLAN`); ciclo di
  riparazione 1 di 2.

Nessun nuovo `DEC-*`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
