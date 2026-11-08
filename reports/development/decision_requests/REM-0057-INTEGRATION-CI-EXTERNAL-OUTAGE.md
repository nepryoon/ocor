# REM-0057-INTEGRATION-CI-EXTERNAL-OUTAGE

Status: `OPEN_PO_DECISION_REQUIRED`. Livello: operativo. Riguarda l'integrazione dell'unità `OCOR-DEV-REM-0057`
(NCP-U09 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, runtime causale di C7), PR #544 dal branch
`governed/ocor-dev-rem-0057-ncp-u09-c7-causal-runtime`, HEAD sigillato `7d0d9965ea5e52af151e4d2c57ee536f70e8287c`.
Aperta perché il paragrafo 5 punto 8 di `CC-OCOR-DELIVERY-COMPLETION` ammette, per un fallimento infrastrutturale,
«un solo rerun dei job falliti», e quel rerun è stato consumato senza esito. Implementatore: Claude Code (Anthropic),
unico implementatore dell'unità.

## Contesto

- Verdetto `OCOR-DEV-REM-0057-4e1a87c2a49a-0`: `GO_FOR_EVIDENCE_SEAL` (Cursor CLI / grok-4.7-high / xAI), un finding
  non bloccante `VF-001` accettato con un campo descrittivo prima del sigillo. Il sigillo `7d0d996` riguarda il record
  dell'unità e quattro riqualifiche di sola regressione. Il PRE-CAMPAIGN-GATE sull'HEAD sigillato è 51/51 `PASS`.
- Primo tentativo CI della PR #544 (run `42469221327`, `42469221388`, `42469221419`, `42469221501`, `42469221713`;
  avvio 2026-11-08 09:56 UTC): 23 check falliti, tutti nei passi di preparazione. I passi sono
  `actions/setup-python`, `astral-sh/setup-uv` e `Install uv`, con l'annotazione «Unexpected HTTP response: 504», e
  `Acquire official checksum-pinned Kubernetes qualification tools` (`scripts/provision_qualification_tools.py`,
  download da `github.com/.../releases/download` e `dl.k8s.io`). I check rimasti fuori dalla preparazione sono
  passati (`contract`, `integration-postgresql`, `supply-chain`, `type-and-lint-gate`,
  `fgm-contract-readiness-not-runtime-evidence`). Nessun test è stato eseguito e fallito.
