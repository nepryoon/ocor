# OCOR-DEV-REM-0049-RCCAD — NCP-U03, C2 Named Query Gateway

Unità NCP-U03 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 4, 5 e 8), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C2-001`…`NCR-C2-009`, `NCR-C2-011`
e `NCR-C2-012` del registro.

Stato: `CANDIDATE_IN_PROGRESS`. Il gateway C2 realizza il contratto `ocor-named-query-gateway.openapi.yaml`
(LLD v1.1 §0.2): principal dal trasporto e GCS canonico ricostruito con digest ricalcolato, allow-list per id,
versione e digest e release attiva dalla release C1 ammessa, schema chiuso dei parametri e cost budget prima di
qualsiasi lookup d'identità o lettura, policy di contesto sull'intero GCS, `classification_marking_ref` sempre
risolto, ordinamento branch/commit e attesa limitata, modello `Problem` chiuso con `served`, le sei operazioni
con marking join, post-filtro e conteggio delle redazioni, forma dei digest sul wire `sha256:` convertita in modo
biunivoco (opzione 2 del PO per `NCR-C2-008`), e l'unico port di audit (append-only, hash-linked, firmato
Ed25519, PostgreSQL) per ogni diniego. RED `5e1e0e6`, GREEN `34ba322` e `49fe988` sui backend reali (TypeDB,
Fuseki, PostgreSQL). Il record `OCOR-DEV-REM-0049.json` contiene criteri, test, ancore, test riallineati o
adattati, scelte di prodotto e ambiguità risolte in modo fail-closed. Seguono revisione preventiva,
PRE-CAMPAIGN-GATE, campagna con le riqualifiche (qualificanti per `0012`, `0017`, `0031`, `0034`, `0035`,
`0037`, `0039`; di sola regressione per `0005`, `0050`, `0082`) e verifica indipendente, da un fornitore diverso
da Anthropic.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.
