# OCOR-DEV-REM-0058-RCCAD — NCP-U10, Governed Agent Kernel di C8

Unità NCP-U10 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 4, 5 e 10), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C8-001` … `NCR-C8-005`,
`NCR-C8-007` e `NCR-C8-008` del registro; `NCR-C8-006` resta fuori dall'unità (`DECISION_REQUIRED`), con il
criterio aggiuntivo dell'opzione A del punto 4: il kernel C8 attuale non si costruisce mai senza Authority né
altri controlli di governo.

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION` sul commit di codice `666433e` (iterazione 6 di stima 5, stop a
15). Il registro dei tool ammette solo contratti `mcp-tool-contract:1.2` dello schema di ADD v1.3 §3.5, con digest
verificato e pin di schema risolti; i soli tool in allow-list sono esportabili e richiamabili, con argomenti
vincolati, precondizioni, egress confinato e output validato, digerito e marcato `TOOL_OUTPUT`/`UNTRUSTED` (RED
`7dbd52f`, GREEN `de7a980`). Il tool runtime di C8 rilegge a ogni dispatch epoca di stop, grant C8 e catena di
delega (correzione di `OCOR-DEV-REM-0043`), Delegation, Authority, livello di autonomia, idoneità delle istruzioni
di memoria e policy, con budget multidimensionale ai livelli agent, run, team e tenant, ricevuta FR-004 e
riconciliatore auditato obbligatorio (RED `be53786` e `2ac5c64`, GREEN `144ae25`). L'orchestratore registra lo
stato AgentRun come record C8 chiusi nel Run Ledger, mai come aggregati canonici; il Coordination Kernel firma ogni
HandoffEnvelope con il mittente legato al Principal di trasporto; ruoli, ciclo di vita dei task, tentativi, cicli,
profondità, timeout, terminazione e dissenso critico bloccante seguono ADD v1.3 §4.3 (RED `a479515`, GREEN
`9cdfd10`). Il caso di policy su OPA reale (bundle firmati su mTLS SPIFFE/SPIRE, principal Keycloak) ha corretto il
rifiuto delle decisioni reali (RED `0ce3c96`, GREEN `f1503b8`); l'autocontrollo `SELF-CHECK-CHECKLIST (2026-11-08)`
sui quattro moduli interi ha chiuso le lacune trovate (RED `9a4b76a` e `91bda4e`, GREEN `f1503b8` e `6a32d61`).

La revisione preventiva `OCOR-DEV-REM-0058-9f452aaa0f64-pre` (Codex CLI, OpenAI, revisore di riserva) ha dato `BLOCKING_FINDINGS`
con otto finding bloccanti e uno consultivo. I bloccanti sono corretti (RED `23c7715` e `baa473c`, GREEN
`e6a921e`): rivalutazione all'istante di ogni dispatch, approval del contratto, binding concesso ed envelope di
invocazione attestato verificati al confine, marking dell'handoff rispetto alla clearance del destinatario,
rilettura del Run Ledger fail-closed, pin e riferimenti degli schemi, invocazioni della ricevuta, una transazione
del Run Ledger per transizione con le lease consumate al suo interno. Il consultivo P9 è accolto: la traccia del
PRE-CAMPAIGN-GATE dell'head finale è nel record, 50/51 al commit di codice, con la sola deriva attesa di `0005`,
`0046`, `0047`, `0050` e `0082`.

Campagna `PASS` da shell pulita: modulo dell'unità con le suite di registro, REM-0046 e validator dell'evidenza tre
volte (371 casi per run) sullo stack CI reale (OPA, Keycloak, SPIRE, PostgreSQL), moduli riallineati di `0046`
e `0047`, consumer `REM-0027`, `REM-0050`, `REM-0054`, EV-029..035, superficie pubblica e mission thread,
regressione di `0005`, `0050`, `0082`, portfolio di `reports/tests`, e suite completa con l'orchestratore
versionato (`FOUR_LANE`, 4 corsie eseguite) 5580/5580, zero skip, JUnit uguale alla collezione, 1743.1 s sul tetto di
5400 s.

Le cinque riqualifiche `.requalified-rem0058` sono di sola regressione, nella classe non qualificante di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: `0046` e `0047` senza requisiti legabili secondo
`NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`, con il confronto dell'albero sintattico; `0005`, `0050`, `0082`
per l'allowlist del piano. Inserimento chirurgico nei MANIFEST, deriva zero all'head candidato. Resta la verifica
indipendente da un fornitore diverso da Anthropic e OpenAI, poi sigillo, merge e state sync.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro normativo
diverso dal registro di conformità, workflow o guard di invarianza è modificato. `E1=0`, `E2=0`, `Verified=0`,
runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
