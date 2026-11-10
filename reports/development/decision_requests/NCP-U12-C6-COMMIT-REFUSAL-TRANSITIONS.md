# NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS

Status: `DECIDED_BY_PO` (era `OPEN_PO_NORMATIVE_DECISION_REQUIRED`). Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0060`
(NCP-U12 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, test; branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, head
`689aff288c3fca00f32bbd501bbc1d99434e9966`) e la voce `NCR-TESTS-004` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Implementatore: Claude Code (Anthropic), implementatore di
riserva.

## Contesto

- La decisione `NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10)` adotta per `NCR-TESTS-004` l'opzione D1: per ogni codice
  chiuso senza un test negativo che lo asserisca, l'unità aggiunge nel suo modulo un test negativo che lo provoca sul
  componente mantenuto, «con RED dove il codice non è prodotto». La richiesta `NCP-U12-UNPRODUCED-REASON-CODES`
  (branch `governed/decision-request-ncp-u12-unproduced-reason-codes`, commit
  `92cdcc2949d9ee5a1135243f03b6919b3b5afd01`, ancora senza disposition) chiede che cosa avviene per otto codici non
  prodotti di C2, C6 e C7 e dichiara invece prodotti, «senza questione», i quattro codici di C6 sul percorso
  `ACT-T31a`/`ACT-T31b`: `PRECONDITION_FAILED`, `INVARIANT_VIOLATION`, `REVISION_CONFLICT` e `GATE_PACKAGE_MISMATCH`.
  Quella classificazione veniva da una lettura statica del motore (la causa registrata come reason code della
  transizione, `ocor-runtime/src/ocor_runtime/c6/engine.py` riga 707), non da un'esecuzione del percorso. Il test
  negativo scritto dopo, primo esercizio eseguibile del percorso, mostra che il motore non produce quei quattro codici.
  Questa richiesta non modifica la precedente e non ne tocca gli otto codici.
- Norma. `docs/OCOR_LLD_v1.1.md` righe 304-305 (e ADD v1.3,
  `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` righe 2820-2821 e 2902-2903): da
  `CANONICAL_COMMIT_PENDING`, un fallimento di precondition o invariant porta con `ACT-T31a` a `EXECUTION_FAILED` con
  reason code `PRECONDITION_FAILED` o `INVARIANT_VIOLATION`; una deriva di revision, GatePackage o GCS porta con
  `ACT-T31b` a `INVALIDATED` con `REVISION_CONFLICT`, `GATE_PACKAGE_MISMATCH` o `GOVERNED_CONTEXT_MISMATCH`. ADD v1.3
  riga 2569: C3 mappa deterministicamente quei quattro casi ai quattro codici. `EXECUTION_UNKNOWN` con retry sospeso e
  reconciliation è l'esito di un invio ambiguo (`docs/OCOR_LLD_v1.1.md` righe 282-283, `ACT-T18a`/`ACT-T18b`; riga
  307: «Timeout post-dispatch non idempotente produce UNKNOWN e sospende retry»).
- Comportamento del motore mantenuto. In `execute` (`ocor-runtime/src/ocor_runtime/c6/engine.py` righe 1243-1252) e in
  `commit_canonical` (righe 1165-1175) ogni eccezione dell'invio a C3, compreso il rifiuto tipizzato `C3Error`
  (`ocor-runtime/src/ocor_runtime/c3/ports.py` riga 19) con uno dei quattro codici, passa da `_unknown` (righe 795-816):
  il comando entra fra gli invii ambigui, si apre la reconciliation `EXECUTION_UNKNOWN`, il retry è sospeso e l'azione
  resta in `CANONICAL_COMMIT_PENDING`. Il motore non applica mai `ACT-T31a` né `ACT-T31b`. L'esito è fail-closed (nessun
  effetto, nessun nuovo invio), ma l'azione non raggiunge lo stato terminale che la norma prescrive e il reason code non
  è registrato sulla transizione.
- Prova. Commit `689aff288c3fca00f32bbd501bbc1d99434e9966`, test
  `ocor-runtime/tests/tasks/test_ocor_dev_rem_0060.py::test_ncr_tests_004_the_c6_engine_ends_the_action_on_the_c3_refusal_after_the_send`
  (righe 469-552), quattro casi sul C3 reale su PostgreSQL attraverso il motore C6 mantenuto: precondition che non vale
  sullo stato, invariant che non vale sul nuovo stato, commit concorrente di un'altra azione sullo stesso target fra la
  fence e l'invio, GatePackage non risolvibile da C3. In tutti e quattro il comando attraversa la fence (`ACT-T29`
  registrata) e C3 lo rifiuta con il codice atteso; l'asserzione della norma fallisce: l'azione resta
  `CANONICAL_COMMIT_PENDING` con la nota `EXECUTION_UNKNOWN` (impronta dell'esito `38bbea9ffdc5`). Con questo test la
  scansione statica conta i quattro codici come coperti; restano scoperti gli otto codici della richiesta precedente.
- Impatto di una correzione del motore: fra i task completati, l'ultimo record di evidenza con
  `ocor-runtime/src/ocor_runtime/c6/engine.py` fra gli input è quello di `OCOR-DEV-0030` (verifica in sola lettura con
  il validatore della deriva degli input); i record sigillati di `OCOR-DEV-REM-0050` e `OCOR-DEV-REM-0053` lo citano
  anch'essi.
- Budget: iterazione 3 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2).

## Opzioni

Quesito A: che cosa fa l'unità per i quattro codici di C6 che il motore mantenuto non produce sul percorso
`ACT-T31a`/`ACT-T31b`. Quesito B: solo se si sceglie A2, come il motore tratta un rifiuto tipizzato di C3 dopo l'invio
con un codice che non è fra quelli di `ACT-T31a`/`ACT-T31b`.

### Opzioni del quesito A

A1. **Nuova voce del registro per C6, unità di soli test (raccomandata).** La divergenza entra nel registro di
   conformità come voce nuova `OPEN` del componente C6, con il primo identificativo `NCR-C6-*` libero (oggi
   `NCR-C6-015`), gravità secondo `severity_rule` del registro, le ancore di questa richiesta e come `red_tests` il test
   del commit `689aff288c3fca00f32bbd501bbc1d99434e9966`, citato con commit, percorso e righe; la sua pianificazione
   segue la regola del registro per le voci aperte. Nel modulo dell'unità il test esce dalla suite in un commit
   successivo, in modo che la suite non abbia casi falliti, e resta nella storia del branch come RED della voce nuova;
   il controllo di copertura elenca i quattro codici come divergenze note con l'identificativo della voce nuova e
   fallisce per ogni altro codice scoperto. `NCR-TESTS-004` si risolve con la copertura dei codici prodotti e con le
   voci nuove, come prevede per gli altri codici la decisione della richiesta precedente se adotta la stessa forma.
   Nessun file di runtime cambia, nessuna riqualifica aggiuntiva.
A2. **Correzione del motore C6 in NCP-U12.** `code_paths` dell'unità si estende a
   `ocor-runtime/src/ocor_runtime/c6/engine.py`: in `execute` e in `commit_canonical` un `C3Error` con
   `PRECONDITION_FAILED` o `INVARIANT_VIOLATION` applica `ACT-T31a`, uno con `REVISION_CONFLICT`,
   `GATE_PACKAGE_MISMATCH` o `GOVERNED_CONTEXT_MISMATCH` applica `ACT-T31b`, con il codice come reason code della
   transizione e un rifiuto tipizzato al chiamante, senza reconciliation; ogni altra eccezione resta un invio ambiguo
   come oggi. GREEN dei quattro casi, test negativi della classe secondo le regole dell'autocontrollo, riqualifica di
   `OCOR-DEV-0030` e degli altri record che hanno il file fra gli input secondo le regole di riqualifica vigenti.
A3. **Voce non risolta da NCP-U12.** `NCR-TESTS-004` resta `IN_REMEDIATION`; il test dei quattro codici resta RED nel
   modulo, fuori dalla suite qualificante, fino all'unità che correggerà C6.

### Opzioni del quesito B

B1. **Invio ambiguo come oggi (raccomandata, se A2).** Un `C3Error` dopo l'invio con un codice diverso dai cinque di
   `ACT-T31a`/`ACT-T31b` (per esempio `POLICY_DENIED`, `AUTHORITY_MISSING`, `CONTRACT_REJECTED`,
   `EMERGENCY_STOP_ACTIVE`, `RELEASE_MISMATCH` di `ocor-runtime/src/ocor_runtime/c3/admission.py` righe 326-367) resta
   trattato come oggi: reconciliation `EXECUTION_UNKNOWN` e retry sospeso; la norma non gli assegna una transizione da
   `CANONICAL_COMMIT_PENDING`.
B2. **Nuova voce del registro.** Il trattamento di quei codici dopo l'invio entra nel registro come voce nuova `OPEN`
   di C6 da decidere a parte; il motore li tratta come oggi finché la voce non è decisa.

## Raccomandazione

Opzioni A1 e, solo se si sceglie A2, B1. A1 mantiene l'unità nel suo ambito di soli test, come raccomanda la richiesta
precedente per gli altri codici non prodotti, e rende tracciabile con una voce propria del registro un difetto di
conformità di C6 emerso dal test; il comportamento attuale è fail-closed, quindi non ci sono effetti non governati da
contenere subito. A2 porterebbe in un'unità di test una modifica del motore C6 con la riqualifica di `OCOR-DEV-0030`;
A3 lascerebbe la suite con un RED permanente. B1 non introduce comportamenti che la norma non descrive.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: il GREEN di `NCR-TESTS-004` (forma del controllo di copertura e destino del test
  dei quattro codici) e quindi gate, revisione preventiva, campagna qualificante e verifica dell'unità, già bloccati
  anche dalla richiesta `NCP-U12-UNPRODUCED-REASON-CODES`.
- Non bloccati: il resto dell'unità secondo le decisioni in vigore (riqualifiche di sola regressione, record, allowlist,
  indice inverso).
- Riqualifiche: con A1 e A3 nessuna nuova; con A2 quella di `OCOR-DEV-0030` e degli altri record interessati.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, limiti e claim invariati (`E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`).

## Disposition del Product Owner — 2026-11-10

Decisione normativa del PO: `NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS (2026-11-10)`, **opzione A1** (il quesito B non si applica), come descritta in questo file al commit `98030e7a17f636b6f3213a3808ec97cce4a20ae5` (sha256 `544e678a18e6a6dbdda3e5de0a9f558625cc09a2f09f2cb91a0404d4a9c9c4c7`, verificata prima dell'attuazione); presa dal PO con istruzione esplicita, non su delega. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS (2026-11-10) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita il 2026-11-10. Il PO risolve la decision request `NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS` (branch `governed/decision-request-ncp-u12-c6-commit-refusal-transitions`, commit `98030e7a17f636b6f3213a3808ec97cce4a20ae5`, file `reports/development/decision_requests/NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS.md`, sha256 `544e678a18e6a6dbdda3e5de0a9f558625cc09a2f09f2cb91a0404d4a9c9c4c7`, draft PR #580) con l'**opzione A1**, come raccomandata e descritta in quel file a quel commit. Il quesito B non si applica, perché riguarda solo l'opzione A2.

1. **Opzione A1.** Attua l'opzione A1 esattamente come la descrive il file: la divergenza dei quattro codici di C6 sul percorso `ACT-T31a`/`ACT-T31b` (`PRECONDITION_FAILED`, `INVARIANT_VIOLATION`, `REVISION_CONFLICT`, `GATE_PACKAGE_MISMATCH`) entra nel registro di conformità come voce nuova `OPEN` del componente C6, con gravità secondo `severity_rule`, le ancore della richiesta e come `red_tests` il test del commit `689aff288c3fca00f32bbd501bbc1d99434e9966` citato con commit, percorso e righe; la sua pianificazione segue la regola del registro per le voci aperte. Nel modulo dell'unità il test esce dalla suite in un commit successivo e resta nella storia del branch come RED della voce nuova; il controllo di copertura elenca i quattro codici come divergenze note con l'identificativo della voce nuova e fallisce per ogni altro codice scoperto. Nessun file di runtime cambia; nessuna riqualifica aggiuntiva.
2. **Identificativo.** La voce nuova prende il primo identificativo `NCR-C6-*` libero nel registro al momento della registrazione: il file indica `NCR-C6-015`, ma `NCR-C6-015` e `NCR-C6-016` sono stati assegnati dopo, da `NCP-U12-REASON-CODE-ENTRIES-PLAN (2026-11-10)`. Questa è l'unica differenza ammessa rispetto al testo del file.
3. **Registrazione.** Registra la disposition nel file della decision request, nel registro `blockers` di `EXECUTION_STATE.json` (`po_decision` uguale a questa decisione; `evidence` con il commit `98030e7a17f636b6f3213a3808ec97cce4a20ae5` e il suo sha256 completi) e nell'`ITERATION_LOG.md`, secondo la prassi e l'allowlist vigenti; chiudi la draft PR come risolta, come per le decisioni precedenti dell'unità.
4. Nessun nuovo `DEC-*`. Oltre a quanto descrive l'opzione A1, nessun test, guard, limite di tempo, soglia, workflow, contratto, schema o file di runtime cambia. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
