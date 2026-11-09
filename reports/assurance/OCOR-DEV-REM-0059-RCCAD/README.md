# OCOR-DEV-REM-0059-RCCAD — NCP-U11, memoria governata

Unità NCP-U11 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-MEMORY-001` … `NCR-MEMORY-005`
del registro di conformità.

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION` sul commit di codice `636975e`, ciclo di riparazione 1
(iterazione 9 di stima 3, estensione fino alla tredicesima per `NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09)` B1). Gli adapter reali di PostgreSQL (metadata, contenuti, full-text), Qdrant e OpenBao Transit passano da
`test_ocor_dev_0051.py` al pacchetto `ocor_runtime.memory.adapters` (criterio aggiuntivo del punto 2). La
partizione di policy precede la query ed è valutata dentro PostgreSQL e Qdrant (`NCR-MEMORY-001`, RED `7b930a8`,
GREEN `ab65f96`); la quota di ammissione si applica dentro un hold serializzato e conta anche gli item ammessi e
non ancora committati (`NCR-MEMORY-002`, RED `a837a53`, GREEN `f527ca4`); l'oblio di `LATEST_VERSION` e degli scope
`PROJECT`/`PRINCIPAL` passa dalla saga, con il replay legato all'insieme dei membri registrato (`NCR-MEMORY-003`,
RED `50fdb6e`, GREEN `2a017be`); la lettura di una versione esatta è autorizzata, materializzata e auditata
(`NCR-MEMORY-004`, RED `2dd02ec`, GREEN `8725b61`); le proiezioni si ricostruiscono per versione e per partizione
(`NCR-MEMORY-005`, RED `e374937`, GREEN `f73b341`). Il guard dei consumer di REM-0023 cambia esattamente come deciso
da `NCP-U11-REM0023-CONSUMER-GUARD (2026-11-09)`, opzione 1 (`8d7fee6`). L'autocontrollo
`SELF-CHECK-CHECKLIST (2026-11-08)` sull'intero modulo degli adapter e sulle classi toccate ha chiuso le lacune
trovate (RED `573ca0b`, GREEN `c5952e8`).

La revisione preventiva `OCOR-DEV-REM-0059-90e47e872c3e-pre` (Codex CLI, OpenAI, revisore di riserva) ha dato `BLOCKING_FINDINGS`
con undici finding bloccanti e uno consultivo. P1-P10 sono corretti (RED `d177078`, GREEN `7801c9c`); P1 è
contestato in parte (il default `quota=None` resta la composizione dei mondi consumatori sigillati e sorvegliati,
punto aperto per la verifica); P11 è realizzato dalle riqualifiche di REM-0023 e REM-0036 con supersession; il
consultivo P12 è accolto: la traccia del PRE-CAMPAIGN-GATE dell'head finale è nel record, 50/51 al commit di
codice, con la sola deriva attesa dei nove task di backlog riqualificati.
Il candidato `3425a01` del ciclo 0 ha avuto `NO_GO` dalla verifica indipendente
`OCOR-DEV-REM-0059-3425a01a39c1-0` (Cursor CLI, xAI): `VF-001` (alta) è corretto dopo le decisioni
`NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09)` (A1, B1) e `NCP-U11-ADMISSION-QUOTA-WORLDS (2026-11-09)`
(opzione 1): `admitMemory` rifiuta prima di ogni scrittura senza autorità di quota, con un valore errato o con un
hold che non è un context manager (RED `390ee12`/`540ecf6`, GREEN `3a13bcb`/`ac0928f`), con il port di quota di
test esplicito nei nove punti sigillati e l'estensione del guard di REM-0023 (`d751aaf`); `VF-002` (media) è
corretto nella tabella dell'autocontrollo. La revisione preventiva del ciclo 1 `OCOR-DEV-REM-0059-5a5d301bbdf1-pre` ha dato tre
finding bloccanti, tutti corretti e nessuno contestato: digest dei journal confrontati solo come URN sha256 ASCII
(`digests_equal`) e campi del record controllati prima della conversione; validatori condivisi di ogni risposta di
metadata, ledger e tombstone nel lifecycle e nei consumatori gemelli di stores, operations e retrieval; surrogati
isolati rifiutati da `_strict_json` (RED `a961656`/`d0cca26`, GREEN `78d755d`/`21db552`). I record candidati del
ciclo 0 non sigillati sono rimossi con le loro righe di MANIFEST e ricostruiti (`superseded_candidate_evidence`).
Una prima campagna completa `PASS` all'head `e113118` è superata: il plan validator, eseguito sull'albero
dell'evidenza costruito da quella campagna, ha trovato l'allowlist priva dei record di REM-0023/REM-0036 (P11) e
del MANIFEST di G6; l'allowlist è completata in `16c24d9` (input delle riqualifiche di `0005`, `0050`, `0082`) e
gate e campagna sono ripetuti a quel commit; anche la campagna `PASS` a `16c24d9` (candidato `NO_GO`) è superata,
senza trasferire alcun conteggio (`superseded_campaigns`).

Campagna `PASS` da shell pulita: modulo dell'unità con le suite di registro, REM-0046 e validator dell'evidenza tre
volte (341 casi per run) sullo stack CI reale con Qdrant e OpenBao per modulo; moduli di `0051`, `0052`, `0054`,
`0055`, `0059`, FGM-01..10 (`0061`), `REM-0023` con il suo guard e `REM-0036`; consumer `0053`, `0056`, `0057`,
`REM-0020`, `REM-0021`, `0058`, `REM-0050`, `REM-0053`; regressione di `0005`, `0050`, `0082`; portfolio di
`reports/tests`; suite completa con l'orchestratore versionato (`FOUR_LANE`, 4 corsie eseguite) 5826/5826, zero skip,
JUnit uguale alla collezione, 1841.4 s sul tetto di 5400 s.

Le undici riqualifiche `.requalified-rem0059` sono di sola regressione, nella classe non qualificante di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: `0051`, `0052`, `0055` e `REM-0023` senza requisiti
legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`, con il confronto dell'albero sintattico; `0054`,
`0059`, `0061` e `REM-0036` con test invariati; `0005`, `0050`, `0082` per l'allowlist del piano. Inserimento
chirurgico nei MANIFEST, deriva zero all'head candidato. Resta la verifica indipendente da un fornitore diverso da
Anthropic e OpenAI, poi sigillo, merge e state sync.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro normativo
diverso dal registro di conformità, workflow o guard di invarianza è modificato; il solo guard toccato è quello di
REM-0023, nei limiti dell'opzione 1 decisa. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
Production `NO-GO`.
