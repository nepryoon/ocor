# OCOR-DEV-REM-0053-RCCAD — NCP-U07, percorso d'azione C6

Unità NCP-U07 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C6-001` … `NCR-C6-009` e
`NCR-C6-014` del registro. La parte di `NCR-C6-004` relativa al runtime dei tool C8 è la voce `NCR-C8-008` di
NCP-U10, per la decisione del PO `NCP-U07-C8-TOOL-RUNTIME-LEASE (2026-11-05)`, opzione 2 (decisa su delega
completa del PO).

Stato: `CANDIDATE_IN_PROGRESS` (bozza prima dell'autocontrollo di robustezza degli input, della revisione
preventiva e della campagna). La FSM di C6 applica ogni transizione solo dal suo stato sorgente, con la guardia
valutata su uno snapshot legato a transizione e azione e con la precedenza dello stop di emergenza (RED `29ed884`,
GREEN `a148287`). I tredici record canonici di C6 sono congelati con il loro digest, ricalcolato da ogni consumer;
G-APPROVAL ammette solo il quorum firmato di umani distinti legato a digest, revisione, release e scadenza della
proposta, G-DECISION solo una Decision firmata, non scaduta e circoscritta (RED `3927a48`, GREEN `e3684e6`).
G-CONTRACT legge la classe di rischio dall'ActionType firmato e attivo della release e un target canonico non è
mai `NOT_REQUIRED` (RED `14ca5c5`, GREEN `73d9492`). La CapabilityLease chiusa e firmata, al massimo PT5S, è
verificata al confine e consumata una sola volta nella transazione del DeliveryAttempt; l'EMISSION-FENCE valuta
G-FRESHNESS e G-DISPATCH in modo atomico prima di ogni invio a C3 (RED `83b2797`, GREEN `27c53a2`). Un esito
ambiguo si riconcilia solo con Evidence positiva del suo comando, su un riconciliatore che scrive sulla catena di
audit firmata (RED `32b0262`, GREEN `24fd631`). La promozione della memoria passa per lo stesso percorso C6 e non
chiama mai C3 da sola (RED `3c0fb95`, GREEN `93c49b6`). La radice di composizione `c6/composition.py` compone il
percorso con un solo stop di emergenza per dispatch, percorso canonico e C3, il break-glass sullo stesso stop, il
riconciliatore auditato e la FSM con la traccia auditata: un'azione attraversa `ACT-T01` … `ACT-T22` in ordine
canonico (RED `6f825a7`, `266cede`, GREEN `295a307`).

Il record `OCOR-DEV-REM-0053.json` contiene criteri, test per voce, ancore, test riallineati (quattro asserzioni
di test sigillati, ciascuna con il suo RED) e adattati con il confronto dell'albero sintattico rispetto a
`d7a62b1`, scelte di prodotto, ambiguità risolte in modo fail-closed, punti aperti, gli esiti dell'inventario dei
consumer e la classificazione delle riqualifiche: tutte di sola regressione (`0030`, `0031`, `0042`, `0043`,
`0044`, `0058` senza requisiti legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`; `0005`, `0050`,
`0082` per l'allowlist del piano). Restano da eseguire: autocontrollo di `NCP-THROUGHPUT-RULES (2026-11-05)`
punto 1, PRE-CAMPAIGN-GATE, revisione preventiva, campagna, riqualifiche `.requalified-rem0053` e verifica
indipendente da un fornitore diverso da Anthropic e dal revisore preventivo.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy (`c6_capabilities.py`, `c7_emission.py`), guard o workflow è modificato. `E1=0`, `E2=0`,
`Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
