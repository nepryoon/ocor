# NCP-U08-RISK-CLASS-NAME-ADAPTATION

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0054`
(NCP-U08 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, sicurezza e policy di C6; branch
`governed/ocor-dev-rem-0054-ncp-u08-c6-safety-policy`) e la voce `NCR-C6-013` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta secondo il punto 5 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` («Fuori da questi casi, fermati e apri una decision request») e il
punto 7 di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`. Implementatore: Claude Code (Anthropic),
implementatore di riserva del loop, per tutte le iterazioni dell'unità.

## Contesto

- `NCR-C6-013` (gravità `MEDIUM`, tipo `CONFLICT`, requisito `FR-079`, `plan_unit` `NCP-U08`): ADD v1.3 §5.4
  (righe 3300-3305) e l'enum `risk_class` dell'Action Type Contract (riga 2193) nominano le classi
  `R0_READ`, `R1_ANALYZE`, `R2_CONTROLLED`, `R3_HIGH_IMPACT`; LLD v1.1 §4.1 (righe 313-318) nomina
  `R1_DERIVE` e `R2_MUTATE`. Per LLD v1.1 §0.1 (righe 16-18) l'ADD prevale e non sono ammesse correzioni
  implicite tramite alias. Il codice usa altri nomi: `ocor-runtime/src/ocor_runtime/kernel/governance.py`
  righe 62-66 (`RiskClass`: `R0_INFORMATIONAL`, `R1_LOW`) e
  `ocor-runtime/src/ocor_runtime/security/control_plane.py` righe 670-680 (`OperationClass`: `R1_DERIVE`,
  `R2_MUTATE`). Il piano approvato non elenca test da riallineare o adattare per NCP-U08
  (`plan_units.NCP-U08.existing_tests_to_realign_or_adapt` è vuoto).
- Il RED dell'unità è il commit `28e9c48` del branch dell'unità: 7 casi falliscono sul codice attuale
  (nomi legacy in `RiskClass` e `OperationClass`, nell'input di policy e sul wire dell'`ActionType`).
- La correzione rinomina i membri degli enum ai nomi di ADD v1.3, con gli stessi valori ordinali (0-3) e senza
  alias. I valori ordinali, l'ordine d'impatto, i gate di `approval_requirement` (R2 un approvatore umano
  indipendente, R3 Domain e National Approver) e ogni decisione restano invariati; cambia soltanto il nome con
  cui il codice e il wire (`effect_class` e `risk_class` dell'input di policy, `risk_class` dei record C6)
  identificano la classe. Una prova eseguita sul branch dell'unità con la correzione applicata e i test
  rinominati come sotto ha dato 957 casi passati su unità, `test_ocor_dev_0030.py`, `test_ocor_dev_rem_0053.py`,
  `test_ocor_dev_0058.py`, `test_ocor_dev_rem_0050.py` e il mission thread.
- I test esistenti nominano i membri legacy, quindi falliscono alla raccolta (attributo inesistente) senza un
  cambiamento. In alcuni il nome sta dentro una parametrizzazione o un'asserzione, che il punto 5, caso 3, non
  consente di cambiare in un adattamento (numeri di riga al commit `28e9c48` del branch dell'unità):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0048.py` (task `OCOR-DEV-0048`, sigillato): righe 1338 e 1385
    (costruzione di `_CAPABILITY` e del grant di prova), righe 2472-2473 e 2476-2477 (costruzione nella
    funzione `test_repair5_capability_must_fit_grant_ceilings`), riga 2568 (costruzione in `_grant_chain`);
    nelle parametrizzazioni: riga 2461 (`test_repair5_capability_must_fit_grant_ceilings`,
    `OperationClass.R2_MUTATE`), riga 2607 (`test_repair5_chain_cannot_amplify_or_exceed_its_limits`,
    `OperationClass.R2_MUTATE`), righe 3025-3026 (`test_repair6_act_principal_grant_is_fully_verified`,
    `RiskClass.R0_INFORMATIONAL` e `OperationClass.R1_DERIVE`). Le stringhe `"R0_INFORMATIONAL"` (riga 2394) e
    `"R1_LOW"` (riga 2484) sono input di casi negativi (una stringa non è mai un enum) e non cambiano.
  - `ocor-runtime/tests/tasks/test_ocor_dev_rem_0053.py` (unità `OCOR-DEV-REM-0053`, sigillata): righe 1328,
    1352, 1444, 1500, 1504, 1691, 3028 e 3564 (costruzione e precondizioni); nelle parametrizzazioni: righe 1349 e
    1633 (`["R0_INFORMATIONAL", "R1_LOW", "R2_CONTROLLED", "R3_HIGH_IMPACT"]`); nelle asserzioni: righe
    1494-1495 di `test_ncr_c6_002_conforms` (`gate_disposition(RiskClass.R1_LOW, ...)`).
  - Solo costruzione, già entro il caso 3: `ocor-runtime/tests/tasks/test_ocor_dev_0030.py` riga 54 (e il
    commento della riga 51) e `ocor-runtime/tests/tasks/c6_action_fixture.py` riga 471.
