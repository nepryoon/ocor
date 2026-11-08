# OCOR-DEV-REM-0057-RCCAD — NCP-U09, runtime causale C7

Unità NCP-U09 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2, 4, 5 e 8), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C7-001` … `NCR-C7-006` del
registro, con le decisioni del punto 4 del piano su `NCR-C7-002` (opzione A con due precisazioni) e su
`NCR-C7-006` (opzione A).

Stato: `CANDIDATE_IN_PROGRESS` (iterazione 3 di stima 4, stop a 12): bozza del record prima della revisione
preventiva; nessuna campagna, nessuna evidenza. Lo SCM registrato `M=(U, V, F, P(U))`, con tolleranza
obbligatoria, sostituisce `F_X` con `do(X=x)` sulla porta del motore, che tiene distinte abduzione, azione e
predizione (abduzione differita, `ELM-070`); l'identificazione deriva dallo SCM con `NOT_IDENTIFIED`; si
confrontano almeno due interventi; `CausalRunOutcome` è `ESTIMATED`, `ABSTAIN`, `REJECTED` o `FAILED` con gli
insiemi chiusi di ADD v1.3, la mappatura decisa dal PO e la precedenza; incertezza e sensibilità accompagnano ogni
stima; il digest non dipende dagli identificativi di traccia; il controfattuale è
`REJECTED{CAPABILITY_DEFERRED, ELM-070}` (RED `b498a6a`, GREEN `c78270b`; consumer riallineati e adattati
`781ce01`, `acc0f70`). Lo `ScenarioRunSpec` immutabile fissa ogni pin; la `CausalQuery` nasce dallo spec e
dall'ipotesi dell'overlay letta alla revisione fissata; il modello causale firmato (DSSE, Ed25519) e verificato al
confine blocca il run con `REJECTED` se firma o digest non tornano (NFR-030); il ledger dei job L2 di C7 su
PostgreSQL realizza il ciclo di vita chiuso di ADD v1.3, quota, backpressure, avanzamento, pausa, cancellazione con
rilascio delle risorse entro `PT30S`, timeout senza risultato parziale e audit append-only (RED `c251812`, GREEN
`3fb9c8f`). L'autocontrollo di robustezza degli input di `NCP-THROUGHPUT-RULES (2026-11-05)` punto 1 ha chiuso due
lacune (RED `10506d3`, GREEN `9c37ca5`; tabella nel record).

Il record `OCOR-DEV-REM-0057.json` contiene criteri, test per voce, ancore, test riallineati (quattordici funzioni
di `test_ocor_dev_0045.py`, una di `test_ocor_dev_rem_0040.py` e una di `test_ocor_dev_rem_0041_overlay.py`,
ciascuna con il suo RED) e adattati, con il confronto dell'albero sintattico rispetto a `ef92062`, scelte di
prodotto, ambiguità risolte in modo fail-closed, punti aperti, esiti dell'inventario dei consumer e la
classificazione delle riqualifiche: tutte di sola regressione (`0045` senza requisiti legabili secondo
`NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`; `0005`, `0050`, `0082` per l'allowlist del piano). Restano
`PRE-CAMPAIGN-GATE`, revisione preventiva, campagna qualificante, riqualifiche e verifica indipendente da un
fornitore diverso da Anthropic e dal revisore preventivo.

Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime conformance `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