- La stessa causa ha già fatto fallire, al tentativo e al rerun, lo state sync dell'iterazione precedente
  (PR #543, head `9e4c5f2`, HTTP 504 nello stesso passo), che non contiene codice.
- La pagina di stato di GitHub ha riportato l'incidente «Increase in timeouts for some unauthenticated users».
  Dall'host locale gli asset di release di `github.com` sono rimasti irraggiungibili (504, 503, timeout) dalle 10:30
  alle 11:40 UTC e raggiungibili senza errori dalle 11:40 alle 11:49 UTC.
- L'unico rerun dei job falliti (`gh run rerun <id> --failed` sui cinque run) è partito alle 11:50 UTC, dopo il
  rientro osservato. Diciassette dei ventitré check rifatti sono passati, fra cui gli obbligatori `unit`,
  `evidence`, `mandatory-gates`, `tooling-policy`, `backend-compatibility-not-ba-evidence` e `rccad-methodology`.
  Tre job (`conditional-infrastructure-0049 part 4/5`,
  `delivery-activation part 1/4` e `delivery-activation part 3/4`) sono falliti di nuovo, nello stesso passo di
  acquisizione degli strumenti di qualifica, con `{"error": "The read operation timed out", "status": "FAIL"}`
  alle 11:52 UTC, prima di eseguire qualsiasi test. Di conseguenza falliscono gli aggregati obbligatori
  `delivery-activation` e `validation-closure` (e `conditional-infrastructure-0049`). Nei tre log, zero test
  falliti e zero `AssertionError`.
- Nessun check obbligatorio è fallito per un'asserzione o per il codice sotto esame. Il codice e l'evidenza
  dell'HEAD sigillato non cambiano.

## Opzioni

1. **Un tentativo aggiuntivo sullo stesso HEAD (raccomandata).** È ammesso un solo tentativo aggiuntivo,
   `gh run rerun <run> --failed` dei soli job falliti della PR #544 sull'HEAD `7d0d996`, a queste condizioni:
   ogni fallimento del tentativo precedente è nei passi di preparazione o di acquisizione degli strumenti, con la
   riga di log della causa esterna e zero test falliti (le prove sono nel contesto); prima del tentativo, per
   almeno dieci minuti consecutivi, il download degli asset di release usati dalla CI non ha errori. Se tutti i
   13 check obbligatori sono `success` sull'HEAD esatto, la PR si integra con `--match-head-commit`. Se il
   tentativo fallisce di nuovo per la stessa causa, non si fanno altri tentativi su quell'HEAD e si apre una nuova
   decision request. Un test fallito non è mai infrastruttura. Effetto: l'integrazione si completa senza cambiare
   HEAD, sigillo, workflow o gate.
2. **Nuovo HEAD con un commit di stato.** Sul branch dell'unità si aggiunge un commit che porta solo i tre file di
   stato (`reports/development/EXECUTION_STATE.json`, `ITERATION_LOG.md`, `MODEL_HANDOFF.json`), con un nuovo
   tentativo e un rerun ordinari. Effetto: cambia l'HEAD da integrare. Il sigillo resta valido, perché l'albero
   non di stato non cambia, ma il record registra l'allineamento all'HEAD `1ab141b`, che non sarebbe più l'ultimo
   commit di stato.
3. **Attesa senza nuovi tentativi.** La PR #544 resta aperta finché un'altra modifica di `main` non impone un nuovo
   allineamento. Effetto: NCP-U10 e le unità successive non partono, perché `plan_order` le esegue una alla volta
   dopo NCP-U09. Le voci `NCR-C7-001`–`006` restano `IN_REMEDIATION` su `main`.

**Raccomandazione**: opzione 1. La causa esterna è documentata in entrambi i tentativi e nessun test è fallito.
Diciassette dei ventitré check rifatti sono già passati sullo stesso HEAD, e restano solo i tre job fermi nel
download con i loro aggregati. Un solo tentativo in più, con il controllo
preventivo della raggiungibilità, segue la forma di `MAIN-CI-30MIN-JOB-CAP (2026-10-14)`: un tentativo aggiuntivo
per HEAD, con prove obbligatorie. L'opzione 2 cambia l'HEAD solo per ripetere la CI. L'opzione 3 ferma il
programma senza motivo tecnico.

## Impatto e task bloccati

- Bloccati fino alla decisione: il merge della PR #544 (integrazione di `OCOR-DEV-REM-0057`) e quindi NCP-U10
  (`OCOR-DEV-REM-0058`, primo libero da verificare) e le unità successive di `plan_order`.
- Non bloccati: lo state sync dell'iterazione, che porta solo i tre file di stato.
- Nessun test, limite, timeout, soglia, workflow, guard, contratto, schema, ruleset o registro normativo cambia.
  Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Disposition del Product Owner — 2026-11-08

Decisione del PO, su delega completa (`DELEGA-COMPLETA (2026-11-02)`), modello `claude-opus-5-5`, effort `xhigh`: `REM-0057-INTEGRATION-CI-EXTERNAL-OUTAGE (2026-11-08)`, **opzione 1** (un solo tentativo aggiuntivo `gh run rerun <run> --failed` dei soli job falliti della PR #544 sull'HEAD sigillato `7d0d9965ea5e52af151e4d2c57ee536f70e8287c`, dopo almeno dieci minuti consecutivi senza errori nel download degli asset di release usati dalla CI; integrazione con `--match-head-commit` se tutti i 13 check obbligatori sono `success` sull'HEAD esatto; nessun altro tentativo su quell'HEAD e nuova decision request se fallisce di nuovo per la stessa causa; un test fallito non è mai infrastruttura). Vale come decisione del PO a ogni effetto. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. La richiesta decisa è il file al commit `043ecc5c352a743a765752ef5bc947dc191c15da`, sha256 `690f1a1fb9ba6bc8c24f2a1e13117c7018537beefcd7e2ab3dee8a93c9b6af2d` (verificata prima dell'attuazione). Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### REM-0057-INTEGRATION-CI-EXTERNAL-OUTAGE (2026-11-08) — decisione del PO, su delega completa

Decisa su delega completa del PO secondo `DELEGA-COMPLETA (2026-11-02)`, con il modello `claude-opus-5-5` ed effort `xhigh` (scelta di `claude-opus-5-5` con effort `medium`, delicatezza ALTA). Il PO risolve la decision request `REM-0057-INTEGRATION-CI-EXTERNAL-OUTAGE` (branch `governed/decision-request-rem0057-integration-ci-external-outage`, commit `043ecc5c352a743a765752ef5bc947dc191c15da`, file `reports/development/decision_requests/REM-0057-INTEGRATION-CI-EXTERNAL-OUTAGE.md`, sha256 `690f1a1fb9ba6bc8c24f2a1e13117c7018537beefcd7e2ab3dee8a93c9b6af2d`) adottando l'**opzione 1**.

1. Applica le opzioni scelte esattamente come descritte nel file indicato, a quel commit. Se il file che leggi a quel commit non ha quello sha256, non applicarle e apri una decision request.
2. Se l'attuazione richiede di andare oltre quanto le opzioni scelte descrivono esplicitamente, fermati e apri una decision request: la deciderà la stessa delega.
3. Registra la disposition nel file della decision request, nel registro `blockers` di `EXECUTION_STATE.json` (`po_decision` uguale a questa decisione, con la nota «decisa su delega completa del PO, modello claude-opus-5-5, effort xhigh») e nell'`ITERATION_LOG.md`, con lo stesso trattamento di una decisione del PO. Vale come decisione del PO a ogni effetto, anche dove una regola chiede una decisione del PO non presa su delega.
4. Le altre decisioni e regole vigenti restano invariate, salvo quanto le opzioni scelte cambiano esplicitamente.
