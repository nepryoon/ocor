# NCP-U07-C8-TOOL-RUNTIME-LEASE

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0053`
(NCP-U07 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, percorso d'azione C6; branch
`governed/ocor-dev-rem-0053-ncp-u07-c6-action-path`) e la voce `NCR-C6-004` di
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta secondo il punto 1 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` e il punto 4.d di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`
(una voce la cui attuazione richiede un'interpretazione della norma non univoca si decide, non si sceglie
nell'unità). Implementatore: Claude Code (Anthropic), implementatore di riserva del loop, per tutte le iterazioni
dell'unità.

## Contesto

- `NCR-C6-004` (gravità `HIGH`, requisiti `FR-162` e `NFR-047`, `plan_unit` `NCP-U07`) afferma che il
  `CapabilityLease` normativo «exist[s] in kernel/governance.py but [is] used only by the Temporal lease-state
  adapter; the engine, the C8 tool runtime and the legacy fence use the legacy c6_capabilities lease». Fra i suoi
  `code_refs` c'è `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py` riga 107 («C8 imports the legacy lease»).
  Il criterio di accettazione di NCP-U07 per la voce cita ADD v1.3 §5.2 (righe 3194-3212), LLD v1.1 §1.4
  (righe 69-81) e §0.2 (riga 25), `capability-lease.schema.json` e `FR-162`; il test RED del piano per la voce
  verifica il solo motore C6 («C6-4 engine lease type: ocor_runtime.c6_capabilities»).
- Stato dell'unità: il percorso d'azione C6 è conforme a `NCR-C6-004` dal GREEN `27c53a2`
  (`ocor-runtime/src/ocor_runtime/c6/dispatch.py`: lease firmato dall'authority di capability, al massimo `PT5S`,
  consumato da `LeaseValidator` nella transazione del `DeliveryAttempt`, con tutti i reason code di LLD v1.1 §1.4);
  il motore non usa più il lease legacy.
- Il tool runtime C8 (`ocor-runtime/src/ocor_runtime/c8/tool_runtime.py`) usa ancora
  `ocor_runtime.c6_capabilities.CapabilityAuthority` e il suo `CapabilityLease` (slice legacy, che non cambia):
  riga 107 (import), riga 303 (`bind_stop_controller`), righe 324-337 (`authorize_effect`, canale dell'effetto),
  righe 356-358 (`invoke`, consumo del lease all'autorizzazione), righe 432-438 (`_authorize_tool`, a ogni
  dispatch). Il lease legacy copre più tool in un'espressione (capability `tool:<nome>`), con TTL scelto dal
  chiamante e senza `action_instance_id`, `gate_package_digest` né `governed_context_digest`. Lo stesso runtime
  costruisce per difetto un `OutcomeReconciler` non auditato (riga 309), mentre dal GREEN di `NCR-C6-007` il
  percorso d'azione C6 riconcilia solo con un reconciler che scrive sull'audit port firmato.
- La norma:
  - ADD v1.3 riga 3194: il Capability Lease «lega una singola chiamata mutativa all'epoca di contenimento
    corrente»; il record (righe 3197-3209) ha `action_instance_id` e `gate_package_digest`; riga 3212: monouso per
    `(action_instance_id, emission_attempt)`; riga 3360: «Ogni mutative call presenta una capability lease con
    `stop_epoch` corrente e TTL non superiore a 5 secondi»;
  - ADD v1.3 riga 1992 (fence del profilo PoC) e riga 3114 (§4.3.1, invariante 2): nel profilo PoC gli autonomy
    tier sono `OBSERVE`, `ANALYZE`, `SIMULATE` e `PROPOSE`; nessun Tool Contract con
    `effect_class=EXECUTE_APPROVED_ACTION` entra nel release bundle PoC; `execute-approved` appartiene al solo
    percorso governato dopo Decision (cioè al motore C6). Nel profilo PoC una chiamata di tool C8 non è dunque una
    chiamata mutativa e non ha un `GatePackage`;
  - ADD v1.3 riga 3856 (§2.12): «Tool invocation always re-evaluates live capability, delegation, policy, memory
    instruction eligibility and stop epoch»; riga 3220: una revoca invalida nuove chiamate e capability lease non
    ancora consumate.
- La rivalutazione dal vivo di capability, Delegation, policy, autonomy tier ed eleggibilità delle istruzioni a
  ogni dispatch, il Tool Contract con `effect_class` e un kernel C8 senza default permissivo sono nell'ambito di
  NCP-U10 (voci `NCR-C8-004`, `NCR-C8-005`, `NCR-C8-007`; `plan_units.NCP-U10.code_paths` comprende
  `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py` e `ocor-runtime/src/ocor_runtime/c6_capabilities.py`).
  `NCR-C8-007` cita come difetto proprio `CapabilityLease.is_active` del lease legacy (riga 108 di
  `ocor-runtime/src/ocor_runtime/c6_capabilities.py`).
- La norma non dice quale controllo sostituisce, nel tool runtime C8 del profilo PoC, il lease legacy: il
  `CapabilityLease` di §5.2 presuppone una chiamata mutativa con action instance e `GatePackage`, che nel profilo
  PoC una chiamata di tool non ha. Applicarlo a ogni chiamata di tool richiederebbe di fabbricare un'action
  instance e un digest di `GatePackage` per chiamate non mutative.

## Opzioni

1. **La parte C8 passa a NCP-U10 (raccomandata).** `NCR-C6-004` è risolta da NCP-U07 sul percorso d'azione C6,
   l'unico che nel profilo PoC emette chiamate mutative (ADD v1.3 righe 1992 e 3114). NCP-U07 non modifica
   `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py`, `ocor-runtime/tests/tasks/test_ocor_dev_0047.py` né
   `ocor-runtime/tests/tasks/test_ocor_dev_rem_0027.py`. Il registro riceve, in `plan_units.NCP-U10`, un criterio
   di accettazione aggiuntivo per `NCR-C8-005` e `NCR-C8-007`: il tool runtime C8 non usa più
   `ocor_runtime.c6_capabilities` (né `CapabilityAuthority` né il suo `CapabilityLease`) e a ogni dispatch
   rivaluta dal vivo capability, Delegation, policy e stop epoch (ADD v1.3 righe 3220 e 3856); il runtime non
   costruisce un `OutcomeReconciler` non auditato per difetto e registra ogni esito `EXECUTION_UNKNOWN` sul
   reconciler che scrive sull'audit port firmato (Register `FR-163`). La voce `NCR-C6-004` riceve nel record di
   risoluzione di NCP-U07 la nota che la menzione del tool runtime C8 nel suo `statement` è risolta da NCP-U10
   secondo questo criterio. Effetto: NCP-U07 resta nel suo percorso; il tool runtime cambia una sola volta,
   nell'unità che introduce il Tool Contract e la rivalutazione dal vivo; nessuna riqualifica di
   `OCOR-DEV-0047` o `OCOR-DEV-REM-0027` in NCP-U07.
2. **Voce nuova per il tool runtime in NCP-U10.** Come l'opzione 1, ma la parte C8 diventa una voce nuova del
   registro, `OPEN`, gravità `HIGH`, componente C8, `plan_unit` `NCP-U10`, requisiti `FR-162`, `NFR-036` e
   `FR-163`, ancore ADD v1.3 righe 3220, 3360 e 3856, `code_refs` le righe di
   `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py` elencate nel contesto, `blocks` uguale a quello di
   `NCR-C6-004`; `plan_units.NCP-U10.resolves` la comprende, con il criterio dell'opzione 1. Effetto: la parte C8
   è tracciata da una voce propria, con un test RED proprio in NCP-U10; per il resto come l'opzione 1.
3. **Lease normativo nel tool runtime ora, in NCP-U07.** NCP-U07 sostituisce nel tool runtime C8 il lease legacy
   con il `CapabilityLease` firmato di `ocor-runtime/src/ocor_runtime/c6/dispatch.py` per ogni chiamata di tool:
   ogni chiamata diventa un'action instance con un proprio `emission_attempt` e un `gate_package_digest` calcolato
   sulla richiesta della chiamata; il lease, al massimo `PT5S`, è consumato al dispatch. Sono autorizzati gli
   adattamenti di costruzione (caso 3 del punto 5) dei lease di `ocor-runtime/tests/tasks/test_ocor_dev_0047.py`
   (righe 69-99) e del harness di `ocor-runtime/tests/tasks/test_ocor_dev_rem_0027.py`, e le riqualifiche di
   `OCOR-DEV-0047` e `OCOR-DEV-REM-0027`. Effetto: introduce per chiamate non mutative un digest di `GatePackage`
   che non corrisponde ad alcun `GatePackage`, contro ADD v1.3 riga 3194 e il criterio di orientamento al
   prodotto (nessun surrogato da sostituire in seguito); NCP-U10 riscriverà comunque lo stesso codice per la
   rivalutazione dal vivo; più lavoro e più riqualifiche in NCP-U07.

**Raccomandazione**: opzione 1. Segue la lettera di ADD v1.3 righe 3194 e 3360 (il lease lega una chiamata
mutativa) e il fence del profilo PoC (righe 1992 e 3114), non fabbrica binding e assegna il cambiamento del tool
runtime all'unità che ne possiede il contratto e la rivalutazione dal vivo. L'opzione 2 è equivalente nel merito,
con una voce di registro in più.

## Impatto e task bloccati

- Fino alla decisione, NCP-U07 non dichiara risolta `NCR-C6-004` e non tocca il tool runtime C8; prosegue con
  `NCR-C6-009` e `NCR-C6-014`. Nessun task del backlog è bloccato oltre a quelli che le voci di NCP-U07 già
  bloccano (`OCOR-DEV-0060`, `0063`, `0064` per `NCR-C6-004`).
- Con le opzioni 1 e 2 cambiano soltanto, nel registro, i criteri (e con l'opzione 2 `resolves` e una voce nuova)
  di NCP-U10, e la nota di risoluzione di `NCR-C6-004`. Nessun limite, soglia, workflow, guard, contratto, schema,
  registro normativo o test esistente cambia. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
