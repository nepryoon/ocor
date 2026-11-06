# NCP-U08-ITERATION-LIMIT

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0054`
(NCP-U08 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, sicurezza e policy di C6; branch
`governed/ocor-dev-rem-0054-ncp-u08-c6-safety-policy`, head di lavoro `ff0508c`, non candidato). Aperta secondo il
punto 2 di `NCP-THROUGHPUT-RULES (2026-11-05)` («lo stop con decision request scatta quando le iterazioni
superano tre volte la stima `estimate_iterations` dell'unità»): la stima di NCP-U08 è 3 iterazioni
(`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`, `plan_units.NCP-U08.estimate_iterations`), il triplo è
9 e la nona iterazione si chiude con il ciclo di riparazione 1 preparato ma senza candidato. Implementatore:
Claude Code (Anthropic), implementatore di riserva, unico implementatore dell'unità in tutte le iterazioni.

## Contesto

- Le quattro voci dell'unità (`NCR-C6-010`–`013`) sono GREEN sullo stack reale dalla quarta iterazione;
  autocontrollo di robustezza degli input (RED `4bc3bfc`, GREEN `d614bbd`) e correzioni della revisione preventiva
  (RED `3e631d5`, GREEN `1963c9d`) sono integrati nel commit di codice `f22de614311f`. Due decisioni dell'unità sono
  state prese durante il lavoro: `NCP-U08-RISK-CLASS-NAME-ADAPTATION (2026-11-06)` (opzione 1) e
  `NCP-U08-LANE-TEMPORAL-READINESS (2026-11-06)` (opzioni A1 e B1).
- Campagna al commit di codice `f22de614311f` `PASS` (ottava iterazione): suite completa seriale sullo stack
  dell'host 4982/4982, zero skip, 3961.4 s sul tetto di 5400 s; candidato `84443cf94590`.
- La verifica indipendente `OCOR-DEV-REM-0054-84443cf94590-0` ha dato `NO_GO` con un solo finding bloccante
  (`VF-001`, gravità high): manca la riqualifica di sola regressione di `OCOR-DEV-REM-0053` che l'opzione 1 di
  `NCP-U08-RISK-CLASS-NAME-ADAPTATION` impone insieme a quella di `OCOR-DEV-0048`, e la nota della classificazione
  in `reports/assurance/OCOR-DEV-REM-0054-RCCAD/OCOR-DEV-REM-0054.json` elencava `REM-0053` fra i task non
  completati. Tutti gli altri controlli della verifica sono `PASS` (suite completa seriale ripetuta dal verifier
  4982/4982, 4044.6 s).
- Ciclo di riparazione 1 (nona iterazione), sul branch dell'unità:
  - `145dc23`: revert dell'evidenza candidata del ciclo 0 (nessun record era sigillato);
  - `4b0d8cc`: allowlist di `scripts/validate_ocor_development_plan.py` per
    `reports/evidence/G4/OCOR-DEV-REM-0053.requalified-rem0054.json` e `.log`, con il solo self-hash di
    `reports/planning/OCOR_PLAN_RUN_STATE.json`;
  - `ff0508c`: `OCOR-DEV-REM-0053` nella classificazione delle riqualifiche del record dell'unità (sola
    regressione, nessun requisito legabile secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)` punti 1, 3 e 4,
    `supersedes` verso il record sigillato `OCOR-DEV-REM-0053-90028ba369a5` senza modificarlo) e nota corretta;
  - PRE-CAMPAIGN-GATE all'head `ff0508c` e richiesta della revisione preventiva del ciclo di riparazione, come
    prevede il punto 1 di `PRE-CAMPAIGN-REVIEW (2026-10-26)` per le riparazioni che eseguono una suite completa.
- La modifica dell'allowlist cambia `scripts/`, quindi il commit di codice della campagna: la campagna completa
  (qualifiche, modulo d'unità, moduli adattati, consumer, regressione, portfolio e suite completa seriale secondo
  l'opzione A1 di `NCP-U08-LANE-TEMPORAL-READINESS`) va rieseguita all'head della riparazione, con dodici
  riqualifiche di sola regressione (le undici del ciclo 0 e `REM-0053`). Codice e test dell'unità non cambiano.
- Iterazioni residue previste senza altri cicli di riparazione: 2 (esito della revisione preventiva, campagna,
  candidato e richiesta di verifica; integrazione: sigillo, PR, check, merge e state sync). Con una nuova verifica
  `NO_GO` serve il ciclo di riparazione 2, l'ultimo ammesso: fino a 2 iterazioni in più (correzione con revisione
  preventiva; campagna e candidato), più l'integrazione già contata.

## Opzioni

1. **Fino a quattro iterazioni oltre la nona (raccomandata).** Per `OCOR-DEV-REM-0054` sono autorizzate fino a
   quattro iterazioni oltre la nona (dalla decima alla tredicesima), solo per il residuo descritto nel contesto:
   due per il ciclo di riparazione 1 fino al merge e due per il ciclo di riparazione 2, se una verifica `NO_GO` lo
   richiede. Resta lo stop anticipato per due iterazioni consecutive senza avanzamento. Se finiscono senza merge,
   l'unità si ferma e apre una decision request di livello normativo con lo stato del lavoro. Effetto: l'unità
   arriva al merge con il lavoro già fatto e con il margine per l'ultimo ciclo di riparazione ammesso; la
   remediation B1 di `NCP-U08-LANE-TEMPORAL-READINESS` e le unità successive di `plan_order` attendono fino ad
   allora.
2. **Fino a due iterazioni oltre la nona.** Come l'opzione 1, con due iterazioni (la decima e l'undicesima).
   Effetto: basta per arrivare al merge se la nuova verifica dà `GO_FOR_EVIDENCE_SEAL`; con un `NO_GO` l'unità si
   ferma di nuovo con una decision request.
3. **Sospensione dell'unità.** NCP-U08 si ferma all'head `ff0508c`, senza candidato; il branch resta. Le unità
   successive di `plan_order` che non dipendono da NCP-U08 partono. Effetto: le voci `NCR-C6-010`–`013` restano
   `OPEN` su `main` e i task G6 che esse bloccano restano bloccati; la remediation B1 di
   `NCP-U08-LANE-TEMPORAL-READINESS`, prevista dopo l'integrazione di NCP-U08, resta in attesa; la ripresa di
   NCP-U08 richiede una nuova decisione.

**Raccomandazione**: opzione 1. Il solo finding della verifica riguarda un record di evidenza mancante, non il
codice né i test; la riparazione è pronta e la campagna già una volta `PASS` va ripetuta all'head della
riparazione. Quattro iterazioni coprono il percorso fino al merge e l'ultimo ciclo di riparazione ammesso con un
limite fisso, come le estensioni delle unità precedenti (`NCP-U05-ITERATION-LIMIT`, opzione A1); l'opzione 2
rischia una seconda richiesta per lo stesso motivo; l'opzione 3 lascia aperte quattro voci già GREEN.

## Impatto e task bloccati

- Bloccati fino alla decisione: la prosecuzione di `OCOR-DEV-REM-0054` oltre la nona iterazione e, di
  conseguenza, la remediation B1 di `NCP-U08-LANE-TEMPORAL-READINESS` e le unità successive di `plan_order`
  (NCP-U09, U10, U11, U12), che partono una alla volta dopo NCP-U08.
- Nessun test, limite di tempo, soglia, workflow, guard, contratto, schema o registro normativo cambia; il numero
  massimo di cicli di riparazione resta 2. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
