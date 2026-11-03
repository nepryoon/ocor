# OCOR-DEV-REM-0049-RCCAD — NCP-U03, C2 Named Query Gateway

Unità NCP-U03 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 4, 5 e 8), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C2-001`…`NCR-C2-009`, `NCR-C2-011`
e `NCR-C2-012` del registro.

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`. Il gateway C2 realizza il contratto `ocor-named-query-gateway.openapi.yaml`
(LLD v1.1 §0.2): principal dal trasporto e GCS canonico ricostruito con digest ricalcolato, allow-list per id,
versione e digest e release attiva dalla release C1 ammessa, schema chiuso dei parametri e cost budget prima di
qualsiasi lookup d'identità o lettura, policy di contesto sull'intero GCS, `classification_marking_ref` sempre
risolto, ordinamento branch/commit e attesa limitata, modello `Problem` chiuso con `served`, le sei operazioni
con marking join, post-filtro e conteggio delle redazioni, forma dei digest sul wire `sha256:` convertita in modo
biunivoco (opzione 2 del PO per `NCR-C2-008`), e l'unico port di audit (append-only, hash-linked, firmato
Ed25519, PostgreSQL) per ogni diniego. RED `5e1e0e6`, GREEN `34ba322` e `49fe988` sui backend reali (TypeDB,
Fuseki, PostgreSQL). Il record `OCOR-DEV-REM-0049.json` contiene criteri, test, ancore, test riallineati o
adattati, scelte di prodotto e ambiguità risolte in modo fail-closed. La revisione preventiva
`OCOR-DEV-REM-0049-530fe1e687e2-pre` (Antigravity, Google) ha segnalato 7 finding bloccanti: tutti corretti con RED
`8880d62` (96 casi falliti per il difetto segnalato) e GREEN `62164b3`; la disposition è nel record.
PRE-CAMPAIGN-GATE all'head del codice `511091f`: 48/49 PASS, con il solo drift atteso sui dieci task da
riqualificare. Campagna sullo stack reale allo stesso head: modulo dell'unità con registro, REM-0046 e validatore
dell'evidenza 3 × 1149 passed, moduli riallineati o adattati dei sette task 84 passed, regressione di
`0005`/`0050`/`0082` 214 passed, portafoglio di `reports/tests` 1594 passed; ammissione a due corsie
`SERIAL_FALLBACK` (nessun test eseguito), poi suite completa seriale 3546 test, zero fallimenti e zero skip, unione
esatta, 4233,4 s sul tetto di 5400 s (margine 1166,6 s; oltre la notifica di 3600 s di 633,4 s), rete elettrica,
stack assente dopo il teardown. Con la decisione `NCP-U03-QUALIFYING-REQUALIFICATIONS (2026-11-02)` (opzione 1,
decisa su delega completa del PO) tutte e dieci le riqualifiche sono di sola regressione, nella classe non
qualificante: `0012`, `0017`, `0031`, `0034`, `0035`, `0037` e `0039` con l'elenco dei test riallineati o adattati
e il confronto dell'albero sintattico, `0005`, `0050` e `0082` con i test invariati; nessuna docstring aggiunta,
head del codice invariato. Drift 0 all'head dell'evidenza. Segue la verifica indipendente, da un fornitore diverso
da Anthropic e da Google.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Ciclo di riparazione 1

Il record `OCOR-DEV-REM-0049.json` è stato sigillato sul branch dell'unità (`b3b175c`, verdetto
`GO_FOR_EVIDENCE_SEAL` `OCOR-DEV-REM-0049-a40b82f86230-0`), ma la CI della PR #457 sull'HEAD esatto è fallita su
`test_ocor_dev_rem_0010.py::test_typedb_apply_commit_escapes_injection`: il test backend-free di REM-0010 isola
l'adapter TypeDB con `_read` e `_write`, e `apply_commit` non leggeva più tramite `_read`. Il record sigillato, le
sue riqualifiche e la PR #457 restano invariati come storia.

Il ciclo di riparazione 1 (branch `governed/ocor-dev-rem-0049-ncp-u03-c2-gateway-repair-1`) ripristina un'unica
primitiva di lettura stretta (RED `d920f91`, GREEN `fdfdc0a`) e corregge i finding bloccanti P1/P2 della revisione
preventiva `OCOR-DEV-REM-0049-7dca6ab6517f-pre` (Antigravity, Google) sulla robustezza degli input dell'adapter
(RED `84af426`, GREEN `cee5b0b`); il consultivo P3 è applicato riallineando il `remediation_record` delle undici
voci `NCR-C2-*` a `repair-1.json`. Nessun test esistente cambia. PRE-CAMPAIGN-GATE all'head del codice `cee5b0b`:
55/56 PASS, con il solo drift atteso su `0005`, `0037`, `0050` e `0082`. Campagna sullo stack reale allo stesso
head: modulo dell'unità con REM-0010, registro, REM-0046 e validatore dell'evidenza 3 × 1208 passed, moduli dei
consumer C2/C4 84 passed, regressione di `0005`/`0050`/`0082` 214 passed, portafoglio di `reports/tests` 1594
passed; suite completa a due corsie (ammissione `TWO_LANE`) 3601 test, zero fallimenti e zero skip, unione
esatta, 2429,5 s sul tetto di 5400 s, rete elettrica, nessun residuo sull'host.

`repair-1.json` supersede il record sigillato dell'unità e riesegue all'head della riparazione ogni criterio di
accettazione e ogni probe di risoluzione. Le riqualifiche `.requalified-rem0049-repair1` di `0037`, `0005`, `0050`
e `0082` sono di sola regressione, nella classe non qualificante, e supersedono i rispettivi record
`.requalified-rem0049` sigillati; le altre sei riqualifiche sigillate non derivano e restano. Drift 0 all'head
dell'evidenza. Segue la verifica indipendente, da un fornitore diverso da Anthropic e da Google.
