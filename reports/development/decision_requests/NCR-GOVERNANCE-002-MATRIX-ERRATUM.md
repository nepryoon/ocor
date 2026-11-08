# NCR-GOVERNANCE-002-MATRIX-ERRATUM

Status: `DECIDED_BY_PO`. Livello: normativo. Riguarda la voce `NCR-GOVERNANCE-002` del registro di conformità
(`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`, componente `GOVERNANCE`, tipo `DIVERGENT`, gravità
`MEDIUM`, stato `DECISION_REQUIRED` fino a questa decisione). Scritto secondo il punto 4 di
`MATRIX-ERRATUM-NCP-U14 (2026-11-07)`: la voce, le sue due opzioni e la decisione del PO come disposition.
Redatto da Claude Code (Anthropic), implementatore di riserva del loop.

## Voce del registro

- Enunciato: nella matrice normativa di tracciabilità (`reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json` e
  `.md`) le colonne di priorità e release sono slittate per più di cento righe: la priorità contiene identificativi di
  decisione o di fonte (per esempio `DEC-063`) e la release contiene dipendenze o stati (per esempio `Confermato`)
  invece dei valori del Register. Il Register v1.1 prevale; correggere la matrice è un erratum normativo del PO.
- Base della gravità: il Register v1.1 prevale e porta i valori corretti; uno strumento che leggesse priorità o
  release dalla matrice otterrebbe valori errati.
- Riferimenti: Register v1.1 riga 112 (`FR-022`, priorità e release,
  `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md`); matrice `.md` riga 46
  (riga di `FR-022` con priorità e release slittate).
- Verifica registrata: il comando della voce stampa 115 (115 delle 285 righe della matrice hanno una priorità fuori da
  `P0`–`P3`), `CONFIRMED` a `12f6088592ce98393b8df119deeb28f626ef46a8`.
- sha256 attuali (verificati alla scrittura di questo file su `main` `045d1cc`): JSON
  `3e321c3fd8f0b7e85c35d888e5273f5f26fae86494b67e3db3876a0eaf09eaeb`, Markdown
  `66f476c3f72fc4a1bc01133dd114058c02c30faa1eca8bf3397c947ecdc6ddeb`.

## Opzioni

1. **Erratum governato della matrice** (JSON e Markdown), rigenerata dal Register v1.1 con una decisione dedicata del PO.
2. **Matrice invariata**: gli strumenti leggono priorità, release, metodo e criteri solo dal Register (decisione del PO
   `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, punto 3).

## Disposition del Product Owner — 2026-11-07

Decisione normativa del PO, con istruzione esplicita: `MATRIX-ERRATUM-NCP-U14 (2026-11-07)`, **opzione 1**. Il testo
integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa
voce. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
`NOT_ESTABLISHED`, PoC e Production `NO-GO`.

### MATRIX-ERRATUM-NCP-U14 (2026-11-07) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita il 2026-11-07. Decide la voce `NCR-GOVERNANCE-002` del registro di conformità (`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`, stato `DECISION_REQUIRED`) con la sua **opzione 1**: erratum governato della matrice normativa di tracciabilità `reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json` (sha256 attuale `3e321c3fd8f0b7e85c35d888e5273f5f26fae86494b67e3db3876a0eaf09eaeb`) e `.md` (sha256 attuale `66f476c3f72fc4a1bc01133dd114058c02c30faa1eca8bf3397c947ecdc6ddeb`), rigenerate dal Requirement Register v1.1. Il Register resta la sola fonte di priorità, release, metodo e criteri per gli strumenti (punto 3 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`): l'erratum corregge il documento, non cambia quella regola. Register, ADD, LLD, contratti, schemi, backlog, piano di tracciabilità, test runtime, limiti e claim non cambiano. Nessun nuovo `DEC-*`, salvo che la procedura vigente lo richieda.

