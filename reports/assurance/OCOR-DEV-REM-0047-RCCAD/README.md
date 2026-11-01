# OCOR-DEV-REM-0047-RCCAD — NCP-U01, conformità di C1 (Ontology Compiler & IR Pipeline)

Unità NCP-U01 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (punti 1 e 5), primo `OCOR-DEV-REM-*` libero
verificato in sola lettura all'avvio. Risolve, a sigillo avvenuto, le voci `NCR-C1-002`…`006`, `NCR-C1-008`,
`NCR-C1-009` e `NCR-C1-010` del registro.

Stato: `CANDIDATE_IN_PROGRESS`. Il record `OCOR-DEV-REM-0047.json` contiene per ora le parti che non dipendono
dalla campagna: voci risolte, criteri con i test, ancore di ogni modifica di comportamento o di firma, sonde di
risoluzione, mappatura delle classi di FR-045 riga per riga. Il PO ha deciso il 2026-11-01 la decision request
`NCP-U01-RETAINED-C1-BUILDERS` (opzione 2): i builder retained restano invariati come candidati pre-normativi,
firmatario, admission e publisher rifiutano ogni core diverso da `ocor.cir/1.0`, `test_ocor_dev_0028.py:81`
non cambia, `NCR-C1-002` è `IN_REMEDIATION`. Riqualifiche: `0011` e `0032` con supersession; `0005`, `0028`,
`0031`, `0033`, `0050` e `0082` di sola regressione. Campagna, riqualifiche, revisione preventiva e verifica
indipendente si aggiungono a campagna eseguita.

Implementatore: Claude Code (Anthropic). Nessun file di `inputs/`, ADD, LLD, contratto, schema, registro
normativo, guard, workflow o dipendenza è modificato. `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`.
