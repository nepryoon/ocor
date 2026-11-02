# OCOR-DEV-REM-0048-RCCAD — NCP-U02, Function & Model Registry `ocor.registry.v1`

Unità NCP-U02 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, la voce `NCR-C1-001` del registro.

Stato: `CANDIDATE_IN_PROGRESS`. Il pacchetto `ocor_runtime.registry` realizza il contratto
`ocor_registry.proto` (LLD v1.1 §0.2): `FunctionRegistry` e `ModelRegistry` con pin esatti, descriptor e
artefatti firmati DSSE e legati a un contratto nominato di una release C1 ammessa, revoche, binding del
Governed Context, sandbox con timeout e quote di CPU, memoria e output e superamenti auditati (NFR-025),
lineage e ricostruzione delle invocazioni di Model (FR-060), persistenza append-only su PostgreSQL. RED
`f578a4e` (50 casi falliti perché il pacchetto non esiste), GREEN `196fec4` (52 passed su PostgreSQL reale).
Il record `OCOR-DEV-REM-0048.json` contiene criteri, test, ancore, scelte di prodotto e ambiguità risolte in
modo fail-closed; campagna, riqualifiche di sola regressione (`0005`, `0050`, `0082`) e verifica indipendente
seguono la revisione preventiva.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, test esistente, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.
