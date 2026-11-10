# NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS

Status: `DECIDED_BY_PO` (era `OPEN_PO_NORMATIVE_DECISION_REQUIRED`). Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0060`
(NCP-U12 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, test; branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, head
`496d745d9e97610c8fe6bd21e2db94844e22920c`) e la voce `NCR-TESTS-001` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Implementatore: Claude Code (Anthropic), implementatore di
riserva.

## Contesto

- La decisione `NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10)` adotta l'opzione B1 della richiesta omonima
  (`reports/development/decision_requests/NCP-U12-TEST-REALIGNMENT-SCOPE.md`, branch
  `governed/decision-request-ncp-u12-test-realignment-scope`, commit `035b76f9ec82026b21baaa447f47b4184f01b716`, sha256
  `3b668f06d27a6dce6f689f63eb3b4dfdeaf8f90fd28a20d3d085135036896652`): «Le asserzioni delle righe 241, 429, 430 e 431 si
  riallineano come nel caso 1 del punto 5 del piano [...] tutte le altre righe sono adattamenti di sola costruzione con
  confronto dell'albero sintattico». Il punto 2 della decisione prescrive una nuova richiesta per ciò che va oltre le
  opzioni scelte. Con A1 il mission thread non chiama metodi delle classi legacy per ottenere un esito del thread.
- Una composizione di prova del thread con i componenti mantenuti, eseguita sullo stack reale (i cinque test di
  `ocor-runtime/tests/mission_thread/test_first_governed_slice.py` passano con le sostituzioni descritte qui), mostra
  altre quattro asserzioni dello stesso file al commit `913b43d59017468ba694c1f638ec370c889c8bfb` che non possono restare
  identiche e che B1 non elenca:
  - riga 161 `assert outcome.status is ResolutionStatus.IDENTIFIED` e riga 162 `assert outcome.canonical_id is not None`,
    nella funzione `resolve_operator_identity`: l'esito è quello del metodo `IdentityRegistry.resolve` della classe legacy
    (`ocor-runtime/src/ocor_runtime/c2_identity.py`); la risoluzione del componente mantenuto,
    `IdentityBackedAuthority.resolve` (`ocor-runtime/src/ocor_runtime/c2/gateway.py` righe 200-215), restituisce
    l'identificativo canonico come stringa, oppure il valore `ABSTAIN`, e non un oggetto con `status` e `canonical_id`;
  - riga 432 `assert receipts.causal_outcome.lineage["correlation_id"] == correlation_id` e riga 433 `assert
    receipts.causal_outcome.lineage["causation_id"] == receipts.action_event_id`, nella funzione di test
    `test_mission_thread_produces_correlated_receipts_across_all_governed_components`: il runtime causale mantenuto tiene
    gli identificativi di traccia fuori dalla lineage e dal digest di riproducibilità, nel campo `trace` del risultato
    (`ocor-runtime/src/ocor_runtime/c7/runtime.py` righe 21-22, 450 e 695); è la risoluzione della voce `NCR-C7-005`
    (Register `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md` riga 61,
    NFR-007); la lineage di LLD v1.1 (`docs/OCOR_LLD_v1.1.md` riga 177) e quella del risultato `ESTIMATED` di ADD v1.3
    (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` righe 2980-2990) non comprendono la traccia.
- Gli altri cambiamenti della composizione sono di sola costruzione e non toccano asserzioni: gli input della query
  causale sono un SCM registrato con il suo insieme fattuale (il modello dello spike non è un SCM ammesso dal runtime
  mantenuto); il valore di un record letto dal backbone di C5 è il `payload` dell'evento consegnato, così le righe 577 e
  583 restano identiche; la proiezione TypeDB non ancora allineata al commit si ottiene osservando il commit senza
  applicarlo, così la riga 567 resta identica. Le classi legacy che restano importate sono `IdentityRegistry` e
  `IdentityRecord` (`c2/gateway.py` riga 209) ed `EmissionFence` (`c6/engine.py` riga 595), entrambe nell'elenco di A1.
- Perché una richiesta nuova: le quattro asserzioni si potevano ricavare dal codice quando la prima richiesta è stata
  aperta e sono state omesse nella sua prima stesura; un emendamento della prima richiesta (commit
  `bb1cea02370d0f8adfa89bbd7ac95de14ddbbf82`) è stato pubblicato mentre la decisione era in corso, non è stato deciso ed
  è stato ritirato con la disposition. La questione è la stessa del quesito B deciso, limitata a queste righe.
- Budget: iterazione 2 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2).

