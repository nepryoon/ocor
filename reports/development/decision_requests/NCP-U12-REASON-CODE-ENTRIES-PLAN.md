# NCP-U12-REASON-CODE-ENTRIES-PLAN

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0060`
(NCP-U12 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, test; branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, head
`d307a0bb00fe79d702243eec9774f599e849c6a5`), la voce `NCR-TESTS-004` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json` e le voci nuove che la decisione
`NCP-U12-UNPRODUCED-REASON-CODES (2026-11-10)` aggiunge al registro. Implementatore: Claude Code (Anthropic),
implementatore di riserva.

## Contesto

- La decisione `NCP-U12-UNPRODUCED-REASON-CODES (2026-11-10)` adotta le opzioni A1 e B2 della richiesta omonima
  (`reports/development/decision_requests/NCP-U12-UNPRODUCED-REASON-CODES.md`, commit
  `92cdcc2949d9ee5a1135243f03b6919b3b5afd01`). A1: gli otto codici non prodotti (C2 `CAPABILITY_DENIED` e
  `SCENARIO_ISOLATION_VIOLATION`; C6 `SCHEMA_VIOLATION` e `CONTRACT_REJECTED` del pre-admission gate; C7
  `INSUFFICIENT_EVIDENCE`, `EXTRAPOLATIVE`, `STALE_CONTEXT` e `NOT_TRANSPORTABLE`) entrano nel registro come voci nuove
  `OPEN`, una per componente, «la loro pianificazione segue la regola del registro per le voci aperte»; il controllo di
  copertura li elenca come divergenze note con l'identificativo della voce nuova. B2: conta soltanto `reason_code`; per
  ogni codice di C6 asserito oggi solo come causa, l'unità aggiunge un test negativo che asserisce il campo
  `reason_code` del record della transizione FSM. Quanto le opzioni non descrivono va deciso con una nuova richiesta
  (punto 2 della decisione). Le due questioni seguenti sono emerse attuando A1 e B2 e non si potevano porre prima della
  decisione.
- Pianificazione delle voci nuove. La gravità segue `severity_rule` del registro («HIGH: violates a P0 PoC requirement
  or a contract of LLD v1.1 §0.2»):
  - C2: i due codici sono valori chiusi di `Problem.reason_code` del contratto del gateway
    (`ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml` righe 452-466), contratto di
    LLD v1.1 §0.2; ADD v1.3 righe 173, 177, 382, 387 e 388 assegnano i casi in cui si producono. Gravità `HIGH`.
  - C6: il pre-admission gate di `SubmitProposal` (ADD v1.3 riga 2753) fa parte della sequenza canonica dell'azione di
    `FR-077` (P0, PoC; `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md`
    riga 209). Gravità `HIGH`.
  - C7: le quattro condizioni di `ABSTAIN` (ADD v1.3 righe 3010, 3013, 3014, 3015) sono quelle che `FR-098` (P0, PoC;
    Register riga 239) chiede di valutare prima di rendere utilizzabile un risultato. Gravità `HIGH`.

  Il test d'integrità del registro (`reports/tests/test_normative_conformance_register.py` righe 281-299) chiede a ogni
  voce `HIGH` aperta un `plan_unit` presente in `plan_units` e `blocks` non vuoto (o `blocks_none_reason`); nessuna
  unità del piano approvato risolve queste voci e A1 non dice quale unità le pianifica. Lo stesso vale per la voce di
  C6 che la richiesta `NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS` (commit `98030e7a17f636b6f3213a3808ec97cce4a20ae5`,
  ancora senza disposition) crea con la sua opzione A1 (codici di `ACT-T31a`/`ACT-T31b`, `FR-077`) e per quella del
  quesito B di questa richiesta.
- Il RED di B2 per C6 `IDEMPOTENCY_CONFLICT`. La norma lo lega a `ACT-T03` (`docs/OCOR_LLD_v1.1.md` riga 264: da `[*]`,
  «stessa key, fingerprint diverso», reason code `IDEMPOTENCY_CONFLICT`, destinazione `DENIED`). Il motore mantenuto
  rifiuta l'istanza già ammessa che si ripresenta con un'altra Decision con `DECISION_MISSING` e causa
  `IDEMPOTENCY_CONFLICT` (`ocor-runtime/src/ocor_runtime/c6/engine.py` righe 917-924), senza alcuna transizione FSM:
  test
  `ocor-runtime/tests/tasks/test_ocor_dev_rem_0060.py::test_ncr_tests_004_an_admitted_action_presented_with_another_decision_records_the_idempotency_conflict`
  al commit `d307a0bb00fe79d702243eec9774f599e849c6a5`, sul C3 reale: lo scenario regge (rifiuto con quella causa),
  l'asserzione B2 fallisce (nessun record di transizione dopo il rifiuto; impronta `fa50b1e39297`). La correlazione
  dell'FSM del motore è l'`action_instance_id`, da cui deriva anche la idempotency key, quindi un'istanza già presente
  non può ripartire da `[*]` e oggi il motore non applica mai `ACT-T03`. Per l'altro codice asserito solo come causa,
  `GOVERNED_CONTEXT_MISMATCH`, il test B2 passa: il motore lo registra come reason code di `ACT-T05` (commit
  `e6d2ba0aa9e1f40a6a3b72a54b2a422c73c68882`).
