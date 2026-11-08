# OCOR-DEV-REM-0056-RCCAD — suite completa locale in quattro corsie parallele

Change set della decisione operativa del PO `LOCAL-SUITE-FOUR-LANES (2026-11-07)`; non è un'unità di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`. Primo `OCOR-DEV-REM-*` libero verificato in sola lettura all'avvio.

`scripts/run_local_lane_campaign.py` esegue la suite completa locale in quattro corsie (`LANE_COUNT = 4`), ciascuna
con il proprio stack isolato nella propria sandbox. L'ammissione in memoria ha tre livelli con la regola misurata in
`REM-0037` (corsie × 5670,3 MiB più la guardia invariata di 3000 MiB): `FOUR_LANE` da 25681,2 MiB, `TWO_LANE` da
14340,6 MiB (soglia invariata), altrimenti `SERIAL` registrato. Partizione, unione JUnit esatta, supervisione,
risultati e smontaggio lavorano sul numero di corsie ammesso all'avvio; il risultato registra livello e corsie
eseguite; i tetti 5400/3600/5100 s valgono per il tempo complessivo. `run_qualifying_campaign.py`, i workflow e la
CI non cambiano. Il guard `reports/tests/test_local_lane_campaign.py` cambia come autorizza il punto 2 della
decisione (RED `7d2d2ab`, GREEN `52cc194`).

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION` sul commit di codice `de79d98`. L'autocontrollo di robustezza
degli input ha chiuso le prime lacune (RED `533edb4`, GREEN `0fd4780`). La revisione preventiva
`OCOR-DEV-REM-0056-0fd478064f9b-pre` (Antigravity CLI, Google) ha dato `BLOCKING_FINDINGS` con cinque finding
bloccanti e uno consultivo, tutti corretti (RED `555bb32`, GREEN `91ba110`; RED `c82d696`, GREEN `de79d98`): ogni
percorso di parsing dell'orchestratore legge l'input senza conversioni (UTF-8 stretto, cifre ASCII, numeri finiti e
non booleani) e rifiuta il resto con l'errore tipizzato o con il ritorno seriale registrato; ogni processo e ogni
osservatore si fermano su ogni percorso di errore. PRE-CAMPAIGN-GATE al commit di codice 49/50, con la sola deriva
attesa di `0005`, `0050` e `0082`.

Prove del punto 3, nell'ordine e sullo stesso head: `--lifecycle-check` con quattro sandbox `PASS` (bootstrap
parallelo in 190.0, 190.0, 195.0, 190.0 s, ogni servizio tipizzato `READY`, Temporal `SERVING`
0.995, 0.378, 0.851, 1.315 s dopo l'avvio del suo container, nessuno scaglionamento, zero residui); suite
completa non qualificante a quattro corsie 5118/5118 in 1599.4 s, con occupazione di picco complessiva
17082.7 MiB (4270.7 MiB per corsia in media, corsia
maggiore 4535.0 MiB di memoria non recuperabile) e `MemAvailable` minima
34753.7 MiB: nessuna corsia supera 5670,3 MiB e la soglia a quattro corsie
resta invariata; equivalenza fra suite seriale (4346.2 s) e suite a quattro corsie: stesso insieme di casi, zero
skip, entrambe `PASS`, digest d'identità identici. Un primo tentativo non qualificante si è fermato per il limite di
pull non autenticato di Docker Hub (429) ed è registrato come tentativo diagnostico, non conteggiato.

Campagna `PASS` da shell pulita: guard delle corsie con i guard importati tre volte (519 casi per run),
regressione di `0005`, `0050`, `0082`, portfolio di `reports/tests`, suite seriale dell'equivalenza, e suite completa
a quattro corsie con l'orchestratore versionato dell'head (`FOUR_LANE`, quattro corsie eseguite) 5118/5118, zero skip,
JUnit uguale alla collezione, 1564.8 s sul tetto di 5400 s.

Le quattro riqualifiche `.requalified-rem0056` sono di sola regressione, nella classe non qualificante di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: `0005`, `0050`, `0082` per l'allowlist del piano;
`OCOR-DEV-REM-0037`, non selezionata dal validator di deriva, che supersede il record sigillato
`OCOR-DEV-REM-0037-61654ea20771` senza modificarlo. Pesi delle corsie invariati. Inserimento chirurgico nei MANIFEST,
deriva zero all'head candidato. Il file della decision request `NCR-GOVERNANCE-002-MATRIX-ERRATUM` entra su main
byte-identico al commit di disposition. Resta la verifica indipendente da un fornitore diverso da Anthropic e
Google, poi sigillo, merge e state sync.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, test, caso, timer, timeout, soglia dei test, tetto, guard diverso da quello delle corsie o workflow è
modificato. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
