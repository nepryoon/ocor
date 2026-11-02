# OCOR-DEV-REM-0048-RCCAD — NCP-U02, Function & Model Registry `ocor.registry.v1`

Unità NCP-U02 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, la voce `NCR-C1-001` del registro.

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`. Il pacchetto `ocor_runtime.registry` realizza il contratto
`ocor_registry.proto` (LLD v1.1 §0.2): `FunctionRegistry` e `ModelRegistry` con pin esatti, descriptor e
artefatti firmati DSSE e legati a un contratto nominato di una release C1 ammessa, revoche, binding del
Governed Context, sandbox con timeout e quote di CPU, memoria e output e superamenti auditati (NFR-025),
lineage e ricostruzione delle invocazioni di Model (FR-060), persistenza append-only su PostgreSQL. RED
`f578a4e` (50 casi falliti perché il pacchetto non esiste), GREEN `196fec4` (52 passed su PostgreSQL reale).
Il record `OCOR-DEV-REM-0048.json` contiene criteri, test, ancore, scelte di prodotto e ambiguità risolte in
modo fail-closed. La revisione preventiva `OCOR-DEV-REM-0048-50c3a1e68535-pre` (Antigravity, Google) ha
segnalato 5 finding bloccanti e 1 consultivo: tutti i bloccanti sono corretti con RED `5a4043f` (12 casi
nuovi falliti per il difetto segnalato) e GREEN `08b6839` (65 passed su PostgreSQL reale); la disposition è nel
record. PRE-CAMPAIGN-GATE all'head del codice `7c48e32`: 47/48 PASS, con il solo drift atteso su `0005`, `0050` e
`0082` prima delle riqualifiche. Campagna sullo stack reale allo stesso head: modulo dell'unità con registro, REM-0046
e validatore dell'evidenza 3 × 1092 passed, regressione di `0005`/`0050`/`0082` 214 passed, portafoglio di
`reports/tests` 1594 passed, suite completa a due corsie 3424 test, zero fallimenti e zero skip, unione esatta,
2431 s sul tetto di 5400 s, rete elettrica, nessun residuo. Riqualifiche di sola regressione (classe non
qualificante) di `0005`, `0050` e `0082` nei rispettivi MANIFEST; drift 0 all'head dell'evidenza. Segue la
verifica indipendente, da un fornitore diverso da Anthropic e da Google.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, test esistente, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.