- Stato del controllo di copertura al commit `d307a0bb00fe79d702243eec9774f599e849c6a5`: restano scoperti esattamente
  gli otto codici di A1; i quattro codici di `ACT-T31a`/`ACT-T31b` e `IDEMPOTENCY_CONFLICT` sono coperti da test RED.
- Budget: iterazione 3 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2).

## Opzioni

Quesito A: quale unità del piano pianifica le voci nuove `HIGH` create dalle decisioni sui codici chiusi. Quesito B:
che cosa fa l'unità per C6 `IDEMPOTENCY_CONFLICT`, che il motore non registra su alcuna transizione FSM.

### Opzioni del quesito A

A1. **Una unità nuova per tutte le voci (raccomandata).** Il registro riceve l'unità `NCP-U15` («codici chiusi dei
   componenti mantenuti»), con i campi richiesti dal test d'integrità, `status` `PROPOSED`, `order` 15,
   `depends_on_units` `["NCP-U12"]`, `estimate_iterations` 3, `required_backend` lo stack reale; `resolves` elenca le tre
   voci di A1 della decisione precedente e, se adottate, la voce di `NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS` e quella del
   quesito B di questa richiesta; `plan_order` la aggiunge dopo `NCP-U14`. Ogni voce nuova ha `plan_unit` `NCP-U15` e
   `blocks` con i task G6 che esercitano il comportamento: C2 `OCOR-DEV-0064` e `OCOR-DEV-0065`; C6 `OCOR-DEV-0063`; C7
   `OCOR-DEV-0060` e `OCOR-DEV-0065`. L'unità si esegue dopo l'integrazione di NCP-U12, nella collocazione del change set
   di `G7-REVIEW-AND-CANDIDATE-CRITERIA (2026-11-07)` punto 6 (prima di `OCOR-DEV-0060`), con il ciclo completo delle
   remediation; criteri di accettazione e RED sono i test che NCP-U12 lascia come divergenze note.
A2. **Una unità nuova per componente.** Come A1, ma con tre unità (`NCP-U15` C2, `NCP-U16` C6, `NCP-U17` C7), ciascuna
   con stima 2, nello stesso ordine di dipendenza dopo `NCP-U14`; le voci C6 delle altre richieste vanno in `NCP-U16`.
A3. **Voci in attesa di pianificazione.** Le voci nuove entrano con stato `DECISION_REQUIRED` invece che `OPEN`, con
   `blocks` come in A1 e senza `plan_unit`, e la loro pianificazione si decide con la decision request
   `NORMATIVE-CONFORMANCE-PLAN` successiva; il test d'integrità passa senza unità nuove.

### Opzioni del quesito B

B1. **Voce nuova del registro, unità di soli test (raccomandata).** La divergenza entra nel registro come voce nuova
   `OPEN` di C6 (`FR-077`, gravità `HIGH`), pianificata secondo il quesito A, con le ancore di questa richiesta e come
   `red_tests` il test del commit `d307a0bb00fe79d702243eec9774f599e849c6a5`, citato con commit, percorso e righe; nel
   modulo dell'unità il test esce dalla suite in un commit successivo e il controllo di copertura elenca
   `IDEMPOTENCY_CONFLICT` di C6 fra le divergenze note con l'identificativo della voce nuova. Nessun file di runtime
   cambia.
B2. **Correzione del motore C6 in NCP-U12.** `code_paths` dell'unità si estende a
   `ocor-runtime/src/ocor_runtime/c6/engine.py`: il rifiuto per idempotency conflict si registra come transizione FSM con
   reason code `IDEMPOTENCY_CONFLICT` e destinazione `DENIED` (`ACT-T03`), con la riqualifica di `OCOR-DEV-0030`; la
   correlazione della transizione per un'istanza già presente si sceglie con l'attuazione e si registra con
   l'ancora.
B3. **Voce non risolta da NCP-U12.** `NCR-TESTS-004` resta `IN_REMEDIATION`; il test resta RED nel modulo, fuori dalla
   suite qualificante, fino all'unità che correggerà C6.

## Raccomandazione

Opzioni A1 e B1. A1 rispetta la regola del registro per le voci `HIGH` aperte con una sola unità, coerente con l'unica
causa delle divergenze (codici chiusi non prodotti dai componenti mantenuti), e la colloca prima dei task G6 che le
voci bloccano; A2 frammenta lo stesso lavoro in tre unità; A3 rinvia la pianificazione e lascia le voci fuori dallo
stato `OPEN` che la decisione precedente prescrive. B1 mantiene NCP-U12 nel suo ambito di soli test, come le decisioni
già prese per gli altri codici; B2 porterebbe in un'unità di test una modifica del motore con una scelta di
correlazione non descritta dalla norma; B3 lascerebbe la suite con un RED permanente.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: le voci nuove del registro e quindi la forma finale del controllo di copertura,
  il GREEN di `NCR-TESTS-004`, gate, revisione preventiva, campagna qualificante e verifica dell'unità.
- Non bloccati: il resto dell'unità secondo le decisioni in vigore.
- Riqualifiche: con A1, A2 o A3 e con B1 o B3 nessuna nuova; con B2 quella di `OCOR-DEV-0030`.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, limiti e claim invariati (`E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`).
