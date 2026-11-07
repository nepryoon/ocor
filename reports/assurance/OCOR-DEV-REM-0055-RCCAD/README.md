# OCOR-DEV-REM-0055-RCCAD — controllo tipizzato di Temporal tollerante all'avvio

Remediation governata B1 della decision request `NCP-U08-LANE-TEMPORAL-READINESS (2026-11-06)`, decisa su delega
completa del PO; non è un'unità di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`. Primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio.

Nella sandbox delle corsie di `scripts/run_local_lane_campaign.py` il frontend di Temporal risponde alla CLI
circa 57-59 s dopo l'avvio del server, mentre l'healthcheck Compose è solo TCP e il controllo tipizzato di
`scripts/verify_external_services.py` lo sondava una sola volta a circa 30-35 s. Ora
`deploy/bootstrap/services/temporal/qualify.py --execute` raggiunge runtime e protocollo attraverso l'attesa
limitata già esistente `wait_ready` (`STARTUP_WAIT_SECONDS = 90.0`) e richiede esattamente lo stesso esito: server
in esecuzione, sano e pubblicato solo su loopback, salute del cluster `SERVING`, versione del lock, namespace
assente rifiutato. Senza `--execute` la sonda resta singola. `verify_external_services.py` limita a 240 s il solo
sottoprocesso di Temporal (60 s per ogni altro script) e la forma della chiamata fissata dal test sigillato di
`REM-0038` resta invariata (RED `1052409`/`bcda5d2`, GREEN `4a5e5f5`).

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION` sul commit di codice `351bb27`. L'autocontrollo di robustezza
degli input (`PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29)`, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 1) ha chiuso le
prime lacune (RED `c51ed23`, GREEN `193559e`). La revisione preventiva `OCOR-DEV-REM-0055-193559ef56e2-pre`
(Antigravity CLI, Google) ha dato `BLOCKING_FINDINGS` con quattro finding bloccanti, tutti corretti (RED
`6f554e3`, GREEN `351bb27`): ogni percorso di parsing di `qualify.py` rifiuta con `QualificationError` un input
malformato, non testuale o non decodificabile, che `wait_ready` ritenta entro il suo limite; `check_temporal`
traduce i fallimenti del sottoprocesso e un payload malformato in un esito tipizzato `UNREACHABLE`, solo per
Temporal come richiede l'opzione B1; i test negativi usano responder locali reali. PRE-CAMPAIGN-GATE al commit di
codice 48/49, con la sola deriva attesa di `0005`, `0050`, `0073`, `0075`, `0079` e `0082`. Campagna `PASS` da
shell pulita: qualifica dei servizi e fault injection (Temporal con pausa, ripresa e riavvio), modulo d'unità tre
volte (231 casi per run, casi live sul Temporal reale inclusi), suite di contratto dei servizi, regressione,
portfolio di `reports/tests`, e suite completa a due corsie 5118/5118, zero skip, JUnit uguale alla collezione,
2587.6 s sul tetto di 5400 s: entrambe le corsie superano il controllo tipizzato di bootstrap dove si erano fermate
le due esecuzioni di `REM-0054`.

Le sette riqualifiche `.requalified-rem0055` sono di sola regressione, nella classe non qualificante di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: `0005`, `0050`, `0082` per l'allowlist del piano;
`0073` e `0075` con i controlli tipizzati e la fault injection; `0079` con il suo modulo e i controlli tipizzati;
`OCOR-DEV-REM-0038`, non selezionata dal validator di deriva, che supersede il record sigillato
`OCOR-DEV-REM-0038-repair1-12659a1cd847` senza modificarlo. Inserimento chirurgico nei MANIFEST, deriva zero
all'head candidato. I file delle decision request `NCP-U08-LANE-TEMPORAL-READINESS` e `NCP-U08-ITERATION-LIMIT`
entrano su main byte-identici ai commit di disposition. Resta la verifica indipendente da un fornitore diverso da
Anthropic e Google, poi sigillo, merge e state sync.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, altro servizio, test esistente, timeout dei test, guard o workflow è modificato. `E1=0`, `E2=0`,
`Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