- In ogni riga il cambiamento è la sola sostituzione dell'identificatore, secondo la corrispondenza biunivoca
  `R0_INFORMATIONAL` → `R0_READ`, `R1_LOW` → `R1_ANALYZE`, `R1_DERIVE` → `R1_ANALYZE`, `R2_MUTATE` →
  `R2_CONTROLLED`: stesso valore ordinale, stesso caso, stessa attesa. Nessun caso, input o soglia diventa meno
  severo; il numero delle funzioni e dei casi non cambia; gli identificativi dei casi parametrizzati cambiano solo
  nel nome della classe.

## Opzioni

1. **Sostituzione degli identificatori come adattamento autorizzato (raccomandata).** NCP-U08 applica la
   correzione di `NCR-C6-013` e, nei test elencati nel contesto, sostituisce gli identificatori legacy secondo la
   corrispondenza biunivoca, anche dentro parametrizzazioni e asserzioni, senza altre differenze. Il record
   dell'unità riporta ogni riga così cambiata nella forma di `existing_tests_to_realign_or_adapt` (tipo
   `ADAPTED`, file e righe, valore attuale, valore prescritto, ancora ADD v1.3 righe 2193 e 3300-3305 e LLD
   v1.1 righe 16-18) e il confronto dell'albero sintattico, che mostra come uniche differenze quelle sostituzioni
   di identificatore. Le riqualifiche di `OCOR-DEV-0048` e di `OCOR-DEV-REM-0053` seguono
   `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`. Effetto: la voce si risolve in NCP-U08 con una sola
   modifica dei nomi; nessun test, caso o attesa cambia significato.
2. **Riallineamento con RED per le righe in parametrizzazioni e asserzioni.** Come l'opzione 1, ma le righe dentro
   parametrizzazioni e asserzioni (`test_ocor_dev_0048.py` righe 2461, 2607, 3025-3026;
   `test_ocor_dev_rem_0053.py` righe 1349, 1494-1495, 1633) sono trattate come riallineamenti del caso 1 del
   punto 5, ciascuna con un RED proprio sul codice attuale (una copia di lavoro del test sigillato in cui cambia
   solo quella riga) e la citazione della norma in un commento. Effetto: stessa correzione, con un RED per riga in
   più e un commento normativo nei test sigillati.
3. **Nessun rinomino in NCP-U08.** `NCR-C6-013` resta `OPEN` e passa, con i test elencati, al ritiro della slice
   legacy (punto 6 di `NORMATIVE-CONFORMANCE-PLAN`) o a una decisione successiva. NCP-U08 risolve
   `NCR-C6-010`, `NCR-C6-011` e `NCR-C6-012`. Effetto: il conflitto fra ADD e codice resta; `OCOR-DEV-0063`,
   bloccato dalla voce, resta bloccato.

## Raccomandazione

Opzione 1: la sostituzione è meccanica e biunivoca, lascia invariati valori ordinali, casi e attese, e il
confronto dell'albero sintattico la rende verificabile riga per riga; il RED della voce resta quello dei test
dell'unità.

## Impatto e task bloccati

- Bloccata solo la risoluzione di `NCR-C6-013` in NCP-U08; l'unità prosegue con `NCR-C6-010` (GREEN `0cd12df`),
  `NCR-C6-011` e `NCR-C6-012`.
- `OCOR-DEV-0063` resta bloccato dalla voce fino alla sua risoluzione.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi e registri normativi invariati; claim invariati (`E1=0`,
  `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`).
