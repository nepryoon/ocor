# NCP-U12-UNPRODUCED-REASON-CODES

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0060`
(NCP-U12 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, test; branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, head
`4fbcf16`) e la voce `NCR-TESTS-004` di `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Implementatore:
Claude Code (Anthropic), implementatore di riserva.

## Contesto

- La decisione `NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10)` adotta per `NCR-TESTS-004` l'opzione D1 della richiesta
  omonima (`reports/development/decision_requests/NCP-U12-TEST-REALIGNMENT-SCOPE.md`, commit
  `035b76f9ec82026b21baaa447f47b4184f01b716`): l'unità inventaria i reason code chiusi di ADD v1.3, LLD v1.1 e dei
  contratti di LLD v1.1 §0.2 per C1-C8 e la memoria governata, verifica con un controllo statico che almeno un test
  negativo della suite asserisca `reason_code` uguale a ciascun codice e, per ogni codice senza un tale test, aggiunge
  nel modulo dell'unità un test negativo che lo provoca sul componente mantenuto, «con RED dove il codice non è
  prodotto»; la prova di risoluzione è la copertura completa. L'opzione non dice che cosa avviene dopo il RED di un
  codice che il componente non produce, e l'ambito del piano per NCP-U12 è di soli test (`code_paths` vuoto). Il
  punto 2 della decisione prescrive una nuova richiesta per ciò che va oltre l'opzione.
- Inventario (modulo `ocor-runtime/tests/tasks/test_ocor_dev_rem_0060.py`, tabella `CLOSED_REASON_CODES`, commit
  `f2a197b` con le correzioni `f1fcfea` e `4fbcf16`): 61 coppie (componente, codice), ciascuna ancorata a file e riga;
  la scansione statica trova 11 codici senza un test negativo che li asserisca sul loro componente. Quattro sono
  prodotti dal componente mantenuto e ricevono un test nuovo secondo D1, senza questione: C6 `PRECONDITION_FAILED`,
  `INVARIANT_VIOLATION`, `REVISION_CONFLICT` e `GATE_PACKAGE_MISMATCH` sul percorso `ACT-T31a`/`ACT-T31b`
  (`docs/OCOR_LLD_v1.1.md` righe 304-305), che il motore C6 riporta come causa del rifiuto di C3. Gli altri sette, più
  uno che la scansione attribuisce a C6 per un test di C8, non sono prodotti dal componente che la norma indica:
  - C2: `CAPABILITY_DENIED` e `SCENARIO_ISOLATION_VIOLATION`
    (`ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml` righe 456 e 466) compaiono
    solo nelle tabelle di `ocor-runtime/src/ocor_runtime/c2/problem.py` (righe 24, 34, 42, 52); il gateway rifiuta una
    lettura di scenario con `UNSUPPORTED_CAPABILITY` (`c2/gateway.py` righe 505-506);
  - C6: `SCHEMA_VIOLATION` e `CONTRACT_REJECTED` del pre-admission gate di `SubmitProposal`
    (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` riga 2753); il gate `G-CONTRACT` del
    motore rifiuta con `CONTRACT_INVALID` e cause `SCHEMA_INVALID`, `ACTION_TYPE_UNKNOWN`,
    `ACTION_TYPE_SIGNATURE_INVALID`, `ACTION_TYPE_INACTIVE`, `ACTION_TYPE_MISMATCH`, `PARAMETERS_INVALID`
    (`ocor-runtime/src/ocor_runtime/c6/contract.py` righe 43-46, `c6/engine.py` righe 831-834);
  - C7: `INSUFFICIENT_EVIDENCE`, `EXTRAPOLATIVE`, `STALE_CONTEXT` e `NOT_TRANSPORTABLE` dell'insieme chiuso
    `ABSTAIN.reason_code` (ADD v1.3 righe 3010, 3013, 3014 e 3015); il runtime causale mantenuto astiene soltanto con
    `ASSUMPTION_VIOLATION`, `NOT_IDENTIFIED`, `OUTSIDE_VALIDITY_ENVELOPE` e `OUT_OF_DISTRIBUTION`
    (`ocor-runtime/src/ocor_runtime/c7/runtime.py` righe 827-845), e la sua `CausalQuery` non porta gli input da cui
    dipendono gli altri quattro (qualità dell'Evidence, extrapolation autorizzata, freshness policy, popolazione o
    dominio target; LLD v1.1 riga 177 elenca population, validity envelope e resource budget fra i campi della query).
- Copertura dei codici di C6 attraverso la causa: il motore C6 registra la causa di una transizione rifiutata come
  `reason_code` della transizione FSM (`ocor-runtime/src/ocor_runtime/c6/engine.py` riga 707) e i suoi test asseriscono la
  coppia (`reason_code`, `cause_code`) dell'errore, per esempio `("DECISION_MISSING", "IDEMPOTENCY_CONFLICT")`
  (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0053.py` riga 1754). La scansione conta un'asserzione su `cause_code` come
  asserzione del reason code della transizione; D1 parla di `reason_code`.
