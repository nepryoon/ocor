# OCOR-DEV-REM-0057-RCCAD — NCP-U09, runtime causale C7

Unità NCP-U09 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 4, 5 e 8), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C7-001` … `NCR-C7-006` del
registro, con le decisioni del punto 4 del piano su `NCR-C7-002` (opzione A con due precisazioni) e su
`NCR-C7-006` (opzione A).

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION` sul commit di codice `10e9473` (iterazione 4 di stima 4, stop a
12). Lo SCM registrato `M=(U, V, F, P(U))`, con tolleranza obbligatoria, sostituisce `F_X` con `do(X=x)` sulla porta
del motore, che tiene distinte abduzione, azione e predizione (abduzione differita, `ELM-070`); l'identificazione
deriva dallo SCM con `NOT_IDENTIFIED`; si confrontano almeno due interventi; `CausalRunOutcome` è `ESTIMATED`,
`ABSTAIN`, `REJECTED` o `FAILED` con gli insiemi chiusi di ADD v1.3, la mappatura decisa dal PO e la precedenza;
incertezza e sensibilità accompagnano ogni stima; il digest non dipende dagli identificativi di traccia; il
controfattuale è `REJECTED{CAPABILITY_DEFERRED, ELM-070}` dopo il controllo della sua struttura (RED `b498a6a`,
GREEN `c78270b`; consumer riallineati e adattati `781ce01`, `acc0f70`). Lo `ScenarioRunSpec` immutabile fissa ogni
pin e porta come contesto il record `GovernedContext` v1.2 completo e chiuso di ADD v1.3 §1.4, legato ai pin del
run; la `CausalQuery` nasce dallo spec e dall'ipotesi dell'overlay letta alla revisione fissata; il modello causale
firmato (DSSE, Ed25519) e verificato al confine blocca il run con `REJECTED` se firma o digest non tornano
(NFR-030); il ledger dei job L2 di C7 su PostgreSQL realizza il ciclo di vita chiuso di ADD v1.3, quota,
backpressure, avanzamento, pausa, cancellazione con rilascio delle risorse entro `PT30S`, timeout senza risultato
parziale e audit append-only (RED `c251812`, GREEN `3fb9c8f`). L'autocontrollo di robustezza degli input ha chiuso
due lacune (RED `10506d3`, GREEN `9c37ca5`).

La revisione preventiva `OCOR-DEV-REM-0057-1a64cb83f153-pre` (Antigravity CLI, Google) ha dato `BLOCKING_FINDINGS` con cinque finding
bloccanti e tre consultivi. I bloccanti sono corretti (RED `b936fb8`, GREEN `7c11a44` e `cb3220b`): contesto di
governo completo di ADD v1.3 §1.4; l'intero adapter SeaweedFS con risposte S3 verificate per struttura, errori di
trasporto tradotti e solo JSON finito; ogni riga del ledger PostgreSQL verificata nella forma e nella coerenza
fra stato, esito e guasto; rilascio delle risorse su ogni percorso del runner; popolazione dell'ipotesi non finita
rifiutata. I consultivi sono accolti: elenco per funzione dei quattordici test riallineati di `0045`, struttura
del controfattuale prima del differimento, descrittore di sensibilità decimale. La tabella di autocontrollo nel
record copre ora ogni adapter e percorso di parsing toccato. PRE-CAMPAIGN-GATE al commit di codice 50/51, con la
sola deriva attesa di `0005`, `0045`, `0050` e `0082`.

Campagna `PASS` da shell pulita: moduli dell'unità con le suite di registro, REM-0046 e validator dell'evidenza tre
volte (281 casi per run) sullo stack reale (PostgreSQL, TerminusDB, SeaweedFS), modulo riallineato di `0045`,
consumer `REM-0040` e `REM-0041`, regressione di `0005`, `0050`, `0082`, portfolio di `reports/tests`, e suite
completa con l'orchestratore versionato (`FOUR_LANE`, 4 corsie eseguite) 5304/5304, zero skip, JUnit uguale alla
collezione, 1619.6 s sul tetto di 5400 s.

Le quattro riqualifiche `.requalified-rem0057` sono di sola regressione, nella classe non qualificante di
`REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`: `0045` senza requisiti legabili secondo
`NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`, con il confronto dell'albero sintattico; `0005`, `0050`, `0082`
per l'allowlist del piano. Inserimento chirurgico nei MANIFEST, deriva zero all'head candidato. Resta la verifica
indipendente da un fornitore diverso da Anthropic e Google, poi sigillo, merge e state sync.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro normativo
diverso dal registro di conformità, workflow o guard di invarianza è modificato. `E1=0`, `E2=0`, `Verified=0`,
runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
