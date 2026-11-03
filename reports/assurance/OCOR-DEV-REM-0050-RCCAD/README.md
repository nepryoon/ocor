# OCOR-DEV-REM-0050-RCCAD — NCP-U04, C3 commit admission, C6 -> C3 composition, outbox relay

Unità NCP-U04 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 4 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C3-001`, `NCR-C3-002`,
`NCR-C3-003`, `NCR-C3-004`, `NCR-C3-006` e `NCR-C3-007` del registro. `NCR-C6-009` resta `OPEN` (NCP-U07) e
`NCR-C3-005` resta `DEFERRED_BY_PO`.

Stato: `CANDIDATE_IN_PROGRESS`. C3 ammette un commit canonico solo con GatePackage, Decision e Authority firmati
da C6, validi, non scaduti e coerenti con il GatePackage congelato, con Evidence registrata, stop epoch e release
attiva verificati, precondizioni e invarianti valutate nella transazione sullo stato bloccato, e writer epoch
fencing su entrambi gli adapter (PostgreSQL e TerminusDB). C6 produce i comandi sul percorso governato (motore
delle azioni e, per l'opzione 1 della decisione `NCP-U04-MEMORY-PROMOTION-GATE-PACKAGE` del 2026-11-03, il
consumer della promozione della memoria tramite la porta di emissione `GovernedCommandIssuer`); lo stato di run
di C8 vive nel Run Ledger PostgreSQL. Il relay legge l'outbox committato con `FOR UPDATE SKIP LOCKED`, pubblica
`canonical-state-committed` sul backbone C5 e registra un `DeliveryAttempt` separato; il projector C4 consuma gli
eventi in ordine per aggregato. `canonical_source_binding` è scritto nel commit su entrambi gli adapter. RED
`5f05830`, GREEN `7d74dd4` e `9b56f4d`; riallineamento di `0046` (`2b9e93b`), adattamento del mission thread
(`b0f106c`) e di `0058` (`8afc3ad`); robustezza degli input degli adapter (RED `6a203cf`, GREEN `46773b1`);
opzione 1 della decisione (RED `482286b`, GREEN `a06d0e4`). Per `NCR-C3-007` la sonda di mutazione sostituisce
il RED (punto 4 della decisione sul piano).

Il record `OCOR-DEV-REM-0050.json` contiene criteri, test, ancore, test riallineati o adattati, scelte di
prodotto, ambiguità risolte in modo fail-closed e la classificazione delle riqualifiche secondo
`NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`: nessun requisito legabile, quindi riqualifiche di sola
regressione per `0029`, `0030`, `0031`, `0036`, `0039`, `0043`, `0046`, `0058`, e per `0005`, `0050`, `0082`.
Seguono PRE-CAMPAIGN-GATE, revisione preventiva, campagna con le riqualifiche e verifica indipendente, da un
fornitore diverso da Anthropic.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.