1. **Difetto.** Per 115 delle 285 righe (da `FR-022` a `NFR-087`, secondo la verifica registrata nella voce) i campi della matrice sono slittati rispetto al Register, perché le tabelle del Register dalla riga 110 in poi hanno le colonne `Fonte esatta | Decisione | Domanda di origine` prima di `Priorità`, mentre le prime tabelle hanno la sola colonna `Fonte`. Esempio, `FR-022` (Register riga 112, matrice `.md` riga 46): `priority` contiene `DEC-060`, `release` contiene le dipendenze, `acceptance_criterion` contiene la domanda di origine, `verification_method` contiene `P0`, `dependencies` contiene il criterio di accettazione.
2. **Unità `NCP-U14`.** È un'unità del programma di conformità, aggiunta al piano approvato da questa decisione. Risolve `NCR-GOVERNANCE-002` e nient'altro. Si esegue nel change set della decisione `G7-REVIEW-AND-CANDIDATE-CRITERIA (2026-11-07)`, nella stessa collocazione (dopo l'integrazione di NCP-U12 e prima di `OCOR-DEV-0060`); se quella decisione non è presente in questo file, o il suo change set è già integrato, si esegue da sola nella stessa collocazione. Stima: 2 iterazioni, che si sommano alla stima del change set che la ospita. Contenuto:
   - **Rigenerazione.** Uno script versionato, `scripts/build_traceability_matrix_erratum.py`, deterministico e da riga di comando, legge il Register v1.1 per nome di colonna, tabella per tabella, e riscrive per ogni riga della matrice i soli campi che il Register definisce: `priority`, `release`, `source_authority`, `acceptance_criterion`, `verification_method`, `dependencies` e, se divergono, `title`, `normative_statement`, `type`, `rationale`. Gli altri campi (`decision_linkage`, `risk_conflict_linkage`, `cap_elm_allocation`, `add_obligation_id`, `add_anchor`, `lld_anchor`, `contracts`, `future_evidence_campaign`, `design_disposition`, `evidence_status`) e `reverse_traceability` restano byte per byte come sono. Le 285 righe restano 285, nello stesso ordine; JSON e Markdown sono rigenerati insieme e coincidono riga per riga.
   - **Erratum.** `reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix_ERRATA.md`: per ogni campo corretto, requisito, campo, valore precedente, valore corretto e riga del Register; in testa, questa decisione, gli sha256 di JSON e Markdown prima e dopo, e l'avvertenza che l'autorità della matrice deriva dal Register (`DEC-208`, `DEC-209`) e che l'erratum non cambia alcun requisito. Il campo `authority` del JSON e il testo di controllo in testa al Markdown citano l'erratum.
   - **RED prima del codice.** Un test in `reports/tests/`, `test_traceability_matrix_register_parity.py`, che fallisce sulla matrice attuale e prova, per ogni requisito: `priority` in `P0`–`P3` e uguale alla cella `Priorità` del Register; `release`, `verification_method`, `acceptance_criterion`, `dependencies` e `source_authority` uguali alle celle corrispondenti del Register, lette per nome di colonna; JSON e Markdown coincidenti; gli altri campi uguali a quelli del commit precedente l'erratum. GREEN dopo la rigenerazione. Il test entra fra i guard eseguiti in locale e dal verifier, non nei workflow.
   - **Hash e consumatori.** `docs/development_plan/OCOR_AGENT_CONTEXT_MANIFEST.json` (`normative_core`) e `reports/planning/OCOR_PLAN_RUN_STATE.json` cambiano solo negli hash dei file toccati; `scripts/validate_ocor_development_plan.py`, `scripts/validate_rccad.py`, `reports/tests/test_backlog_generator_reality_parity.py` e i workflow passano invariati; i nuovi percorsi entrano nell'elenco dei percorsi del validatore del piano. Se la parità del generatore richiedesse altro, fermati e apri una decision request.
   - **Registro.** Nello state sync che registra questa decisione: `NCR-GOVERNANCE-002` passa da `DECISION_REQUIRED` a `OPEN` con `plan_unit` `NCP-U14` e `po_decision_ref` al file del punto 4; `plan_units` riceve `NCP-U14` con tutti i campi richiesti dal test d'integrità (`scope`, `resolves` `["NCR-GOVERNANCE-002"]`, `acceptance_criteria` e `red_tests` per la voce con le ancore al Register e alla matrice, `estimate_iterations` 2, `order` 14, `status` `PROPOSED`, `required_backend` nessuno, `depends_on_units` `["NCP-U12"]`); `plan_order` lo aggiunge dopo `NCP-U12`; `plan_summary` si aggiorna; il test d'integrità passa. Nell'unità la voce passa a `IN_REMEDIATION` con `remediation_unit`, `remediation_record` e la prova: il comando della voce stampa 0. Nessun'altra modifica del registro.
   - **Ciclo completo.** Riqualifiche di sola regressione dei record sigillati con input toccati (`0005`, `0050` e `0082` sono sempre previste), `PRE-CAMPAIGN-GATE`, revisione preventiva, suite completa, verifica indipendente, sigillo, merge.
3. **Vincoli.** Nessun requisito cambia testo, priorità, release o metodo: cambia solo la copia nella matrice, che torna uguale al Register. Non toccare `inputs/`, i record sigillati, la slice legacy, i guard di invarianza, i workflow. Un'incoerenza interna del Register (riga senza priorità o release riconoscibile) non si corregge: resta nell'erratum come «non risolvibile dal Register» e diventa una voce nuova `OPEN` del registro, da decidere a parte.
4. **Registrazione.** Al primo state sync scrivi `reports/development/decision_requests/NCR-GOVERNANCE-002-MATRIX-ERRATUM.md` con stato `DECIDED_BY_PO`: la voce, le sue due opzioni, questa decisione come disposition; è il riferimento di `po_decision_ref` (percorso e sha256) ed entra nell'elenco dei percorsi del validatore del piano. Non aggiungere per esso una voce aperta in `blockers`. Registra la decisione come decisione normativa del PO secondo `AGENTS.md` (`po_normative_decisions_registered`, `ITERATION_LOG.md`). Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