- Budget: iterazione 2 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2).

## Opzioni

Quesito A: che cosa fa l'unità per i codici chiusi che il componente mantenuto non produce. Quesito B: se la causa
registrata da C6 vale come reason code nel controllo di copertura.

### Opzioni del quesito A

A1. **Nuove voci del registro, unità di soli test (raccomandata).** I codici non prodotti (C2 `CAPABILITY_DENIED` e
   `SCENARIO_ISOLATION_VIOLATION`; C6 `SCHEMA_VIOLATION` e `CONTRACT_REJECTED` del pre-admission gate; C7
   `INSUFFICIENT_EVIDENCE`, `EXTRAPOLATIVE`, `STALE_CONTEXT` e `NOT_TRANSPORTABLE`) entrano nel registro di conformità
   come voci nuove `OPEN` del componente, una per componente, con le ancore di questa richiesta e il RED descritto qui;
   la loro pianificazione segue la regola del registro per le voci aperte. Nel modulo dell'unità il controllo di
   copertura li elenca come divergenze note, ciascuna con l'identificativo della voce nuova, e fallisce per ogni altro
   codice scoperto; `NCR-TESTS-004` si risolve con la copertura completa dei codici prodotti e con le voci nuove. Nessun
   file di runtime cambia.
A2. **Estensione di NCP-U12 ai componenti.** L'unità produce i codici nei componenti, con RED e GREEN: `code_paths` si
   estende a `ocor-runtime/src/ocor_runtime/c2/gateway.py`, `c6/contract.py`, `c6/engine.py` e `c7/runtime.py` (per C7
   anche i campi della `CausalQuery` che le quattro condizioni richiedono), con le riqualifiche dei task i cui ultimi
   record hanno quei file fra gli input; `NCR-TESTS-004` si risolve con la copertura completa dell'inventario.
A3. **Voce non risolta da NCP-U12.** `NCR-TESTS-004` resta `IN_REMEDIATION` con la copertura dei codici prodotti; i
   codici non prodotti restano nel controllo come RED fino all'unità del componente che li produrrà, e il controllo di
   copertura non entra nella suite qualificante finché non passa.

### Opzioni del quesito B

B1. **La causa registrata vale come reason code della transizione (raccomandata).** Per C6 un'asserzione su
   `cause_code` conta come asserzione del reason code della transizione rifiutata, perché il motore la registra come
   tale (`c6/engine.py` riga 707); il controllo lo dichiara in un commento con quell'ancora.
B2. **Solo `reason_code`.** Per ogni codice di C6 asserito oggi solo come causa, l'unità aggiunge un test negativo che
   asserisce il campo `reason_code` del record della transizione FSM; il controllo conta soltanto `reason_code`.

## Raccomandazione

Opzioni A1 e B1. A1 mantiene l'unità nel suo ambito di soli test e rende tracciabili, con voci proprie del registro,
difetti di conformità dei componenti che la copertura dei test ha fatto emergere; A2 porterebbe in un'unità di test
modifiche di runtime di tre componenti, con nuovi input per C7; A3 lascerebbe la suite con un RED permanente. B1 legge
la copertura sul valore che il componente registra davvero.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: il GREEN di `NCR-TESTS-004` (forma del controllo di copertura) e quindi gate,
  revisione preventiva, campagna qualificante e verifica dell'unità.
- Non bloccati: i test nuovi dei quattro codici prodotti di C6; il resto dell'unità secondo le decisioni in vigore.
- Riqualifiche: con A1 e A3 nessuna nuova; con A2 quelle dei task toccati.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, limiti e claim invariati (`E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`).
