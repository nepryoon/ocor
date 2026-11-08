# OCOR-DEV-REM-0058-RCCAD — NCP-U10, Governed Agent Kernel di C8

Unità NCP-U10 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 4, 5 e 10), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C8-001` … `NCR-C8-005`,
`NCR-C8-007` e `NCR-C8-008` del registro; `NCR-C8-006` resta fuori dall'unità (`DECISION_REQUIRED`), con il
criterio aggiuntivo dell'opzione A del punto 4: il kernel C8 attuale non si costruisce mai senza Authority né
altri controlli di governo.

Stato: `CANDIDATE_IN_PROGRESS` (iterazione 4 di stima 5, stop a 15): bozza del record prima della revisione
preventiva; nessuna campagna, nessuna evidenza. Il registro dei tool ammette solo contratti
`mcp-tool-contract:1.2` dello schema di ADD v1.3 §3.5, con digest verificato e pin di schema risolti; i soli tool
in allow-list sono esportabili e richiamabili, con argomenti vincolati, precondizioni, egress confinato e output
validato, digerito e marcato `TOOL_OUTPUT`/`UNTRUSTED` (RED `7dbd52f`, GREEN `de7a980`). Il tool runtime di C8
rilegge a ogni dispatch epoca di stop, grant C8 e catena di delega (correzione di `OCOR-DEV-REM-0043`), Delegation,
Authority, livello di autonomia, idoneità delle istruzioni di memoria e policy, con budget multidimensionale ai
livelli agent, run, team e tenant, ricevuta FR-004 e riconciliatore auditato obbligatorio (RED `be53786` e
`2ac5c64`, GREEN `144ae25`). L'orchestratore registra lo stato AgentRun come record C8 chiusi nel Run Ledger, mai
come aggregati canonici; il Coordination Kernel firma ogni HandoffEnvelope di 28 campi con il mittente legato al
Principal di trasporto; ruoli, ciclo di vita dei task, tentativi, cicli, profondità, timeout, terminazione e
dissenso critico bloccante seguono ADD v1.3 §4.3 (RED `a479515`, GREEN `9cdfd10`).

Iterazione 4: il caso di policy sul backend richiesto (OPA con bundle firmati su mTLS SPIFFE/SPIRE, principal
Keycloak) ha mostrato che runtime e kernel rifiutavano come scadute le decisioni reali, valutate dopo l'istante
presentato (RED `0ce3c96`, GREEN `f1503b8`). L'autocontrollo `SELF-CHECK-CHECKLIST (2026-11-08)` sui quattro moduli
interi ha chiuso le lacune trovate (RED `9a4b76a` e `91bda4e`, GREEN `f1503b8` e `6a32d61`): conversioni silenziose
e budget disattivabile con un NaN, risposte delle porte non tipizzate, avvio del worker, lease consumate da
chiamate rifiutate, atomicità con il Run Ledger, envelope `REJECTED` completi dei campi di LLD v1.1 :183 e
auditati. Selezione ampia sullo stack CI: 872 passati, zero skip.

Il record `OCOR-DEV-REM-0058.json` contiene criteri, test per voce, ancore, test riallineati e adattati di `0046`,
`0047`, `REM-0027`, `REM-0050` e `REM-0054` con il confronto dell'albero sintattico rispetto a `b6232f8`, la
tabella di autocontrollo, scelte di prodotto, ambiguità risolte in modo fail-closed, punti aperti, esiti
dell'inventario dei consumer e la classificazione delle riqualifiche: tutte di sola regressione (`0046` e `0047`
senza requisiti legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`; `0005`, `0050`, `0082` per
l'allowlist del piano).

Revisione preventiva `OCOR-DEV-REM-0058-9f452aaa0f64-pre` (Codex/OpenAI, revisore di riserva): otto finding
bloccanti e uno consultivo. Iterazione 5: RED `23c7715` e `baa473c`, GREEN `e6a921e` chiudono P1-P8
(rivalutazione all'istante di ogni dispatch, approval del contratto, binding concesso ed envelope di invocazione
attestato, marking dell'handoff rispetto alla clearance del destinatario, rilettura del Run Ledger, pin e
riferimenti degli schemi, invocazioni della ricevuta, una transazione del Run Ledger per transizione con le lease
consumate al suo interno). Selezione ampia sullo stack CI: 950 passati, zero skip. Il record riporta la
disposition di ogni finding e le annotazioni del punto 3 di `SELF-CHECK-CHECKLIST (2026-11-08)`; la traccia del
`PRE-CAMPAIGN-GATE` dell'head finale entra nel record con la campagna. Restano campagna qualificante,
riqualifiche e verifica indipendente da un fornitore diverso da Anthropic, da OpenAI e dal revisore preventivo.

Implementatore: Claude Code (Anthropic). Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.
