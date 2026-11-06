# OCOR-DEV-REM-0054-RCCAD — NCP-U08, safety e policy di C6

Unità NCP-U08 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1, 2 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C6-010` … `NCR-C6-013` del
registro, con il criterio aggiuntivo del punto 2 per NCP-U08 (`stop_epoch` firmato, durevole e letto tramite una
porta).

Stato: `CANDIDATE_IN_PROGRESS` (bozza prima dell'autocontrollo di robustezza degli input, della revisione
preventiva e della campagna). Lo stop di emergenza è attivato solo da un Safety Officer autorizzato per un
incidente nominato; ogni transizione pubblica uno `stop_epoch` firmato Ed25519 sulla `StopEpochPort` durevole,
con l'adapter PostgreSQL append-only e compare-and-set, e ogni lettura lo verifica (G-DISPATCH, runtime dei tool
C8, break-glass); il reset richiede due approvatori distinti e la verifica di incidente e ripristino; il
break-glass è una Delegation firmata su ogni campo con motivo tipizzato (RED `0eee9ff`, GREEN `0cd12df`). Il
punto di decisione OPA deriva dal bundle firmato `PermitWithConstraints`, `RequireApproval` e `Obligate`,
rifiuta una qualificazione malformata o ambigua, e `PolicyDecision.admit` ammette una decisione solo se il
consumer ne onora ogni qualificazione (RED `341acf4`, GREEN `3a90e68`). Il gateway C2 e il runtime dei tool C8
valutano il marking con il `ResolvedMarkingEngine`: un marking mancante, sconosciuto o incomparabile è
`MARKING_UNRESOLVED`, il join è il minimo maggiorante conservativo (RED `7aa8342`, GREEN `060e1f5`). Le classi di
rischio portano i nomi di ADD v1.3 senza alias (RED `28e9c48`, GREEN `a1f2750`), con i test di `0030`, `0048`,
`REM-0053` e della fixture d'azione C6 adattati per sola sostituzione biunivoca secondo la decisione del PO
`NCP-U08-RISK-CLASS-NAME-ADAPTATION (2026-11-06)`, opzione 1 (decisa su delega completa del PO).

Il record `OCOR-DEV-REM-0054.json` contiene criteri, test per voce, ancore, test adattati (costruzioni e
precondizioni del caso 3 e righe `ADAPTED` della decisione) con il confronto dell'albero sintattico rispetto a
`78ba179`, scelte di prodotto, ambiguità risolte in modo fail-closed, punti aperti, gli esiti dell'inventario dei
consumer e la classificazione delle riqualifiche: tutte di sola regressione (`0030`, `0034`, `0035`, `0044`,
`0047`, `0048` senza requisiti legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`; `0009`, `0014`
con test invariati; `0005`, `0050`, `0082` per l'allowlist del piano; `REM-0053`, unità non completata, perché lo
richiede `NCP-U08-RISK-CLASS-NAME-ADAPTATION (2026-11-06)` opzione 1, aggiunta nel ciclo di riparazione 1 dopo
il finding VF-001 della verifica `OCOR-DEV-REM-0054-84443cf94590-0`). Restano da eseguire: autocontrollo di
`NCP-THROUGHPUT-RULES (2026-11-05)` punto 1, PRE-CAMPAIGN-GATE, revisione preventiva, campagna, riqualifiche
`.requalified-rem0054` e verifica indipendente da un fornitore diverso da Anthropic e dal revisore preventivo.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, slice legacy (`c4_marking.py`, `c6_capabilities.py`, `c7_emission.py`), guard o workflow è
modificato. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