## Opzioni

1. **Riallineamento al valore del componente mantenuto, con RED, come l'opzione B1 decisa (raccomandata).** Le
   asserzioni delle righe 161, 162, 432 e 433 si riallineano come nel caso 1 del punto 5 del piano, nello stesso RED con
   fingerprint e nello stesso GREEN delle righe 241, 429, 430 e 431, ciascuna con la citazione della norma in un
   commento: righe 161 e 162 l'identificativo canonico restituito dalla risoluzione del gateway, uguale a quello
   registrato e diverso da `ABSTAIN` (`c2/gateway.py` righe 200-215); righe 432 e 433 gli stessi identificativi letti dal
   campo `trace` del risultato causale invece che dalla lineage (`NCR-C7-005`, Register v1.1 riga 61). Numero di funzioni
   e di asserzioni invariato, nessun valore accettato in più; il resto resta come decide B1.
2. **Righe 161 e 162 invariate, righe 432 e 433 riallineate.** In `resolve_operator_identity` il test chiama ancora
   `IdentityRegistry.resolve` della classe legacy per le due asserzioni sull'esito, come eccezione circoscritta a quella
   funzione rispetto all'opzione A1 decisa, e poi passa lo stesso registro alla risoluzione del gateway; le righe 432 e
   433 si riallineano al campo `trace` come nell'opzione 1. L'elenco delle eccezioni di A1 entra fra le dipendenze residue
   di `NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT`.

## Raccomandazione

Opzione 1. Applica alle quattro righe la stessa lettura che la decisione ha già dato alle righe 241, 429, 430 e 431:
il thread asserisce i valori che la norma prescrive ai componenti mantenuti che attraversa, senza eccezioni ad A1.
L'opzione 2 conserva un esito ottenuto da un metodo legacy, che A1 esclude.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: il RED e il GREEN del mission thread di `NCR-TESTS-001`, quindi gate, revisione
  preventiva, campagna qualificante e verifica dell'unità.
- Non bloccati: l'adattamento del test RED dell'unità secondo A1, la qualificazione legacy di
  `ocor-runtime/tests/schemas/test_schema_integrity.py` secondo C1, l'inventario e i test dei failure code di
  `NCR-TESTS-004` secondo D1.
- Riqualifiche: invariate rispetto alla decisione `NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10)` (`OCOR-DEV-0031` con
  supersession, qualificante per i soli requisiti legabili).
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, registri normativi, limiti e claim invariati
  (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`).

## Disposition del Product Owner — 2026-11-10

Decisione del PO su delega completa: `NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS (2026-11-10)`, **opzione 1**, come descritta in questo file al commit `a09370d7ef0e26b447a2ea5020bd67555dcc2ffa` (sha256 `1506d2d678b830e1137c169b30431ddd16031f2e6a111f094782e484a68b5e36`, verificata prima dell'attuazione); decisa su delega completa del PO, modello claude-opus-5-5, effort xhigh. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS (2026-11-10) — decisione del PO, su delega completa

Decisa su delega completa del PO secondo `DELEGA-COMPLETA (2026-11-02)`, con il modello `claude-opus-5-5` ed effort `xhigh` (scelta di `claude-opus-5-5` con effort `medium`, delicatezza ALTA). Il PO risolve la decision request `NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS` (branch `governed/decision-request-ncp-u12-mission-thread-residual-assertions`, commit `a09370d7ef0e26b447a2ea5020bd67555dcc2ffa`, file `reports/development/decision_requests/NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS.md`, sha256 `1506d2d678b830e1137c169b30431ddd16031f2e6a111f094782e484a68b5e36`) adottando l'**opzione 1**.

1. Applica le opzioni scelte esattamente come descritte nel file indicato, a quel commit. Se il file che leggi a quel commit non ha quello sha256, non applicarle e apri una decision request.
2. Se l'attuazione richiede di andare oltre quanto le opzioni scelte descrivono esplicitamente, fermati e apri una decision request: la deciderà la stessa delega.
3. Registra la disposition nel file della decision request, nel registro `blockers` di `EXECUTION_STATE.json` (`po_decision` uguale a questa decisione, con la nota «decisa su delega completa del PO, modello claude-opus-5-5, effort xhigh») e nell'`ITERATION_LOG.md`, con lo stesso trattamento di una decisione del PO. Vale come decisione del PO a ogni effetto, anche dove una regola chiede una decisione del PO non presa su delega.
4. Le altre decisioni e regole vigenti restano invariate, salvo quanto le opzioni scelte cambiano esplicitamente.
