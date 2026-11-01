# OCOR-DEV-REM-0047-RCCAD — NCP-U01, conformità di C1 (Ontology Compiler & IR Pipeline)

Unità NCP-U01 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C1-002`…`006`, `NCR-C1-008`,
`NCR-C1-009` e `NCR-C1-010` del registro.

Stato: `CANDIDATE_IN_PROGRESS`. Il record `OCOR-DEV-REM-0047.json` contiene per ora le parti che non dipendono
dalla campagna né dalla decisione del PO: voci risolte, criteri con i test, ancore di ogni modifica di
comportamento o di firma, sonde di risoluzione. La voce `NCR-C1-002` (firma e admission) passa a
`IN_REMEDIATION` dopo la disposition del PO sulla decision request `NCP-U01-RETAINED-C1-BUILDERS` (PR #438),
da cui dipendono anche il riallineamento di `test_ocor_dev_0028.py:81`, le riqualifiche di `0028`, `0031` e
`0033`, la campagna, il sigillo e il merge. Campagna, riqualifiche, revisione preventiva e verifica
indipendente si aggiungono a campagna eseguita.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
