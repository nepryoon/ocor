# OCOR-DEV-REM-0047-RCCAD — NCP-U01, conformità di C1 (Ontology Compiler & IR Pipeline)

Unità NCP-U01 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C1-002`…`006`, `NCR-C1-008`,
`NCR-C1-009` e `NCR-C1-010` del registro.

Stato: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`. Il record `OCOR-DEV-REM-0047.json` contiene voci risolte,
criteri con i test e i loro esiti, ancore di ogni modifica di comportamento o di firma, sonde di risoluzione,
mappatura delle classi di FR-045 riga per riga, PRE-CAMPAIGN-GATE e campagna all'head del codice `1ab725f`
(stack reale, suite completa a due corsie 3359/3359, zero skip, 2429 s su 5400 s); il raw log è
`OCOR-DEV-REM-0047.log`. Il PO ha deciso il 2026-11-01 la decision request
`NCP-U01-RETAINED-C1-BUILDERS` (opzione 2): i builder retained restano invariati come candidati pre-normativi,
firmatario, admission e publisher rifiutano ogni core diverso da `ocor.cir/1.0`, `test_ocor_dev_0028.py:81`
non cambia, `NCR-C1-002` è `IN_REMEDIATION`. Il PO ha deciso il 2026-11-02 la decision request
`NCP-U01-SUPERSESSION-REQUALIFICATIONS` (opzioni A1 e B1): tutte le riqualifiche dell'unità (`0005`, `0011`,
`0028`, `0031`, `0032`, `0033`, `0050` e `0082`) sono di sola regressione, nella classe non qualificante;
`check_regression_record` di `scripts/validate_runtime_evidence.py` ammette che un record di regressione superi
per percorso un record sigillato senza `record_id`, solo se il registro dei record sigillati lo riconosce per
percorso e sha256 (RED `c002b33`, GREEN `c9a7fe7`). I record `*.requalified-rem0047.json` degli otto task sono
inseriti in testa ai rispettivi `MANIFEST.json`; `0028`, `0031` e `0033` superano per percorso i record sigillati
originali. Verifica indipendente richiesta al loop esterno.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
